from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from math import isfinite
from typing import Any, Sequence

from .config import load_project_config
from .execution.factory import build_ctrader_research_feed
from .execution.policy import load_execution_policy
from .models import Bar, ensure_utc
from .storage.supabase_operational import SupabaseOperationalStore

SYMBOL = "XAUUSD"
WORKER_NAME = "ctrader_demo_xau_supply_demand_path_outcome_v187"
CONTRACT = "XAU_SUPPLY_DEMAND_PATH_OUTCOME_V187"
STRATEGY_ID = "XAU_SUPPLY_DEMAND_PATH_V187"
EPISODE_TYPE = "SUPPLY_DEMAND_PATH_V187"
ATLAS_WORKER = "ctrader_demo_xau_supply_demand_atlas_v182"

LOOKBACK_DAYS = 45
REQUEST_COUNT = 3000
PATH_EXPIRY_HOURS = 24
CONFIRM_LOOKBACK_BARS = 3
CONFIRM_MIN_BODY_FRACTION = 0.50
CONFIRM_MIN_RANGE_ATR = 0.50
MAX_LEDGER_ROWS = 5000

TERMINAL_STATUSES = {
    "TARGET_REACHED",
    "SOURCE_INVALIDATED",
    "EXPIRED_NO_TARGET",
}


def _finite(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _dt(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def _latest_atlas(store: SupabaseOperationalStore) -> tuple[datetime | None, dict[str, Any]]:
    response = (
        store.client.table("runtime_heartbeats")
        .select("observed_at,healthy,details")
        .eq("worker_name", ATLAS_WORKER)
        .order("observed_at", desc=True)
        .limit(1)
        .execute()
    )
    rows = list(response.data or [])
    if not rows:
        return None, {}
    row = dict(rows[0])
    details = dict(row.get("details") or {})
    return _dt(row.get("observed_at")), dict(details.get("evaluation") or {})


def _closed_m15(rows: Sequence[Bar], *, as_of: datetime) -> tuple[Bar, ...]:
    now = ensure_utc(as_of)
    return tuple(
        row
        for row in sorted(tuple(rows), key=lambda item: ensure_utc(item.timestamp))
        if ensure_utc(row.timestamp) + timedelta(minutes=15) <= now
    )


def _inside(row: Bar, source: dict[str, Any]) -> bool:
    low = float(source["low"])
    high = float(source["high"])
    return float(row.high) >= low and float(row.low) <= high


def _price_inside(price: float, source: dict[str, Any]) -> bool:
    return float(source["low"]) <= price <= float(source["high"])


def _invalidated(row: Bar, source: dict[str, Any], direction: str) -> bool:
    distal = float(source["distal"])
    if direction == "LONG":
        return float(row.close) < distal
    return float(row.close) > distal


def _deep_mitigation(row: Bar, source: dict[str, Any], direction: str) -> bool:
    low = float(source["low"])
    high = float(source["high"])
    midpoint = (low + high) / 2.0
    if direction == "LONG":
        return float(row.low) <= midpoint
    return float(row.high) >= midpoint


def _distal_sweep_reclaimed(row: Bar, source: dict[str, Any], direction: str) -> bool:
    distal = float(source["distal"])
    if direction == "LONG":
        return float(row.low) < distal and float(row.close) >= distal
    return float(row.high) > distal and float(row.close) <= distal


def _proximal_reclaimed(row: Bar, source: dict[str, Any], direction: str) -> bool:
    if direction == "LONG":
        return float(row.close) > float(source["high"])
    return float(row.close) < float(source["low"])


def _reaction_confirmed(
    rows: Sequence[Bar],
    *,
    index: int,
    source: dict[str, Any],
    direction: str,
) -> bool:
    if index < CONFIRM_LOOKBACK_BARS:
        return False
    row = rows[index]
    rng = max(float(row.high) - float(row.low), 1e-12)
    body_fraction = abs(float(row.close) - float(row.open)) / rng
    if body_fraction < CONFIRM_MIN_BODY_FRACTION:
        return False

    atr = _finite(source.get("atr_points"))
    if atr is None or atr <= 0:
        atr = max(float(source["high"]) - float(source["low"]), 1e-12)
    if rng / atr < CONFIRM_MIN_RANGE_ATR:
        return False

    prior = rows[index - CONFIRM_LOOKBACK_BARS : index]
    if direction == "LONG":
        return (
            float(row.close) > float(row.open)
            and float(row.close) > max(float(item.high) for item in prior)
        )
    return (
        float(row.close) < float(row.open)
        and float(row.close) < min(float(item.low) for item in prior)
    )


def _waypoint_hit(row: Bar, *, direction: str, price: float) -> bool:
    if direction == "LONG":
        return float(row.high) >= float(price)
    return float(row.low) <= float(price)


def _target_reached(row: Bar, target: dict[str, Any], direction: str) -> bool:
    if direction == "LONG":
        return float(row.high) >= float(target["low"])
    return float(row.low) <= float(target["high"])


def _path_fingerprint(path: dict[str, Any]) -> str:
    source = dict(path.get("source_zone") or {})
    target = dict(path.get("primary_opposing_zone") or {})
    raw = "|".join(
        (
            str(path.get("reaction_direction") or ""),
            str(source.get("zone_id") or ""),
            str(target.get("zone_id") or ""),
        )
    )
    return sha256(raw.encode()).hexdigest()[:24]


def _episode_key(path: dict[str, Any]) -> str:
    return f"V187:PATH:{_path_fingerprint(path)}"


def _existing_rows(store: SupabaseOperationalStore) -> tuple[dict[str, Any], ...]:
    response = (
        store.client.table("xau_outcome_ledger")
        .select(
            "episode_key,episode_type,strategy_id,zone_id,observed_at,status,"
            "first_touch_at,confirmed_at,outcome_at,outcome_class,mfe_points,"
            "mae_points,metadata,updated_at"
        )
        .eq("strategy_id", STRATEGY_ID)
        .order("observed_at", desc=False)
        .limit(MAX_LEDGER_ROWS)
        .execute()
    )
    return tuple(dict(row) for row in (response.data or []))


def _existing_by_key(rows: Sequence[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(row.get("episode_key") or ""): dict(row) for row in rows}


def _enrollment_metadata(
    path: dict[str, Any],
    *,
    enrolled_at: datetime,
    last_price: float,
    atlas_observed_at: datetime | None,
) -> dict[str, Any]:
    source = dict(path.get("source_zone") or {})
    target = dict(path.get("primary_opposing_zone") or {})
    return {
        "contract": CONTRACT,
        "policy_effect": "SHADOW_ONLY",
        "execution_influence": False,
        "execution_authority": False,
        "promotion_authority": False,
        "no_backfill_rule": "EVENTS_BEFORE_ENROLLED_AT_NEVER_COUNT",
        "enrolled_at": ensure_utc(enrolled_at).isoformat(),
        "atlas_observed_at": None
        if atlas_observed_at is None
        else ensure_utc(atlas_observed_at).isoformat(),
        "path_fingerprint": _path_fingerprint(path),
        "reaction_direction": str(path.get("reaction_direction") or ""),
        "source_zone": source,
        "target_zone": target,
        "internal_targets": list(path.get("internal_targets") or []),
        "inside_at_enrollment": _price_inside(last_price, source),
        "enrollment_price": float(last_price),
        "expiry_at": (
            ensure_utc(enrolled_at) + timedelta(hours=PATH_EXPIRY_HOURS)
        ).isoformat(),
    }


def _evaluate_episode(
    rows: Sequence[Bar],
    *,
    metadata: dict[str, Any],
    now: datetime,
) -> dict[str, Any]:
    source = dict(metadata.get("source_zone") or {})
    target = dict(metadata.get("target_zone") or {})
    direction = str(metadata.get("reaction_direction") or "").upper()
    enrolled_at = _dt(metadata.get("enrolled_at"))
    if enrolled_at is None or direction not in {"LONG", "SHORT"}:
        raise ValueError("V187_EPISODE_METADATA_INVALID")
    if not source or not target:
        raise ValueError("V187_PATH_GEOMETRY_MISSING")

    expiry_at = _dt(metadata.get("expiry_at")) or (
        enrolled_at + timedelta(hours=PATH_EXPIRY_HOURS)
    )
    baseline_inside = bool(metadata.get("inside_at_enrollment"))

    source_entry_at: datetime | None = None
    deep_mitigation_at: datetime | None = None
    distal_sweep_at: datetime | None = None
    reclaim_at: datetime | None = None
    confirmed_at: datetime | None = None
    invalidated_at: datetime | None = None
    target_at: datetime | None = None
    waypoint_hits: dict[str, str] = {}

    engaged = baseline_inside
    min_low: float | None = None
    max_high: float | None = None

    ordered = tuple(rows)
    for index, row in enumerate(ordered):
        ts = ensure_utc(row.timestamp)
        if ts < enrolled_at:
            continue
        if ts > min(ensure_utc(now), expiry_at):
            break

        if min_low is None:
            min_low = float(row.low)
            max_high = float(row.high)
        else:
            min_low = min(min_low, float(row.low))
            max_high = max(max_high or float(row.high), float(row.high))

        if not engaged and _inside(row, source):
            engaged = True
            source_entry_at = ts

        if engaged and deep_mitigation_at is None and _deep_mitigation(
            row, source, direction
        ):
            deep_mitigation_at = ts

        if engaged and distal_sweep_at is None and _distal_sweep_reclaimed(
            row, source, direction
        ):
            distal_sweep_at = ts

        if engaged and _invalidated(row, source, direction):
            invalidated_at = ts
            break

        if engaged and reclaim_at is None and _proximal_reclaimed(
            row, source, direction
        ):
            reclaim_at = ts

        if (
            reclaim_at is not None
            and confirmed_at is None
            and ts >= reclaim_at
            and _reaction_confirmed(
                ordered,
                index=index,
                source=source,
                direction=direction,
            )
        ):
            confirmed_at = ts

        # Destination progress only counts after reclaim. This prevents a wick
        # elsewhere in the path from being mis-labelled as a successful reaction.
        if reclaim_at is not None and ts >= reclaim_at:
            for waypoint in list(metadata.get("internal_targets") or []):
                price = _finite(waypoint.get("price"))
                if price is None:
                    continue
                key = f"{waypoint.get('source','LEVEL')}@{price:.4f}"
                if key not in waypoint_hits and _waypoint_hit(
                    row,
                    direction=direction,
                    price=price,
                ):
                    waypoint_hits[key] = ts.isoformat()

            if _target_reached(row, target, direction):
                target_at = ts
                break

    source_high = float(source["high"])
    source_low = float(source["low"])
    if direction == "LONG":
        mfe_points = 0.0 if max_high is None else max(0.0, max_high - source_high)
        mae_points = 0.0 if min_low is None else max(0.0, source_high - min_low)
    else:
        mfe_points = 0.0 if min_low is None else max(0.0, source_low - min_low)
        mae_points = 0.0 if max_high is None else max(0.0, max_high - source_low)

    sweep_reclaimed = bool(
        distal_sweep_at is not None
        and reclaim_at is not None
        and reclaim_at >= distal_sweep_at
    )

    if target_at is not None:
        status = "TARGET_REACHED"
        outcome_class = "PATH_SUCCESS"
        outcome_at = target_at
    elif invalidated_at is not None:
        status = "SOURCE_INVALIDATED"
        outcome_class = "PATH_FAILURE_SOURCE_INVALIDATED"
        outcome_at = invalidated_at
    elif ensure_utc(now) >= expiry_at:
        status = "EXPIRED_NO_TARGET"
        outcome_class = "PATH_EXPIRED"
        outcome_at = expiry_at
    elif confirmed_at is not None:
        status = "REACTION_CONFIRMED"
        outcome_class = None
        outcome_at = None
    elif reclaim_at is not None:
        status = "SOURCE_RECLAIMED"
        outcome_class = None
        outcome_at = None
    elif distal_sweep_at is not None:
        status = "DISTAL_SWEEP_RECLAIMED_INSIDE"
        outcome_class = None
        outcome_at = None
    elif deep_mitigation_at is not None:
        status = "DEEP_MITIGATION"
        outcome_class = None
        outcome_at = None
    elif engaged:
        status = (
            "INSIDE_AT_ENROLLMENT"
            if baseline_inside and source_entry_at is None
            else "SOURCE_ENTERED_POST_ENROLLMENT"
        )
        outcome_class = None
        outcome_at = None
    else:
        status = "ENROLLED_WATCH"
        outcome_class = None
        outcome_at = None

    return {
        "status": status,
        "outcome_class": outcome_class,
        "outcome_at": outcome_at,
        "source_entry_at": source_entry_at,
        "deep_mitigation_at": deep_mitigation_at,
        "distal_sweep_at": distal_sweep_at,
        "reclaim_at": reclaim_at,
        "confirmed_at": confirmed_at,
        "target_at": target_at,
        "waypoint_hits": waypoint_hits,
        "sweep_reclaimed": sweep_reclaimed,
        "mfe_points": mfe_points,
        "mae_points": mae_points,
        "last_evaluated_at": ensure_utc(now),
    }


def _ledger_row(
    path: dict[str, Any],
    *,
    enrolled_at: datetime,
    atlas_observed_at: datetime | None,
    last_price: float,
    rows: Sequence[Bar],
    now: datetime,
    existing: dict[str, Any] | None,
) -> dict[str, Any]:
    previous = dict(existing or {})
    previous_metadata = dict(previous.get("metadata") or {})
    metadata = (
        previous_metadata
        if previous_metadata
        else _enrollment_metadata(
            path,
            enrolled_at=enrolled_at,
            last_price=last_price,
            atlas_observed_at=atlas_observed_at,
        )
    )
    evaluation = _evaluate_episode(rows, metadata=metadata, now=now)
    metadata = {
        **metadata,
        "source_entry_at": None
        if evaluation["source_entry_at"] is None
        else evaluation["source_entry_at"].isoformat(),
        "deep_mitigation_at": None
        if evaluation["deep_mitigation_at"] is None
        else evaluation["deep_mitigation_at"].isoformat(),
        "distal_sweep_at": None
        if evaluation["distal_sweep_at"] is None
        else evaluation["distal_sweep_at"].isoformat(),
        "reclaim_at": None
        if evaluation["reclaim_at"] is None
        else evaluation["reclaim_at"].isoformat(),
        "confirmed_at": None
        if evaluation["confirmed_at"] is None
        else evaluation["confirmed_at"].isoformat(),
        "target_at": None
        if evaluation["target_at"] is None
        else evaluation["target_at"].isoformat(),
        "waypoint_hits": dict(evaluation["waypoint_hits"]),
        "sweep_reclaimed": bool(evaluation["sweep_reclaimed"]),
        "last_evaluated_at": evaluation["last_evaluated_at"].isoformat(),
    }
    source = dict(metadata["source_zone"])
    return {
        "episode_key": _episode_key(path),
        "episode_type": EPISODE_TYPE,
        "strategy_id": STRATEGY_ID,
        "signal_id": None,
        "zone_id": source.get("zone_id"),
        "map_at": None,
        "observed_at": metadata["enrolled_at"],
        "direction": metadata["reaction_direction"],
        "grade": None,
        "score": None,
        "status": evaluation["status"],
        "execution_authority": "NONE",
        "entry_price": None,
        "stop_price": None,
        "tp1_price": None,
        "tp2_price": None,
        "first_touch_at": None
        if evaluation["source_entry_at"] is None
        else evaluation["source_entry_at"].isoformat(),
        "map_first_touch_at": None,
        "confirmed_at": None
        if evaluation["confirmed_at"] is None
        else evaluation["confirmed_at"].isoformat(),
        "execution_ready_at": None,
        "order_accepted_at": None,
        "protection_verified_at": None,
        "outcome_at": None
        if evaluation["outcome_at"] is None
        else evaluation["outcome_at"].isoformat(),
        "outcome_class": evaluation["outcome_class"],
        "mfe_points": float(evaluation["mfe_points"]),
        "mae_points": float(evaluation["mae_points"]),
        "mfe_r": None,
        "mae_r": None,
        "tp1_hit": False,
        "tp2_hit": False,
        "stop_hit": False,
        "missed_execution": False,
        "metadata": metadata,
        "updated_at": ensure_utc(now).isoformat(),
    }


def _summary(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    selected = [
        row
        for row in rows
        if str(row.get("episode_type") or "") == EPISODE_TYPE
    ]
    resolved = [
        row for row in selected if str(row.get("status") or "") in TERMINAL_STATUSES
    ]
    successes = [
        row for row in resolved if str(row.get("status") or "") == "TARGET_REACHED"
    ]
    sweep_reclaim = [
        row
        for row in resolved
        if bool(dict(row.get("metadata") or {}).get("sweep_reclaimed"))
    ]
    sweep_success = [
        row
        for row in sweep_reclaim
        if str(row.get("status") or "") == "TARGET_REACHED"
    ]
    return {
        "episodes": len(selected),
        "resolved": len(resolved),
        "active": len(selected) - len(resolved),
        "target_reached": len(successes),
        "invalidated": sum(
            str(row.get("status") or "") == "SOURCE_INVALIDATED"
            for row in resolved
        ),
        "expired": sum(
            str(row.get("status") or "") == "EXPIRED_NO_TARGET"
            for row in resolved
        ),
        "resolved_success_rate": None
        if not resolved
        else len(successes) / len(resolved),
        "sweep_reclaim_resolved": len(sweep_reclaim),
        "sweep_reclaim_target_reached": len(sweep_success),
        "sweep_reclaim_success_rate": None
        if not sweep_reclaim
        else len(sweep_success) / len(sweep_reclaim),
        "promotion_authority": False,
        "decision": "COLLECTING_PROSPECTIVE_PATH_EVIDENCE",
    }


def run() -> int:
    cfg = load_project_config(None)
    policy = load_execution_policy(None)
    if str(policy.ctrader.get("environment", "")).upper() != "DEMO":
        raise SystemExit("XAU_SUPPLY_DEMAND_PATH_V187_DEMO_ONLY")
    if not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("XAU_SUPPLY_DEMAND_PATH_V187_REQUIRE_DEMO")
    if SYMBOL not in cfg.pair_map:
        raise SystemExit("XAU_SUPPLY_DEMAND_PATH_V187_SYMBOL_NOT_CONFIGURED")

    now = datetime.now(tz=UTC)
    store = SupabaseOperationalStore.from_env()
    feed = build_ctrader_research_feed(policy, (SYMBOL,))
    error: str | None = None
    row_written = 0
    raw_count = 0
    active_path: dict[str, Any] = {}
    ledger_row: dict[str, Any] | None = None

    try:
        atlas_observed_at, atlas = _latest_atlas(store)
        path_map = dict(atlas.get("path_map") or {})
        active_path = dict(path_map.get("active_path") or {})
        source = dict(active_path.get("source_zone") or {})
        target = dict(active_path.get("primary_opposing_zone") or {})
        last_price = _finite(atlas.get("last_closed_m15_price"))

        existing_rows = _existing_rows(store)
        existing_map = _existing_by_key(existing_rows)

        if active_path and source and target and last_price is not None:
            key = _episode_key(active_path)
            existing = existing_map.get(key)
            if existing is None or str(existing.get("status") or "") not in TERMINAL_STATUSES:
                feed.ensure_connected()
                raw = tuple(
                    feed.historical_bars(
                        SYMBOL,
                        "M15",
                        from_time=now - timedelta(days=LOOKBACK_DAYS),
                        to_time=now,
                        count=REQUEST_COUNT,
                    )
                )
                raw_count = len(raw)
                closed = _closed_m15(raw, as_of=now)
                enrolled_at = (
                    _dt(dict(existing or {}).get("observed_at"))
                    or now
                )
                ledger_row = _ledger_row(
                    active_path,
                    enrolled_at=enrolled_at,
                    atlas_observed_at=atlas_observed_at,
                    last_price=last_price,
                    rows=closed,
                    now=now,
                    existing=existing,
                )
                store.client.table("xau_outcome_ledger").upsert(
                    [ledger_row],
                    on_conflict="episode_key",
                ).execute()
                row_written = 1

        after = _existing_rows(store)
        summary = _summary(after)
    except Exception as exc:
        error = f"{type(exc).__name__}:{exc}"
        summary = {
            "decision": "ERROR",
            "promotion_authority": False,
        }
    finally:
        try:
            feed.close()
        except Exception:
            pass

    healthy = error is None
    store.write_heartbeat(
        WORKER_NAME,
        healthy=healthy,
        lag_seconds=0.0,
        details={
            "contract": CONTRACT,
            "environment": "DEMO",
            "policy_effect": "SHADOW_ONLY",
            "execution_influence": False,
            "execution_authority": False,
            "promotion_authority": False,
            "live_execution_enabled": False,
            "raw_m15_bars": raw_count,
            "row_written": row_written,
            "active_path": active_path,
            "current_episode": ledger_row,
            "summary": summary,
            "error": error,
        },
    )
    print(
        "CTRADER_DEMO_XAU_SUPPLY_DEMAND_PATH_V187 "
        f"healthy={int(healthy)} row_written={row_written} "
        f"decision={summary.get('decision')} execution_authority=0"
    )
    return 0 if healthy else 2


if __name__ == "__main__":
    raise SystemExit(run())

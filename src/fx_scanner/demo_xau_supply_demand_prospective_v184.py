from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from math import isfinite
import os
from typing import Any, Sequence

from .config import load_project_config
from .demo_xau_afic_path_shadow_observer import _resample_completed
from .demo_xau_supply_demand_atlas_v182 import (
    SDZone,
    TIMEFRAME_PRIORITY,
    _approach_quality,
    _dedupe_zones,
    _detect_base_departure_zones,
    _structural_h1_zones,
    _zone_lifecycle,
)
from .execution.factory import build_ctrader_research_feed
from .execution.policy import load_execution_policy
from .models import Bar, ensure_utc
from .research_xau_supply_demand_reaction_v183 import (
    PRIMARY_REACTION_ATR,
    REACTION_HORIZON_M15,
    _age_bucket,
    _liquidity_bucket,
    _liquidity_sources,
    _nesting_bucket,
    _session_bucket_wib,
    evaluate_reaction_outcome,
)
from .research_xau_zone_path_v174 import wilson_lower_bound
from .storage.supabase_operational import SupabaseOperationalStore

SYMBOL = "XAUUSD"
WORKER_NAME = "ctrader_demo_xau_supply_demand_prospective_v184"
CONTRACT = "XAU_SUPPLY_DEMAND_PROSPECTIVE_LIFECYCLE_V184"
STRATEGY_ID = "XAU_SUPPLY_DEMAND_PROSPECTIVE_V184"
ZONE_EPISODE_TYPE = "SUPPLY_DEMAND_V184_ZONE"
REACTION_EPISODE_TYPE = "SUPPLY_DEMAND_V184_REACTION"

LOOKBACK_DAYS = 45
REQUEST_COUNT = 3000
ZONE_OBSERVATION_DAYS = 10
MAX_POST_ENROLLMENT_TOUCHES = 4
MAX_LEDGER_ROWS = 5000

# Frozen after V183 historical holdout. This is the only primary replication
# candidate in V184; session/pattern/liquidity fields remain diagnostics.
PRIMARY_CANDIDATE = {
    "timeframe": "H1",
    "direction": "LONG",
    "nesting_bucket": "MULTI_HTF_NESTING",
    "approach_state": "AGGRESSIVE_APPROACH",
}
PROSPECTIVE_MIN_N = 50
PROSPECTIVE_MIN_RAW_PRECISION = 0.80
PROSPECTIVE_MIN_WILSON_LOWER = 0.70


def _safe_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _dt(value: Any) -> datetime | None:
    if value is None or value == "":
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


def _closed_m15(rows: Sequence[Bar], *, as_of: datetime) -> tuple[Bar, ...]:
    now = ensure_utc(as_of)
    return tuple(
        row
        for row in sorted(tuple(rows), key=lambda item: ensure_utc(item.timestamp))
        if ensure_utc(row.timestamp) + timedelta(minutes=15) <= now
    )


def _all_zones(
    rows: Sequence[Bar],
    *,
    as_of: datetime,
) -> tuple[SDZone, ...]:
    zones: list[SDZone] = list(_structural_h1_zones(rows, as_of=as_of))
    for timeframe, rule in (("H1", "1h"), ("H4", "4h"), ("D1", "1D")):
        frame = _resample_completed(rows, rule, as_of=as_of)
        zones.extend(_detect_base_departure_zones(frame, timeframe=timeframe))
    return _dedupe_zones(zones)


def _inside(row: Bar, zone: SDZone) -> bool:
    return float(row.high) >= float(zone.low) and float(row.low) <= float(zone.high)


def _invalidated(row: Bar, zone: SDZone) -> bool:
    if zone.direction == "LONG":
        return float(row.close) < float(zone.distal)
    return float(row.close) > float(zone.distal)


def _active_at(
    zone: SDZone,
    *,
    rows: Sequence[Bar],
    timestamp: datetime,
) -> bool:
    cutoff = ensure_utc(timestamp)
    if ensure_utc(zone.available_at) > cutoff:
        return False
    for row in rows:
        ts = ensure_utc(row.timestamp)
        if ts < ensure_utc(zone.available_at):
            continue
        if ts > cutoff:
            break
        if _invalidated(row, zone):
            return False
    return True


def _nesting_at_touch(
    zone: SDZone,
    *,
    all_zones: Sequence[SDZone],
    rows: Sequence[Bar],
    touch_at: datetime,
) -> tuple[int, tuple[str, ...]]:
    midpoint = (float(zone.low) + float(zone.high)) / 2.0
    priority = TIMEFRAME_PRIORITY.get(zone.timeframe, 0)
    parents: list[str] = []
    for parent in all_zones:
        if parent.zone_id == zone.zone_id or parent.direction != zone.direction:
            continue
        if TIMEFRAME_PRIORITY.get(parent.timeframe, 0) <= priority:
            continue
        if ensure_utc(parent.available_at) > ensure_utc(touch_at):
            continue
        overlaps = (
            float(parent.low) <= midpoint <= float(parent.high)
            or max(0.0, min(zone.high, parent.high) - max(zone.low, parent.low)) > 0.0
        )
        if not overlaps:
            continue
        if not _active_at(parent, rows=rows, timestamp=touch_at):
            continue
        parents.append(f"{parent.timeframe}:{parent.zone_id}")
    return len(parents), tuple(sorted(parents))


def _post_enrollment_touch_indices(
    rows: Sequence[Bar],
    *,
    zone: SDZone,
    enrolled_at: datetime,
) -> tuple[int, ...]:
    ordered = tuple(rows)
    enrolled = ensure_utc(enrolled_at)
    first_index = 0
    while (
        first_index < len(ordered)
        and ensure_utc(ordered[first_index].timestamp) < enrolled
    ):
        first_index += 1

    was_inside = (
        first_index > 0 and _inside(ordered[first_index - 1], zone)
    )
    touches: list[int] = []
    next_eligible = first_index
    for index in range(first_index, len(ordered)):
        row = ordered[index]
        inside = _inside(row, zone)
        if inside and not was_inside and index >= next_eligible:
            touches.append(index)
            next_eligible = index + REACTION_HORIZON_M15 + 1
            if len(touches) >= MAX_POST_ENROLLMENT_TOUCHES:
                break
        was_inside = inside
    return tuple(touches)


def _existing_rows(
    store: SupabaseOperationalStore,
) -> tuple[dict[str, Any], ...]:
    response = (
        store.client.table("xau_outcome_ledger")
        .select(
            "episode_key,episode_type,strategy_id,zone_id,observed_at,status,"
            "first_touch_at,outcome_at,outcome_class,mfe_points,mae_points,metadata"
        )
        .eq("strategy_id", STRATEGY_ID)
        .order("observed_at", desc=False)
        .limit(MAX_LEDGER_ROWS)
        .execute()
    )
    return tuple(dict(row) for row in (response.data or []))


def _existing_zone_registry(
    rows: Sequence[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for row in rows:
        if str(row.get("episode_type") or "") != ZONE_EPISODE_TYPE:
            continue
        zone_id = str(row.get("zone_id") or "")
        if zone_id:
            output[zone_id] = dict(row)
    return output


def _baseline_touch_count(zone: SDZone, rows: Sequence[Bar]) -> tuple[int, str]:
    lifecycle = _zone_lifecycle(zone, bars=rows)
    return (
        int(lifecycle.get("touch_count") or 0),
        str(lifecycle.get("freshness") or "UNKNOWN"),
    )


def _zone_registry_row(
    zone: SDZone,
    *,
    rows: Sequence[Bar],
    now: datetime,
    existing: dict[str, Any] | None,
) -> dict[str, Any]:
    previous = dict(existing or {})
    previous_metadata = dict(previous.get("metadata") or {})
    enrolled_at = (
        _dt(previous_metadata.get("enrolled_at"))
        or _dt(previous.get("observed_at"))
        or ensure_utc(now)
    )
    baseline_touch_count = previous_metadata.get("baseline_touch_count")
    baseline_freshness = previous_metadata.get("baseline_freshness")
    if baseline_touch_count is None or baseline_freshness is None:
        baseline_touch_count, baseline_freshness = _baseline_touch_count(zone, rows)

    touches = _post_enrollment_touch_indices(
        rows,
        zone=zone,
        enrolled_at=enrolled_at,
    )
    invalidated_at: datetime | None = None
    for row in rows:
        ts = ensure_utc(row.timestamp)
        if ts < enrolled_at:
            continue
        if _invalidated(row, zone):
            invalidated_at = ts
            break

    expiry_at = enrolled_at + timedelta(days=ZONE_OBSERVATION_DAYS)
    if invalidated_at is not None:
        status = (
            "INVALIDATED_AFTER_TOUCH"
            if touches
            else "INVALIDATED_PRE_TOUCH"
        )
    elif touches:
        status = "TOUCHED_POST_ENROLLMENT"
    elif ensure_utc(now) >= expiry_at:
        status = "EXPIRED_NO_TOUCH"
    else:
        status = "ACTIVE"

    metadata = {
        **previous_metadata,
        "contract": CONTRACT,
        "policy_effect": "SHADOW_ONLY",
        "execution_influence": False,
        "execution_authority": False,
        "no_backfill_rule": "ONLY_TOUCHES_AT_OR_AFTER_ENROLLED_AT_COUNT",
        "enrolled_at": enrolled_at.isoformat(),
        "available_at": ensure_utc(zone.available_at).isoformat(),
        "origin_at": ensure_utc(zone.origin_at).isoformat(),
        "departure_at": ensure_utc(zone.departure_at).isoformat(),
        "timeframe": zone.timeframe,
        "zone_class": zone.zone_class,
        "pattern": zone.pattern,
        "low": float(zone.low),
        "high": float(zone.high),
        "proximal": float(zone.proximal),
        "distal": float(zone.distal),
        "atr_points": float(zone.atr_points),
        "base_bars": int(zone.base_bars),
        "base_range_atr": float(zone.base_range_atr),
        "departure_range_atr": float(zone.departure_range_atr),
        "departure_body_fraction": float(zone.departure_body_fraction),
        "structural_bos": bool(zone.structural_bos),
        "baseline_touch_count": int(baseline_touch_count),
        "baseline_freshness": str(baseline_freshness),
        "post_enrollment_touch_count": len(touches),
        "expiry_at": expiry_at.isoformat(),
        "last_evaluated_at": ensure_utc(now).isoformat(),
    }
    return {
        "episode_key": f"V184:ZONE:{zone.zone_id}",
        "episode_type": ZONE_EPISODE_TYPE,
        "strategy_id": STRATEGY_ID,
        "signal_id": None,
        "zone_id": zone.zone_id,
        "map_at": None,
        "observed_at": enrolled_at.isoformat(),
        "direction": zone.direction,
        "grade": None,
        "score": None,
        "status": status,
        "execution_authority": "NONE",
        "entry_price": None,
        "stop_price": None,
        "tp1_price": None,
        "tp2_price": None,
        "first_touch_at": (
            None
            if not touches
            else ensure_utc(rows[touches[0]].timestamp).isoformat()
        ),
        "map_first_touch_at": None,
        "confirmed_at": None,
        "execution_ready_at": None,
        "order_accepted_at": None,
        "protection_verified_at": None,
        "outcome_at": (
            None if invalidated_at is None else invalidated_at.isoformat()
        ),
        "outcome_class": (
            None if invalidated_at is None else "ZONE_INVALIDATED"
        ),
        "mfe_points": None,
        "mae_points": None,
        "mfe_r": None,
        "mae_r": None,
        "tp1_hit": False,
        "tp2_hit": False,
        "stop_hit": False,
        "missed_execution": False,
        "metadata": metadata,
        "updated_at": ensure_utc(now).isoformat(),
    }


def _reaction_row(
    zone: SDZone,
    *,
    all_zones: Sequence[SDZone],
    rows: Sequence[Bar],
    touch_index: int,
    post_touch_ordinal: int,
    baseline_touch_count: int,
    enrolled_at: datetime,
    daily,
    daily_times,
    weekly,
    weekly_times,
    now: datetime,
) -> dict[str, Any]:
    touch_at = ensure_utc(rows[touch_index].timestamp)
    outcome = evaluate_reaction_outcome(
        rows,
        touch_index=touch_index,
        zone=zone,
    )
    prior = rows[max(0, touch_index - 12) : touch_index]
    approach = _approach_quality(prior, zone=zone)
    nesting_count, nested_in = _nesting_at_touch(
        zone,
        all_zones=all_zones,
        rows=rows,
        touch_at=touch_at,
    )
    liquidity = _liquidity_sources(
        zone=zone,
        touch_at=touch_at,
        daily=daily,
        daily_times=daily_times,
        weekly=weekly,
        weekly_times=weekly_times,
    )
    global_touch_ordinal = int(baseline_touch_count) + int(post_touch_ordinal)
    age_hours = max(
        0.0,
        (touch_at - ensure_utc(zone.available_at)).total_seconds() / 3600.0,
    )
    nesting_bucket = _nesting_bucket(nesting_count)
    approach_state = str(approach.get("state") or "INSUFFICIENT")
    candidate_match = (
        zone.timeframe == PRIMARY_CANDIDATE["timeframe"]
        and zone.direction == PRIMARY_CANDIDATE["direction"]
        and nesting_bucket == PRIMARY_CANDIDATE["nesting_bucket"]
        and approach_state == PRIMARY_CANDIDATE["approach_state"]
    )
    outcome_terminal = outcome.status != "PENDING"

    metadata = {
        "contract": CONTRACT,
        "policy_effect": "SHADOW_ONLY",
        "execution_influence": False,
        "execution_authority": False,
        "prospective": True,
        "no_backfill_rule": "TOUCH_AT_OR_AFTER_ENROLLED_AT_ONLY",
        "enrolled_at": ensure_utc(enrolled_at).isoformat(),
        "available_at": ensure_utc(zone.available_at).isoformat(),
        "timeframe": zone.timeframe,
        "zone_class": zone.zone_class,
        "pattern": zone.pattern,
        "direction": zone.direction,
        "low": float(zone.low),
        "high": float(zone.high),
        "proximal": float(zone.proximal),
        "distal": float(zone.distal),
        "atr_points": float(zone.atr_points),
        "post_enrollment_touch_ordinal": int(post_touch_ordinal),
        "global_touch_ordinal": int(global_touch_ordinal),
        "age_hours": age_hours,
        "age_bucket": _age_bucket(zone.timeframe, age_hours),
        "session_context": _session_bucket_wib(touch_at),
        "approach": approach,
        "approach_state": approach_state,
        "htf_nesting_count": int(nesting_count),
        "nesting_bucket": nesting_bucket,
        "nested_in": list(nested_in),
        "liquidity_sources": list(liquidity),
        "liquidity_bucket": _liquidity_bucket(len(liquidity)),
        "departure_range_atr": float(zone.departure_range_atr),
        "departure_body_fraction": float(zone.departure_body_fraction),
        "base_range_atr": float(zone.base_range_atr),
        "structural_bos": bool(zone.structural_bos),
        "primary_reaction_atr": PRIMARY_REACTION_ATR,
        "reaction_horizon_m15": REACTION_HORIZON_M15,
        "break_wins_same_bar_ambiguity": True,
        "candidate_contract": PRIMARY_CANDIDATE,
        "primary_candidate_match": bool(candidate_match),
        "mfe_atr": float(outcome.max_favorable_excursion_atr),
        "mae_atr": float(outcome.max_adverse_excursion_atr),
        "hit_025_before_break": bool(outcome.hit_025_before_break),
        "hit_050_before_break": bool(outcome.hit_050_before_break),
        "hit_075_before_break": bool(outcome.hit_075_before_break),
        "hit_100_before_break": bool(outcome.hit_100_before_break),
        "last_evaluated_at": ensure_utc(now).isoformat(),
    }
    return {
        "episode_key": f"V184:REACTION:{zone.zone_id}:{touch_at.isoformat()}",
        "episode_type": REACTION_EPISODE_TYPE,
        "strategy_id": STRATEGY_ID,
        "signal_id": None,
        "zone_id": zone.zone_id,
        "map_at": None,
        "observed_at": touch_at.isoformat(),
        "direction": zone.direction,
        "grade": None,
        "score": None,
        "status": outcome.status,
        "execution_authority": "NONE",
        "entry_price": None,
        "stop_price": None,
        "tp1_price": None,
        "tp2_price": None,
        "first_touch_at": touch_at.isoformat(),
        "map_first_touch_at": None,
        "confirmed_at": None,
        "execution_ready_at": None,
        "order_accepted_at": None,
        "protection_verified_at": None,
        "outcome_at": (
            None
            if not outcome_terminal or outcome.outcome_at is None
            else ensure_utc(outcome.outcome_at).isoformat()
        ),
        "outcome_class": (
            None if not outcome_terminal else outcome.status
        ),
        "mfe_points": float(outcome.max_favorable_excursion_atr)
        * float(zone.atr_points),
        "mae_points": float(outcome.max_adverse_excursion_atr)
        * float(zone.atr_points),
        "mfe_r": None,
        "mae_r": None,
        "tp1_hit": False,
        "tp2_hit": False,
        "stop_hit": False,
        "missed_execution": False,
        "metadata": metadata,
        "updated_at": ensure_utc(now).isoformat(),
    }


def _upsert(
    store: SupabaseOperationalStore,
    rows: Sequence[dict[str, Any]],
) -> int:
    if not rows:
        return 0
    store.client.table("xau_outcome_ledger").upsert(
        list(rows),
        on_conflict="episode_key",
    ).execute()
    return len(rows)


def _frame_times(frame) -> tuple[datetime, ...]:
    return tuple(ensure_utc(value.to_pydatetime()) for value in frame["time"])


def _prospective_summary(
    ledger_rows: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    reactions = [
        row
        for row in ledger_rows
        if str(row.get("episode_type") or "") == REACTION_EPISODE_TYPE
    ]
    resolved = [
        row
        for row in reactions
        if str(row.get("status") or "") in {"HOLD", "BREAK", "BREAK_TOUCH_BAR", "STALL"}
    ]

    def summarize(selected: Sequence[dict[str, Any]]) -> dict[str, Any]:
        items = list(selected)
        n = len(items)
        holds = sum(str(row.get("status") or "") == "HOLD" for row in items)
        return {
            "n": n,
            "holds": holds,
            "precision_hold": None if n == 0 else holds / n,
            "wilson_lower_95": None if n == 0 else wilson_lower_bound(holds, n),
        }

    candidate = [
        row
        for row in resolved
        if bool(dict(row.get("metadata") or {}).get("primary_candidate_match"))
    ]
    h1_long = [
        row
        for row in resolved
        if str(dict(row.get("metadata") or {}).get("timeframe")) == "H1"
        and str(row.get("direction") or "") == "LONG"
    ]
    h1_short = [
        row
        for row in resolved
        if str(dict(row.get("metadata") or {}).get("timeframe")) == "H1"
        and str(row.get("direction") or "") == "SHORT"
    ]
    candidate_summary = summarize(candidate)
    replicated = bool(
        candidate_summary["n"] >= PROSPECTIVE_MIN_N
        and candidate_summary["precision_hold"] is not None
        and candidate_summary["precision_hold"] >= PROSPECTIVE_MIN_RAW_PRECISION
        and candidate_summary["wilson_lower_95"] is not None
        and candidate_summary["wilson_lower_95"] >= PROSPECTIVE_MIN_WILSON_LOWER
    )
    return {
        "reaction_rows": len(reactions),
        "resolved_reactions": len(resolved),
        "pending_reactions": len(reactions) - len(resolved),
        "primary_candidate": {
            **candidate_summary,
            "contract": PRIMARY_CANDIDATE,
            "minimum_n": PROSPECTIVE_MIN_N,
            "minimum_raw_precision": PROSPECTIVE_MIN_RAW_PRECISION,
            "minimum_wilson_lower_95": PROSPECTIVE_MIN_WILSON_LOWER,
            "replication_gate_met": replicated,
            "promotion_authority": False,
        },
        "controls": {
            "all_h1_long": summarize(h1_long),
            "all_h1_short": summarize(h1_short),
        },
        "decision": (
            "PROSPECTIVE_REPLICATION_SIGNAL_NOT_PROMOTED"
            if replicated
            else "COLLECTING_PROSPECTIVE_EVIDENCE"
        ),
    }


def run() -> int:
    cfg = load_project_config(None)
    policy = load_execution_policy(None)
    if str(policy.ctrader.get("environment", "")).upper() != "DEMO":
        raise SystemExit("XAU_SUPPLY_DEMAND_V184_DEMO_ONLY")
    if not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("XAU_SUPPLY_DEMAND_V184_REQUIRE_DEMO")
    if SYMBOL not in cfg.pair_map:
        raise SystemExit("XAU_SUPPLY_DEMAND_V184_SYMBOL_NOT_CONFIGURED")

    now = datetime.now(tz=UTC)
    feed = build_ctrader_research_feed(policy, (SYMBOL,))
    store = SupabaseOperationalStore.from_env()
    raw_count = 0
    closed: tuple[Bar, ...] = ()
    registry_rows: list[dict[str, Any]] = []
    reaction_rows: list[dict[str, Any]] = []
    written = 0
    error: str | None = None

    try:
        existing = _existing_rows(store)
        existing_registry = _existing_zone_registry(existing)

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
        all_zones = _all_zones(closed, as_of=now)
        h1_zones = [zone for zone in all_zones if zone.timeframe == "H1"]

        daily = _resample_completed(closed, "1D", as_of=now)
        weekly = _resample_completed(closed, "W-MON", as_of=now)
        daily_times = _frame_times(daily)
        weekly_times = _frame_times(weekly)

        for zone in h1_zones:
            lifecycle = _zone_lifecycle(zone, bars=closed)
            if not bool(lifecycle.get("active")) and zone.zone_id not in existing_registry:
                continue
            registry = _zone_registry_row(
                zone,
                rows=closed,
                now=now,
                existing=existing_registry.get(zone.zone_id),
            )
            registry_rows.append(registry)
            metadata = dict(registry.get("metadata") or {})
            enrolled_at = _dt(metadata.get("enrolled_at")) or now
            baseline_touch_count = int(metadata.get("baseline_touch_count") or 0)
            touch_indices = _post_enrollment_touch_indices(
                closed,
                zone=zone,
                enrolled_at=enrolled_at,
            )
            for post_ordinal, touch_index in enumerate(touch_indices, start=1):
                reaction_rows.append(
                    _reaction_row(
                        zone,
                        all_zones=all_zones,
                        rows=closed,
                        touch_index=touch_index,
                        post_touch_ordinal=post_ordinal,
                        baseline_touch_count=baseline_touch_count,
                        enrolled_at=enrolled_at,
                        daily=daily,
                        daily_times=daily_times,
                        weekly=weekly,
                        weekly_times=weekly_times,
                        now=now,
                    )
                )

        written = _upsert(store, tuple(registry_rows + reaction_rows))
        after = _existing_rows(store)
        summary = _prospective_summary(after)
    except Exception as exc:
        error = f"{type(exc).__name__}:{exc}"
        summary = {
            "decision": "ERROR",
            "primary_candidate": {},
            "controls": {},
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
            "primary_candidate_contract": PRIMARY_CANDIDATE,
            "prospective_gate": {
                "minimum_n": PROSPECTIVE_MIN_N,
                "minimum_raw_precision": PROSPECTIVE_MIN_RAW_PRECISION,
                "minimum_wilson_lower_95": PROSPECTIVE_MIN_WILSON_LOWER,
                "automatic_promotion": False,
            },
            "raw_m15_bars": raw_count,
            "closed_m15_bars": len(closed),
            "h1_registry_rows_this_run": len(registry_rows),
            "reaction_rows_this_run": len(reaction_rows),
            "rows_upserted": written,
            "summary": summary,
            "error": error,
            "code_version": os.getenv("GITHUB_SHA", "LOCAL"),
        },
    )
    print(
        "CTRADER_DEMO_XAU_SUPPLY_DEMAND_V184 "
        f"healthy={int(healthy)} registry={len(registry_rows)} "
        f"reactions={len(reaction_rows)} rows_upserted={written} "
        f"decision={summary.get('decision')} execution_authority=0"
    )
    return 0 if healthy else 2


if __name__ == "__main__":
    raise SystemExit(run())

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from math import isfinite
from typing import Any, Sequence

from .execution.factory import build_ctrader_research_feed
from .execution.policy import load_execution_policy
from .models import Bar, ensure_utc
from .storage.supabase_operational import SupabaseOperationalStore

SYMBOL = "XAUUSD"
WORKER_NAME = "ctrader_demo_xau_v196_shadow_evidence"
CONTRACT = "XAU_V196_PROSPECTIVE_SHADOW_EVIDENCE_V197"
SOURCE_CONTRACT = "XAU_BIDIRECTIONAL_M5_PATH_V196"
STRATEGY_ID = SOURCE_CONTRACT
EPISODE_TYPE = "V196_SHADOW_POCKET"
ATLAS_WORKER = "ctrader_demo_xau_supply_demand_atlas_v182"

LOOKBACK_DAYS = 7
OUTCOME_HORIZON_HOURS = 24
REQUEST_COUNT = 3000
MAX_HEARTBEATS = 2000
VALID_POCKET_STATES = {"CANDIDATE_M5_POCKET", "REFINED_M5_POCKET"}
VALID_REVERSE_SOURCE_ROLES = {
    "H1_PRECISION_INSIDE_CURRENT_TERMINAL",
    "CURRENT_TERMINAL_OPPOSING_ZONE",
}


@dataclass(frozen=True, slots=True)
class PocketSnapshot:
    episode_key: str
    observed_at: datetime
    leg_role: str
    direction: str
    pocket_state: str
    pocket_low: float
    pocket_high: float
    pocket_origin_at: str | None
    source_role: str | None
    source_zone: dict[str, Any]
    reaction_target: float | None
    terminal_zone: dict[str, Any]
    projection_state: str


@dataclass(frozen=True, slots=True)
class PocketOutcome:
    status: str
    first_touch_at: datetime | None
    reaction_hit_at: datetime | None
    terminal_hit_at: datetime | None
    invalidated_at: datetime | None
    outcome_at: datetime | None
    outcome_class: str | None
    mfe_points: float
    mae_points: float
    reaction_hit: bool
    terminal_hit: bool


def _finite(value: Any) -> float | None:
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


def _closed_m5(rows: Sequence[Bar], *, as_of: datetime) -> tuple[Bar, ...]:
    now = ensure_utc(as_of)
    return tuple(
        row
        for row in sorted(tuple(rows), key=lambda item: ensure_utc(item.timestamp))
        if ensure_utc(row.timestamp) + timedelta(minutes=5) <= now
    )


def _episode_key(
    *,
    leg_role: str,
    direction: str,
    source_zone_id: str,
    pocket_low: float,
    pocket_high: float,
    pocket_origin_at: str | None,
) -> str:
    raw = "|".join(
        (
            SOURCE_CONTRACT,
            leg_role,
            direction,
            source_zone_id,
            f"{pocket_low:.8f}",
            f"{pocket_high:.8f}",
            str(pocket_origin_at or ""),
        )
    )
    return "V197:POCKET:" + hashlib.sha256(raw.encode()).hexdigest()[:32]


def _snapshots_from_heartbeats(
    heartbeats: Sequence[dict[str, Any]],
) -> tuple[PocketSnapshot, ...]:
    first_seen: dict[str, PocketSnapshot] = {}
    for heartbeat in sorted(
        tuple(heartbeats),
        key=lambda row: _dt(row.get("observed_at")) or datetime.max.replace(tzinfo=UTC),
    ):
        observed_at = _dt(heartbeat.get("observed_at"))
        if observed_at is None:
            continue
        details = dict(heartbeat.get("details") or {})
        evaluation = dict(details.get("evaluation") or {})
        projection = dict(evaluation.get("m5_path_projection") or {})
        if str(projection.get("contract") or "") != SOURCE_CONTRACT:
            continue

        # V196 reverse-leg semantics were corrected to anchor the next leg to
        # the current terminal opposing zone. Ignore earlier heartbeats so the
        # evidence ledger does not enroll a pocket produced by the superseded
        # global-nearest-source implementation.
        next_leg = dict(projection.get("next_leg") or {})
        next_source_role = str(next_leg.get("source_role") or "")
        if next_leg and next_source_role not in VALID_REVERSE_SOURCE_ROLES:
            continue

        for leg_role in ("current_leg", "next_leg"):
            leg = dict(projection.get(leg_role) or {})
            direction = str(leg.get("direction") or "").upper()
            pocket_state = str(leg.get("pocket_state") or "").upper()
            pocket = dict(leg.get("m5_pocket") or {})
            micro = dict(leg.get("micro_refinement") or {})
            micro_state = str(micro.get("state") or "").upper()
            if direction not in {"LONG", "SHORT"}:
                continue
            if pocket_state not in VALID_POCKET_STATES or not pocket:
                continue
            if "INVALIDATED" in micro_state:
                continue

            low = _finite(pocket.get("low"))
            high = _finite(pocket.get("high"))
            if low is None or high is None or high < low:
                continue
            source_zone = dict(leg.get("source_zone") or {})
            source_zone_id = str(source_zone.get("zone_id") or "NO_ZONE_ID")
            target = _finite(dict(leg.get("reaction_target") or {}).get("price"))
            terminal = dict(leg.get("terminal_target_zone") or {})
            origin_at = str(pocket.get("origin_at") or "") or None
            key = _episode_key(
                leg_role=leg_role,
                direction=direction,
                source_zone_id=source_zone_id,
                pocket_low=low,
                pocket_high=high,
                pocket_origin_at=origin_at,
            )
            if key in first_seen:
                continue
            first_seen[key] = PocketSnapshot(
                episode_key=key,
                observed_at=observed_at,
                leg_role=leg_role,
                direction=direction,
                pocket_state=pocket_state,
                pocket_low=low,
                pocket_high=high,
                pocket_origin_at=origin_at,
                source_role=str(leg.get("source_role") or "") or None,
                source_zone=source_zone,
                reaction_target=target,
                terminal_zone=terminal,
                projection_state=str(projection.get("state") or ""),
            )
    return tuple(first_seen.values())


def evaluate_pocket_outcome(
    bars: Sequence[Bar],
    *,
    snapshot: PocketSnapshot,
    as_of: datetime,
    horizon_hours: int = OUTCOME_HORIZON_HOURS,
) -> PocketOutcome:
    end_at = min(
        ensure_utc(as_of),
        ensure_utc(snapshot.observed_at) + timedelta(hours=int(horizon_hours)),
    )
    selected = tuple(
        row
        for row in sorted(tuple(bars), key=lambda item: ensure_utc(item.timestamp))
        if snapshot.observed_at <= ensure_utc(row.timestamp) <= end_at
    )
    entry = (snapshot.pocket_low + snapshot.pocket_high) / 2.0
    source_distal = _finite(snapshot.source_zone.get("distal"))
    terminal_low = _finite(snapshot.terminal_zone.get("low"))
    terminal_high = _finite(snapshot.terminal_zone.get("high"))

    first_touch_at: datetime | None = None
    reaction_hit_at: datetime | None = None
    terminal_hit_at: datetime | None = None
    invalidated_at: datetime | None = None
    mfe = 0.0
    mae = 0.0

    for row in selected:
        ts = ensure_utc(row.timestamp)
        if snapshot.direction == "LONG":
            invalidated = (
                source_distal is not None and float(row.close) < float(source_distal)
            )
        else:
            invalidated = (
                source_distal is not None and float(row.close) > float(source_distal)
            )

        if first_touch_at is None:
            if invalidated:
                invalidated_at = ts
                break
            touched = (
                float(row.high) >= snapshot.pocket_low
                and float(row.low) <= snapshot.pocket_high
            )
            if not touched:
                continue
            first_touch_at = ts

        if snapshot.direction == "LONG":
            mfe = max(mfe, max(0.0, float(row.high) - entry))
            mae = max(mae, max(0.0, entry - float(row.low)))
            hit_reaction = (
                snapshot.reaction_target is not None
                and float(row.high) >= float(snapshot.reaction_target)
            )
            hit_terminal = terminal_low is not None and float(row.high) >= terminal_low
        else:
            mfe = max(mfe, max(0.0, entry - float(row.low)))
            mae = max(mae, max(0.0, float(row.high) - entry))
            hit_reaction = (
                snapshot.reaction_target is not None
                and float(row.low) <= float(snapshot.reaction_target)
            )
            hit_terminal = terminal_high is not None and float(row.low) <= terminal_high

        # Conservative ambiguity: source invalidation takes precedence when it
        # occurs on the same closed M5 bar as a target.
        if invalidated:
            invalidated_at = ts
            break
        if hit_reaction and reaction_hit_at is None:
            reaction_hit_at = ts
        if hit_terminal:
            terminal_hit_at = ts
            break

    expired = ensure_utc(as_of) >= snapshot.observed_at + timedelta(hours=int(horizon_hours))
    if terminal_hit_at is not None:
        status = "PROVEN_TERMINAL_ZONE"
        outcome_at = terminal_hit_at
        outcome_class = "PROVEN_TERMINAL_ZONE_NO_ORDER_REQUIRED"
    elif reaction_hit_at is not None:
        status = "PROVEN_REACTION_TARGET"
        outcome_at = reaction_hit_at
        outcome_class = "PROVEN_REACTION_TARGET_NO_ORDER_REQUIRED"
    elif invalidated_at is not None:
        status = (
            "INVALIDATED_PRE_TOUCH"
            if first_touch_at is None
            else "INVALIDATED_AFTER_TOUCH"
        )
        outcome_at = invalidated_at
        outcome_class = status
    elif expired:
        status = "EXPIRED_NO_TOUCH" if first_touch_at is None else "EXPIRED_AFTER_TOUCH"
        outcome_at = snapshot.observed_at + timedelta(hours=int(horizon_hours))
        outcome_class = status
    else:
        status = "ENROLLED_WAIT_TOUCH" if first_touch_at is None else "TOUCHED_PENDING"
        outcome_at = None
        outcome_class = None

    return PocketOutcome(
        status=status,
        first_touch_at=first_touch_at,
        reaction_hit_at=reaction_hit_at,
        terminal_hit_at=terminal_hit_at,
        invalidated_at=invalidated_at,
        outcome_at=outcome_at,
        outcome_class=outcome_class,
        mfe_points=mfe,
        mae_points=mae,
        reaction_hit=reaction_hit_at is not None,
        terminal_hit=terminal_hit_at is not None,
    )


def _heartbeats(
    store: SupabaseOperationalStore,
    *,
    cutoff: datetime,
) -> tuple[dict[str, Any], ...]:
    response = (
        store.client.table("runtime_heartbeats")
        .select("observed_at,details")
        .eq("worker_name", ATLAS_WORKER)
        .gte("observed_at", cutoff.isoformat())
        .order("observed_at", desc=False)
        .limit(MAX_HEARTBEATS)
        .execute()
    )
    return tuple(dict(row) for row in (response.data or []))


def _ledger_row(
    *,
    snapshot: PocketSnapshot,
    outcome: PocketOutcome,
    now: datetime,
) -> dict[str, Any]:
    terminal_low = _finite(snapshot.terminal_zone.get("low"))
    terminal_high = _finite(snapshot.terminal_zone.get("high"))
    terminal_boundary = (
        terminal_low if snapshot.direction == "LONG" else terminal_high
    )
    source_zone_id = str(snapshot.source_zone.get("zone_id") or "") or None
    entry = (snapshot.pocket_low + snapshot.pocket_high) / 2.0
    return {
        "episode_key": snapshot.episode_key,
        "episode_type": EPISODE_TYPE,
        "strategy_id": STRATEGY_ID,
        "signal_id": None,
        "zone_id": source_zone_id,
        "map_at": None,
        "observed_at": snapshot.observed_at.isoformat(),
        "direction": snapshot.direction,
        "grade": None,
        "score": None,
        "status": outcome.status,
        "execution_authority": "NONE",
        "entry_price": entry,
        "stop_price": None,
        "tp1_price": snapshot.reaction_target,
        "tp2_price": terminal_boundary,
        "first_touch_at": (
            None if outcome.first_touch_at is None else outcome.first_touch_at.isoformat()
        ),
        "map_first_touch_at": None,
        "confirmed_at": (
            snapshot.observed_at.isoformat()
            if snapshot.pocket_state == "REFINED_M5_POCKET"
            else None
        ),
        "execution_ready_at": None,
        "order_accepted_at": None,
        "protection_verified_at": None,
        "outcome_at": None if outcome.outcome_at is None else outcome.outcome_at.isoformat(),
        "outcome_class": outcome.outcome_class,
        "mfe_points": outcome.mfe_points,
        "mae_points": outcome.mae_points,
        "mfe_r": None,
        "mae_r": None,
        "tp1_hit": outcome.reaction_hit,
        "tp2_hit": outcome.terminal_hit,
        "stop_hit": False,
        "missed_execution": False,
        "metadata": {
            "contract": CONTRACT,
            "source_contract": SOURCE_CONTRACT,
            "evidence_class": "PROSPECTIVE_SHADOW_GEOMETRY",
            "prospective": True,
            "order_required": False,
            "counts_without_order": True,
            "not_trade_pnl_evidence": True,
            "no_backfill_rule": "ONLY_BARS_AT_OR_AFTER_FIRST_VALID_V196_HEARTBEAT_COUNT",
            "outcome_horizon_hours": OUTCOME_HORIZON_HOURS,
            "leg_role": snapshot.leg_role,
            "projection_state_at_enrollment": snapshot.projection_state,
            "pocket_state_at_enrollment": snapshot.pocket_state,
            "pocket_low": snapshot.pocket_low,
            "pocket_high": snapshot.pocket_high,
            "pocket_origin_at": snapshot.pocket_origin_at,
            "source_role": snapshot.source_role,
            "source_zone": snapshot.source_zone,
            "reaction_target": snapshot.reaction_target,
            "terminal_zone": snapshot.terminal_zone,
            "reaction_hit_at": (
                None
                if outcome.reaction_hit_at is None
                else outcome.reaction_hit_at.isoformat()
            ),
            "terminal_hit_at": (
                None
                if outcome.terminal_hit_at is None
                else outcome.terminal_hit_at.isoformat()
            ),
            "invalidated_at": (
                None
                if outcome.invalidated_at is None
                else outcome.invalidated_at.isoformat()
            ),
            "last_evaluated_at": ensure_utc(now).isoformat(),
        },
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


def run() -> int:
    policy = load_execution_policy(None)
    if str(policy.ctrader.get("environment", "")).upper() != "DEMO":
        raise SystemExit("XAU_V197_EVIDENCE_DEMO_ONLY")
    if not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("XAU_V197_EVIDENCE_REQUIRE_DEMO")

    store = SupabaseOperationalStore.from_env()
    feed = build_ctrader_research_feed(policy, (SYMBOL,))
    now = datetime.now(tz=UTC)
    cutoff = now - timedelta(days=LOOKBACK_DAYS)
    bars: tuple[Bar, ...] = ()
    snapshots: tuple[PocketSnapshot, ...] = ()
    rows: tuple[dict[str, Any], ...] = ()
    written = 0
    error: str | None = None

    try:
        heartbeats = _heartbeats(store, cutoff=cutoff)
        snapshots = _snapshots_from_heartbeats(heartbeats)

        feed.ensure_connected()
        raw = tuple(
            feed.historical_bars(
                SYMBOL,
                "M5",
                from_time=cutoff,
                to_time=now,
                count=REQUEST_COUNT,
            )
        )
        bars = _closed_m5(raw, as_of=now)
        rows = tuple(
            _ledger_row(
                snapshot=snapshot,
                outcome=evaluate_pocket_outcome(bars, snapshot=snapshot, as_of=now),
                now=now,
            )
            for snapshot in snapshots
        )
        written = _upsert(store, rows)
    except Exception as exc:
        error = f"{type(exc).__name__}:{exc}"
    finally:
        try:
            feed.close()
        except Exception:
            pass

    proven_reaction = sum(
        str(row.get("status") or "") == "PROVEN_REACTION_TARGET" for row in rows
    )
    proven_terminal = sum(
        str(row.get("status") or "") == "PROVEN_TERMINAL_ZONE" for row in rows
    )
    failed = sum(
        str(row.get("status") or "").startswith("INVALIDATED") for row in rows
    )
    pending = sum(
        str(row.get("status") or "") in {"ENROLLED_WAIT_TOUCH", "TOUCHED_PENDING"}
        for row in rows
    )
    healthy = error is None
    store.write_heartbeat(
        WORKER_NAME,
        healthy=healthy,
        lag_seconds=0.0,
        details={
            "contract": CONTRACT,
            "source_contract": SOURCE_CONTRACT,
            "environment": "DEMO",
            "execution_influence": False,
            "execution_authority": False,
            "promotion_authority": False,
            "order_required_for_evidence": False,
            "evidence_is_not_trade_pnl": True,
            "lookback_days": LOOKBACK_DAYS,
            "outcome_horizon_hours": OUTCOME_HORIZON_HOURS,
            "closed_m5_bars": len(bars),
            "enrolled_pockets": len(rows),
            "proven_reaction_target": proven_reaction,
            "proven_terminal_zone": proven_terminal,
            "invalidated": failed,
            "pending": pending,
            "rows_upserted": written,
            "error": error,
            "code_version": os.getenv("GITHUB_SHA", "LOCAL"),
        },
    )
    print(
        "CTRADER_DEMO_XAU_V196_SHADOW_EVIDENCE "
        f"healthy={healthy} enrolled={len(rows)} proven_reaction={proven_reaction} "
        f"proven_terminal={proven_terminal} invalidated={failed} pending={pending} "
        f"rows_upserted={written} error={error or 'NONE'}"
    )
    return 0 if healthy else 2


if __name__ == "__main__":
    raise SystemExit(run())

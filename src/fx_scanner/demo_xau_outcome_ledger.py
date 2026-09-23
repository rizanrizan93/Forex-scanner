from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from math import isfinite
from typing import Any, Iterable, Sequence

from .execution.factory import build_ctrader_research_feed
from .execution.policy import load_execution_policy
from .models import Bar, ensure_utc
from .storage.supabase_operational import SupabaseOperationalStore

SYMBOL = "XAUUSD"
WORKER_NAME = "ctrader_demo_xau_outcome_ledger"
CONTRACT = "XAU_PROSPECTIVE_OUTCOME_LEDGER_V1"
LOOKBACK_DAYS = 7
REQUEST_COUNT = 800
OUTCOME_HORIZON_HOURS = 8
MAX_SIGNAL_ROWS = 1000
MAX_EVENT_ROWS = 5000

AUTHORIZED_GEOMETRY_CODES = {
    "XAU_AFIC_PATH_EXECUTION_V1",
    "XAU_M15_EMA_SMC_RECLAIM_V1",
    "XAU_V24_CHAMPION_DEMO_V1",
}


@dataclass(frozen=True, slots=True)
class PathOutcome:
    activation_at: datetime | None
    mfe_points: float
    mae_points: float
    mfe_r: float | None
    mae_r: float | None
    tp1_hit: bool
    tp2_hit: bool
    stop_hit: bool
    outcome_at: datetime | None
    outcome_class: str | None


def _dt(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def _finite(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _entry_price(row: dict[str, Any]) -> float | None:
    low = _finite(row.get("entry_low"))
    high = _finite(row.get("entry_high"))
    if low is not None and high is not None:
        return (low + high) / 2.0
    return low if low is not None else high


def _targets(row: dict[str, Any]) -> tuple[float | None, float | None]:
    tp1 = _finite(row.get("tp1"))
    tp2 = _finite(row.get("tp2"))
    tp3 = _finite(row.get("tp3"))
    first = tp1 if tp1 is not None else tp2
    terminal = tp3 if tp3 is not None else (tp2 if tp2 is not None else tp1)
    return first, terminal


def _grade_for_signal(row: dict[str, Any], prepared: dict[str, dict[str, Any]]) -> str | None:
    signal_id = str(row.get("id") or "")
    payload = dict(prepared.get(signal_id) or {})
    plan = dict(payload.get("prepared_plan") or {})
    grade = str(plan.get("selector_grade") or "").upper().strip()
    if grade in {"A", "B", "C"}:
        return grade
    setup = str(row.get("setup_type") or "").upper()
    score = _finite(row.get("final_score"))
    if setup.startswith("AFIC_") and score is not None:
        if score >= 95:
            return "A"
        if score >= 90:
            return "B"
        if score >= 85:
            return "C"
    return None


def _stable_zone_id(zone: dict[str, Any]) -> str | None:
    direction = str(zone.get("direction") or "").upper().strip()
    origin_at = str(zone.get("origin_at") or "").strip()
    available_at = str(zone.get("available_at") or "").strip()
    low = _finite(zone.get("low"))
    high = _finite(zone.get("high"))
    bos_level = _finite(zone.get("bos_level"))
    if (
        direction not in {"LONG", "SHORT"}
        or not origin_at
        or not available_at
        or low is None
        or high is None
        or bos_level is None
    ):
        return None
    raw = "|".join(
        (
            direction,
            origin_at,
            available_at,
            f"{low:.8f}",
            f"{high:.8f}",
            f"{bos_level:.8f}",
        )
    )
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def _closed_m15(rows: Sequence[Bar], *, as_of: datetime) -> tuple[Bar, ...]:
    now = ensure_utc(as_of)
    return tuple(
        row
        for row in sorted(rows, key=lambda value: ensure_utc(value.timestamp))
        if ensure_utc(row.timestamp) + timedelta(minutes=15) <= now
    )


def evaluate_signal_path(
    bars: Sequence[Bar],
    *,
    observed_at: datetime,
    direction: str,
    entry: float,
    stop: float | None,
    tp1: float | None,
    tp2: float | None,
    horizon_hours: int = OUTCOME_HORIZON_HOURS,
    require_entry_touch: bool = False,
) -> PathOutcome:
    normalized = str(direction).upper()
    if normalized not in {"LONG", "SHORT"}:
        raise ValueError("direction must be LONG or SHORT")
    end_at = ensure_utc(observed_at) + timedelta(hours=int(horizon_hours))
    selected = tuple(
        row
        for row in sorted(bars, key=lambda value: ensure_utc(value.timestamp))
        if ensure_utc(observed_at) <= ensure_utc(row.timestamp) <= end_at
    )
    risk = None if stop is None else abs(float(stop) - float(entry))
    if risk is not None and (not isfinite(risk) or risk <= 0):
        risk = None

    mfe = 0.0
    mae = 0.0
    first_hit = False
    terminal_hit = False
    stop_hit = False
    outcome_at: datetime | None = None
    outcome_class: str | None = None
    activation_at: datetime | None = None if require_entry_touch else ensure_utc(observed_at)

    for row in selected:
        if require_entry_touch and activation_at is None:
            if not (float(row.low) <= float(entry) <= float(row.high)):
                continue
            activation_at = ensure_utc(row.timestamp)

        if normalized == "LONG":
            favorable = max(0.0, float(row.high) - entry)
            adverse = max(0.0, entry - float(row.low))
            row_stop = stop is not None and float(row.low) <= float(stop)
            row_tp1 = tp1 is not None and float(row.high) >= float(tp1)
            row_tp2 = tp2 is not None and float(row.high) >= float(tp2)
        else:
            favorable = max(0.0, entry - float(row.low))
            adverse = max(0.0, float(row.high) - entry)
            row_stop = stop is not None and float(row.high) >= float(stop)
            row_tp1 = tp1 is not None and float(row.low) <= float(tp1)
            row_tp2 = tp2 is not None and float(row.low) <= float(tp2)

        mfe = max(mfe, favorable)
        mae = max(mae, adverse)

        # Conservative same-bar ambiguity: stop takes precedence.
        if row_stop:
            stop_hit = True
            outcome_at = ensure_utc(row.timestamp)
            outcome_class = "STOPPED_AFTER_TP1" if first_hit else "STOPPED"
            break
        if row_tp1:
            first_hit = True
        if row_tp2:
            terminal_hit = True
            first_hit = True
            outcome_at = ensure_utc(row.timestamp)
            outcome_class = "TP2_HIT"
            break

    if outcome_class is None and first_hit:
        outcome_class = "TP1_HIT"

    return PathOutcome(
        activation_at=activation_at,
        mfe_points=mfe,
        mae_points=mae,
        mfe_r=None if risk is None else mfe / risk,
        mae_r=None if risk is None else mae / risk,
        tp1_hit=first_hit,
        tp2_hit=terminal_hit,
        stop_hit=stop_hit,
        outcome_at=outcome_at,
        outcome_class=outcome_class,
    )


def _signals(store: SupabaseOperationalStore, *, cutoff: datetime) -> tuple[dict[str, Any], ...]:
    response = (
        store.client.table("signals")
        .select(
            "id,observed_at,symbol,direction,setup_type,state,final_score,"
            "entry_low,entry_high,sl,tp1,tp2,tp3,active_guards,expires_at"
        )
        .eq("symbol", SYMBOL)
        .gte("observed_at", cutoff.isoformat())
        .order("observed_at", desc=True)
        .limit(MAX_SIGNAL_ROWS)
        .execute()
    )
    return tuple(dict(row) for row in (response.data or []))


def _events(store: SupabaseOperationalStore, *, cutoff: datetime) -> tuple[dict[str, Any], ...]:
    response = (
        store.client.table("broker_order_events")
        .select("observed_at,event_type,signal_key,accepted,code,payload")
        .gte("observed_at", cutoff.isoformat())
        .order("observed_at", desc=False)
        .limit(MAX_EVENT_ROWS)
        .execute()
    )
    return tuple(dict(row) for row in (response.data or []))


def _prepared_by_signal(events: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in events:
        if str(row.get("event_type") or "") != "DEMO_XAU_AFIC_PREPARED_PLAN":
            continue
        key = str(row.get("signal_key") or "")
        if key:
            out[key] = dict(row.get("payload") or {})
    return out


def _events_by_signal(events: Iterable[dict[str, Any]]) -> dict[str, tuple[dict[str, Any], ...]]:
    indexed: dict[str, list[dict[str, Any]]] = {}
    for row in events:
        key = str(row.get("signal_key") or "")
        if key:
            indexed.setdefault(key, []).append(dict(row))
    return {key: tuple(value) for key, value in indexed.items()}


def _event_time(rows: Sequence[dict[str, Any]], event_type: str) -> datetime | None:
    values = [
        _dt(row.get("observed_at"))
        for row in rows
        if str(row.get("event_type") or "") == event_type
    ]
    parsed = [value for value in values if value is not None]
    return min(parsed) if parsed else None


def _geometry_authority(rows: Sequence[dict[str, Any]]) -> str:
    for row in rows:
        if str(row.get("event_type") or "") != "DEMO_SIGNAL_GEOMETRY":
            continue
        code = str(row.get("code") or "")
        if code in AUTHORIZED_GEOMETRY_CODES:
            return code
    return "NONE"


def _actual_close(rows: Sequence[dict[str, Any]]) -> tuple[datetime | None, str | None, dict[str, Any]]:
    closes = [
        row
        for row in rows
        if str(row.get("event_type") or "") == "DEMO_TRADE_CLOSED"
        and bool(row.get("accepted"))
    ]
    if not closes:
        return None, None, {}
    row = closes[-1]
    payload = dict(row.get("payload") or {})
    at = _dt(payload.get("exit_time")) or _dt(row.get("observed_at"))
    outcome = str(payload.get("exit_type") or row.get("code") or "DEMO_TRADE_CLOSED")
    return at, outcome, payload


def _signal_status(
    row: dict[str, Any],
    *,
    path: PathOutcome,
    order_at: datetime | None,
    protection_at: datetime | None,
    actual_outcome: str | None,
    authority: str,
    now: datetime,
) -> tuple[str, bool, str | None]:
    state = str(row.get("state") or "").upper()
    expired = (_dt(row.get("expires_at")) or datetime.max.replace(tzinfo=UTC)) < now
    missed = order_at is None and path.tp1_hit

    if actual_outcome:
        return "CLOSED", False, actual_outcome
    if order_at is not None and protection_at is not None:
        return "PROTECTED", False, path.outcome_class
    if order_at is not None:
        return "ORDER_ACCEPTED", False, path.outcome_class

    # Market-path evidence is chronological and must survive a later state/map
    # invalidation. This is essential for prospective missed-execution analysis:
    # a signal can hit TP before a later H4 remap marks its stored row INVALIDATED.
    if path.tp2_hit:
        return "MISSED_EXECUTION" if missed else "TP2_HIT", missed, (
            "FORECAST_TARGET_HIT_NO_EXECUTION" if missed else path.outcome_class
        )
    if path.stop_hit:
        return "STOPPED", False, path.outcome_class
    if path.tp1_hit:
        return "MISSED_EXECUTION" if missed else "TP1_HIT", missed, (
            "FORECAST_TP1_HIT_NO_EXECUTION" if missed else path.outcome_class
        )
    if state == "INVALIDATED":
        return "INVALIDATED", False, path.outcome_class
    if state == "EXECUTION_READY" and authority != "NONE":
        return "EXECUTION_READY", False, None
    if expired:
        return "EXPIRED", False, None
    return state or "PENDING", False, None


def _signal_rows(
    signals: Sequence[dict[str, Any]],
    *,
    events: Sequence[dict[str, Any]],
    bars: Sequence[Bar],
    now: datetime,
) -> tuple[dict[str, Any], ...]:
    prepared = _prepared_by_signal(events)
    event_index = _events_by_signal(events)
    rows: list[dict[str, Any]] = []

    for signal in signals:
        signal_id = str(signal.get("id") or "")
        observed_at = _dt(signal.get("observed_at"))
        direction = str(signal.get("direction") or "").upper()
        entry = _entry_price(signal)
        if not signal_id or observed_at is None or direction not in {"LONG", "SHORT"} or entry is None:
            continue
        stop = _finite(signal.get("sl"))
        first_target, terminal_target = _targets(signal)
        setup_type = str(signal.get("setup_type") or "").upper()
        entry_activation_required = setup_type == "AFIC_PATH_FORECAST"
        path = evaluate_signal_path(
            bars,
            observed_at=observed_at,
            direction=direction,
            entry=entry,
            stop=stop,
            tp1=first_target,
            tp2=terminal_target,
            require_entry_touch=entry_activation_required,
        )
        signal_events = event_index.get(signal_id, ())
        order_at = _event_time(signal_events, "ORDER_ACCEPTED")
        protection_at = _event_time(signal_events, "POSITION_PROTECTION_VERIFIED")
        actual_at, actual_outcome, actual_payload = _actual_close(signal_events)
        authority = _geometry_authority(signal_events)
        status, missed, outcome_class = _signal_status(
            signal,
            path=path,
            order_at=order_at,
            protection_at=protection_at,
            actual_outcome=actual_outcome,
            authority=authority,
            now=now,
        )
        execution_ready_at = observed_at if str(signal.get("state") or "").upper() == "EXECUTION_READY" else None
        metadata = {
            "contract": CONTRACT,
            "raw_signal_state": signal.get("state"),
            "active_guards": list(signal.get("active_guards") or []),
            "expires_at": signal.get("expires_at"),
            "geometry_authority": authority,
            "entry_activation_required": entry_activation_required,
            "entry_activated_at": None
            if path.activation_at is None
            else path.activation_at.isoformat(),
            "path_outcome_is_market_geometry_not_realized_pnl": order_at is not None,
            "actual_close": {
                "net_pnl_estimate": actual_payload.get("net_pnl_estimate"),
                "exit_price": actual_payload.get("exit_price"),
                "position_id": actual_payload.get("position_id"),
            }
            if actual_payload
            else None,
            "outcome_horizon_hours": OUTCOME_HORIZON_HOURS,
        }
        rows.append(
            {
                "episode_key": f"SIGNAL:{signal_id}",
                "episode_type": "SIGNAL",
                "strategy_id": str(signal.get("setup_type") or "UNKNOWN"),
                "signal_id": signal_id,
                "zone_id": None,
                "map_at": None,
                "observed_at": observed_at.isoformat(),
                "direction": direction,
                "grade": _grade_for_signal(signal, prepared),
                "score": _finite(signal.get("final_score")),
                "status": status,
                "execution_authority": authority,
                "entry_price": entry,
                "stop_price": stop,
                "tp1_price": first_target,
                "tp2_price": terminal_target,
                "first_touch_at": None
                if path.activation_at is None
                else path.activation_at.isoformat(),
                "map_first_touch_at": None,
                "confirmed_at": None,
                "execution_ready_at": None if execution_ready_at is None else execution_ready_at.isoformat(),
                "order_accepted_at": None if order_at is None else order_at.isoformat(),
                "protection_verified_at": None if protection_at is None else protection_at.isoformat(),
                "outcome_at": None
                if (actual_at or path.outcome_at) is None
                else (actual_at or path.outcome_at).isoformat(),
                "outcome_class": outcome_class,
                "mfe_points": path.mfe_points,
                "mae_points": path.mae_points,
                "mfe_r": path.mfe_r,
                "mae_r": path.mae_r,
                "tp1_hit": path.tp1_hit,
                "tp2_hit": path.tp2_hit,
                "stop_hit": path.stop_hit,
                "missed_execution": missed,
                "metadata": metadata,
                "updated_at": now.isoformat(),
            }
        )
    return tuple(rows)


def _latest_afic_shadow(store: SupabaseOperationalStore) -> dict[str, Any] | None:
    response = (
        store.client.table("runtime_heartbeats")
        .select("observed_at,details")
        .eq("worker_name", "ctrader_demo_xau_afic_path_shadow_observer")
        .limit(1)
        .execute()
    )
    rows = list(response.data or [])
    return None if not rows else dict(rows[0])


def _zone_rows(store: SupabaseOperationalStore, *, now: datetime) -> tuple[dict[str, Any], ...]:
    heartbeat = _latest_afic_shadow(store)
    if heartbeat is None:
        return ()
    details = dict(heartbeat.get("details") or {})
    evaluation = dict(details.get("evaluation") or {})
    map_at = _dt(evaluation.get("map_at"))
    if map_at is None:
        return ()
    diagnostics = dict(evaluation.get("zone_diagnostics") or {})
    candidates: list[tuple[str, dict[str, Any]]] = []
    zone = dict(evaluation.get("zone") or {})
    if zone:
        candidates.append(("PRIMARY_AFIC_ZONE", zone))
    for watch in list(diagnostics.get("alternative_reversal_watch_zones") or []):
        candidates.append(("PRIOR_ORIGIN_REVISIT", dict(watch)))

    rows: list[dict[str, Any]] = []
    for episode_type, item in candidates:
        zone_id = str(item.get("zone_id") or "") or _stable_zone_id(item)
        if not zone_id:
            continue
        direction = str(item.get("direction") or evaluation.get("continuation_direction") or "").upper()
        if direction not in {"LONG", "SHORT"}:
            continue
        first_touch = _dt(item.get("first_touch_at") or evaluation.get("first_touch_at"))
        map_touch = _dt(item.get("map_first_touch_at") or evaluation.get("map_first_touch_at"))
        invalidated = _dt(item.get("invalidated_at") or evaluation.get("invalidated_at"))
        confirmed = _dt(evaluation.get("confirm_at")) if episode_type == "PRIMARY_AFIC_ZONE" else None
        status = str(item.get("status") or evaluation.get("state") or "WATCH")
        if invalidated is not None:
            status = "INVALIDATED"
        elif map_touch is not None:
            status = "ZONE_TOUCHED"
        rows.append(
            {
                "episode_key": f"AFIC_ZONE:{zone_id}:{map_at.isoformat()}",
                "episode_type": episode_type,
                "strategy_id": "XAU_AFIC_PATH_SHADOW_V1",
                "signal_id": None,
                "zone_id": zone_id,
                "map_at": map_at.isoformat(),
                "observed_at": str(heartbeat.get("observed_at") or now.isoformat()),
                "direction": direction,
                "grade": None,
                "score": None,
                "status": status,
                "execution_authority": "NONE",
                "entry_price": None,
                "stop_price": None,
                "tp1_price": None,
                "tp2_price": None,
                "first_touch_at": None if first_touch is None else first_touch.isoformat(),
                "map_first_touch_at": None if map_touch is None else map_touch.isoformat(),
                "confirmed_at": None if confirmed is None else confirmed.isoformat(),
                "execution_ready_at": None,
                "order_accepted_at": None,
                "protection_verified_at": None,
                "outcome_at": None if invalidated is None else invalidated.isoformat(),
                "outcome_class": "INVALIDATED" if invalidated is not None else None,
                "mfe_points": None,
                "mae_points": None,
                "mfe_r": None,
                "mae_r": None,
                "tp1_hit": False,
                "tp2_hit": False,
                "stop_hit": False,
                "missed_execution": False,
                "metadata": {
                    "contract": CONTRACT,
                    "touch_lifecycle": item.get("touch_lifecycle"),
                    "zone_lifecycle": item.get("zone_lifecycle"),
                    "invalidated_before_map": bool(item.get("invalidated_before_map", False)),
                    "role": item.get("role"),
                    "zone_low": _finite(item.get("low")),
                    "zone_high": _finite(item.get("high")),
                    "source_state": evaluation.get("state"),
                    "auto_execution_authority": bool(item.get("auto_execution_authority", False)),
                },
                "updated_at": now.isoformat(),
            }
        )
    return tuple(rows)


def _upsert_rows(store: SupabaseOperationalStore, rows: Sequence[dict[str, Any]]) -> int:
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
        raise SystemExit("XAU_OUTCOME_LEDGER_DEMO_ONLY")
    if not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("XAU_OUTCOME_LEDGER_REQUIRE_DEMO")

    store = SupabaseOperationalStore.from_env()
    feed = build_ctrader_research_feed(policy, (SYMBOL,))
    now = datetime.now(tz=UTC)
    cutoff = now - timedelta(days=LOOKBACK_DAYS)
    bars: tuple[Bar, ...] = ()
    signal_rows: tuple[dict[str, Any], ...] = ()
    zone_rows: tuple[dict[str, Any], ...] = ()
    written = 0
    error: str | None = None
    try:
        feed.ensure_connected()
        raw = tuple(
            feed.historical_bars(
                SYMBOL,
                "M15",
                from_time=cutoff,
                to_time=now,
                count=REQUEST_COUNT,
            )
        )
        bars = _closed_m15(raw, as_of=now)
        signals = _signals(store, cutoff=cutoff)
        events = _events(store, cutoff=cutoff)
        signal_rows = _signal_rows(signals, events=events, bars=bars, now=now)
        zone_rows = _zone_rows(store, now=now)
        written = _upsert_rows(store, signal_rows + zone_rows)
    except Exception as exc:
        error = f"{type(exc).__name__}:{exc}"
    finally:
        try:
            feed.close()
        except Exception:
            pass

    missed = sum(bool(row.get("missed_execution")) for row in signal_rows)
    closed = sum(str(row.get("status") or "") == "CLOSED" for row in signal_rows)
    healthy = error is None
    store.write_heartbeat(
        WORKER_NAME,
        healthy=healthy,
        lag_seconds=0.0,
        details={
            "contract": CONTRACT,
            "environment": "DEMO",
            "execution_influence": False,
            "live_execution_enabled": False,
            "outcome_horizon_hours": OUTCOME_HORIZON_HOURS,
            "lookback_days": LOOKBACK_DAYS,
            "bars": len(bars),
            "signal_episodes": len(signal_rows),
            "zone_episodes": len(zone_rows),
            "rows_upserted": written,
            "missed_execution_rows": missed,
            "closed_broker_rows": closed,
            "error": error,
            "code_version": os.getenv("GITHUB_SHA", "LOCAL"),
        },
    )
    print(
        "CTRADER_DEMO_XAU_OUTCOME_LEDGER "
        f"healthy={healthy} bars={len(bars)} signal_episodes={len(signal_rows)} "
        f"zone_episodes={len(zone_rows)} rows_upserted={written} "
        f"missed_execution={missed} closed={closed} error={error or 'NONE'}"
    )
    return 0 if healthy else 2


if __name__ == "__main__":
    raise SystemExit(run())

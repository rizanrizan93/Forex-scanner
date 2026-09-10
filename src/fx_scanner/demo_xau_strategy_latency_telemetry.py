from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite
from statistics import median
from typing import Any

from .storage.supabase_operational import SupabaseOperationalStore

UTC = timezone.utc
STRATEGY_ID = "IMPULSE_RETEST_V2"
EVENT_TYPE = "DEMO_XAU_STRATEGY_LATENCY_V1"
HEARTBEAT_NAME = "ctrader_demo_xau_strategy_latency"
MAX_ROWS = 500


def _dt(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def _seconds(start: datetime | None, end: datetime | None) -> float | None:
    if start is None or end is None or end < start:
        return None
    value = (end - start).total_seconds()
    return value if isfinite(value) else None


def _signals(store: SupabaseOperationalStore) -> tuple[dict[str, Any], ...]:
    response = (
        store.client.table("signals")
        .select("id,run_id,observed_at,symbol,direction,state,final_score,setup_type")
        .eq("symbol", "XAUUSD")
        .order("observed_at", desc=True)
        .limit(MAX_ROWS)
        .execute()
    )
    return tuple(dict(row) for row in (response.data or []))


def _events(store: SupabaseOperationalStore) -> tuple[dict[str, Any], ...]:
    response = (
        store.client.table("broker_order_events")
        .select("observed_at,signal_key,event_type,accepted,payload")
        .eq("backend", "CTRADER")
        .order("observed_at", desc=True)
        .limit(MAX_ROWS * 4)
        .execute()
    )
    return tuple(dict(row) for row in (response.data or []))


def _existing(store: SupabaseOperationalStore) -> set[str]:
    response = (
        store.client.table("broker_order_events")
        .select("signal_key")
        .eq("backend", "CTRADER")
        .eq("event_type", EVENT_TYPE)
        .order("observed_at", desc=True)
        .limit(MAX_ROWS)
        .execute()
    )
    return {
        str(row.get("signal_key") or "")
        for row in (response.data or [])
        if row.get("signal_key")
    }


def _index_events(rows: tuple[dict[str, Any], ...]) -> dict[str, dict[str, datetime]]:
    wanted = {
        "DEMO_SIGNAL_GEOMETRY": "geometry_at",
        "DEMO_SIGNAL_FEATURE_SNAPSHOT_V2": "feature_snapshot_at",
        "ORDER_ACCEPTED": "order_accepted_at",
        "POSITION_PROTECTION_VERIFIED": "protection_verified_at",
    }
    indexed: dict[str, dict[str, datetime]] = {}
    for row in rows:
        signal_key = str(row.get("signal_key") or "")
        event_type = str(row.get("event_type") or "").upper()
        field = wanted.get(event_type)
        if not signal_key or field is None:
            continue
        if event_type in {"ORDER_ACCEPTED", "POSITION_PROTECTION_VERIFIED"} and not bool(row.get("accepted")):
            continue
        observed = _dt(row.get("observed_at"))
        if observed is None:
            continue
        item = indexed.setdefault(signal_key, {})
        previous = item.get(field)
        if previous is None or observed < previous:
            item[field] = observed
    return indexed


def build_latency_payload(signal: dict[str, Any], event_times: dict[str, datetime]) -> dict[str, Any]:
    signal_at = _dt(signal.get("observed_at"))
    geometry_at = event_times.get("geometry_at")
    feature_at = event_times.get("feature_snapshot_at")
    order_at = event_times.get("order_accepted_at")
    protection_at = event_times.get("protection_verified_at")
    return {
        "strategy_id": STRATEGY_ID,
        "strategy_authority": "SOLE_DEMO_EXECUTION_STRATEGY",
        "symbol": "XAUUSD",
        "signal_id": str(signal.get("id") or ""),
        "run_id": signal.get("run_id"),
        "direction": signal.get("direction"),
        "state": signal.get("state"),
        "setup_type_storage_compatibility": signal.get("setup_type"),
        "final_score": signal.get("final_score"),
        "signal_observed_at": None if signal_at is None else signal_at.isoformat(),
        "geometry_at": None if geometry_at is None else geometry_at.isoformat(),
        "feature_snapshot_at": None if feature_at is None else feature_at.isoformat(),
        "order_accepted_at": None if order_at is None else order_at.isoformat(),
        "protection_verified_at": None if protection_at is None else protection_at.isoformat(),
        "signal_to_geometry_seconds": _seconds(signal_at, geometry_at),
        "signal_to_feature_seconds": _seconds(signal_at, feature_at),
        "signal_to_order_seconds": _seconds(signal_at, order_at),
        "order_to_protection_seconds": _seconds(order_at, protection_at),
        "m5_close_to_detection_seconds": None,
        "m5_close_latency_status": "NOT_INFERRED_WITHOUT_EXACT_BAR_IDENTITY",
        "policy_effect": "OBSERVATION_ONLY",
        "execution_influence": False,
    }


def _percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(ordered) - 1)
    weight = pos - lo
    return ordered[lo] * (1.0 - weight) + ordered[hi] * weight


def run() -> int:
    store = SupabaseOperationalStore.from_env()
    signals = _signals(store)
    event_index = _index_events(_events(store))
    existing = _existing(store)
    emitted = 0
    order_latencies: list[float] = []
    protection_latencies: list[float] = []

    for signal in reversed(signals):
        signal_id = str(signal.get("id") or "")
        if not signal_id:
            continue
        payload = build_latency_payload(signal, event_index.get(signal_id, {}))
        order_latency = payload.get("signal_to_order_seconds")
        protection_latency = payload.get("order_to_protection_seconds")
        if isinstance(order_latency, (int, float)) and isfinite(float(order_latency)):
            order_latencies.append(float(order_latency))
        if isinstance(protection_latency, (int, float)) and isfinite(float(protection_latency)):
            protection_latencies.append(float(protection_latency))
        if signal_id in existing:
            continue
        store.record_order_event(
            backend="CTRADER",
            account_id="OBSERVABILITY",
            signal_key=signal_id,
            event_type=EVENT_TYPE,
            broker_order_id=f"XAU_LATENCY:{signal_id}",
            accepted=True,
            code=STRATEGY_ID,
            message="XAUUSD active strategy identity and latency telemetry",
            payload=payload,
        )
        emitted += 1

    details = {
        "strategy_id": STRATEGY_ID,
        "strategy_authority": "SOLE_DEMO_EXECUTION_STRATEGY",
        "policy_effect": "OBSERVATION_ONLY",
        "execution_influence": False,
        "signals_considered": len(signals),
        "telemetry_rows_emitted": emitted,
        "matched_order_latencies": len(order_latencies),
        "signal_to_order_median_seconds": None if not order_latencies else median(order_latencies),
        "signal_to_order_p90_seconds": _percentile(order_latencies, 0.90),
        "signal_to_order_max_seconds": None if not order_latencies else max(order_latencies),
        "matched_protection_latencies": len(protection_latencies),
        "order_to_protection_median_seconds": None if not protection_latencies else median(protection_latencies),
        "m5_close_latency_status": "NOT_INFERRED_WITHOUT_EXACT_BAR_IDENTITY",
        "cadence_decision": "KEEP_60S_DISCOVERY_UNTIL_FORWARD_LATENCY_EVIDENCE",
    }
    store.write_heartbeat(
        HEARTBEAT_NAME,
        healthy=True,
        lag_seconds=0.0,
        details=details,
    )
    print(
        "CTRADER_DEMO_XAU_STRATEGY_LATENCY "
        f"strategy={STRATEGY_ID} signals={len(signals)} emitted={emitted} "
        f"matched_orders={len(order_latencies)} "
        f"median_s={'NONE' if not order_latencies else f'{median(order_latencies):.3f}'} "
        f"p90_s={'NONE' if not order_latencies else f'{_percentile(order_latencies, 0.90):.3f}'} "
        "policy=OBSERVATION_ONLY execution_influence=0"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())

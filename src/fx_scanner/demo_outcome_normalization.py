from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite
from typing import Any, Iterable

from .storage.supabase_operational import SupabaseOperationalStore

UTC = timezone.utc
ADAPTIVE_EVENT = "DEMO_ADAPTIVE_PROFIT_LOCK_ADVANCED"
NORMALIZABLE_STOP_OUTCOMES = {"SL_HIT", "PROTECTION_CLOSE_BREAKEVEN", "BREAKEVEN"}


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


def _adaptive_outcome(net_pnl: float) -> str:
    if abs(net_pnl) <= 0.01:
        return "ADAPTIVE_PROFIT_LOCK_BREAKEVEN"
    return "ADAPTIVE_PROFIT_LOCK_PROFIT" if net_pnl > 0 else "ADAPTIVE_PROFIT_LOCK_LOSS"


def _adaptive_events(store: SupabaseOperationalStore, *, limit: int = 1000) -> tuple[dict[str, Any], ...]:
    response = (
        store.client.table("broker_order_events")
        .select("observed_at,signal_key,accepted,payload")
        .eq("backend", "CTRADER")
        .eq("event_type", ADAPTIVE_EVENT)
        .eq("accepted", True)
        .order("observed_at", desc=True)
        .limit(int(limit))
        .execute()
    )
    return tuple(dict(row) for row in (response.data or []))


def _index_acknowledged(rows: Iterable[dict[str, Any]]) -> dict[tuple[str, str], tuple[datetime, ...]]:
    indexed: dict[tuple[str, str], list[datetime]] = {}
    for row in rows:
        payload = row.get("payload")
        if not isinstance(payload, dict):
            continue
        if str(payload.get("execution") or "").upper() != "ACKNOWLEDGED":
            continue
        signal_key = str(row.get("signal_key") or "").strip()
        position_id = str(payload.get("position_id") or "").strip()
        observed_at = _dt(row.get("observed_at"))
        if not signal_key or not position_id or observed_at is None:
            continue
        indexed.setdefault((signal_key, position_id), []).append(observed_at)
    return {key: tuple(sorted(values)) for key, values in indexed.items()}


def normalize_adaptive_profit_lock_outcomes(
    store: SupabaseOperationalStore,
    rows: Iterable[dict[str, Any]],
    *,
    adaptive_rows: Iterable[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], ...]:
    """Return calibration-only copies with historical adaptive-stop attribution repaired.

    Broker evidence is immutable. This function never updates/deletes source rows. It
    overlays only an exact acknowledged adaptive stop advance for the same signal UUID
    and broker position ID, observed no later than the close. Structural/manual/partial
    exits and non-stop native TP outcomes are never rewritten.
    """
    source_rows = tuple(dict(row) for row in rows)
    events = _adaptive_events(store) if adaptive_rows is None else tuple(dict(row) for row in adaptive_rows)
    acknowledged = _index_acknowledged(events)
    normalized: list[dict[str, Any]] = []

    for source in source_rows:
        item = dict(source)
        payload = dict(item.get("payload")) if isinstance(item.get("payload"), dict) else {}
        original = str(payload.get("exit_type") or item.get("code") or "").upper().strip()
        signal_key = str(item.get("signal_key") or payload.get("signal_id") or "").strip()
        position_id = str(payload.get("position_id") or "").strip()
        close_at = _dt(item.get("observed_at")) or _dt(payload.get("exit_time"))
        management = str(payload.get("trade_management_exit") or "").upper().strip()
        partial = bool(payload.get("partial_close", False))
        net_pnl = _finite(payload.get("net_pnl_estimate"))

        eligible = (
            original in NORMALIZABLE_STOP_OUTCOMES
            and management not in {"STRUCTURAL_PROFIT_PROTECT", "ADAPTIVE_PROFIT_LOCK"}
            and not original.startswith("MANUAL_CLOSE_")
            and not partial
            and bool(signal_key)
            and bool(position_id)
            and close_at is not None
            and net_pnl is not None
        )
        matched = False
        if eligible:
            matched = any(
                event_at <= close_at
                for event_at in acknowledged.get((signal_key, position_id), ())
            )

        if matched:
            outcome = _adaptive_outcome(float(net_pnl))
            payload["historical_exit_type_original"] = original
            payload["exit_type"] = outcome
            payload["trade_management_exit"] = "ADAPTIVE_PROFIT_LOCK"
            payload["exit_attribution"] = ADAPTIVE_EVENT
            payload["outcome_normalized_for_calibration"] = True
            payload["outcome_normalization_contract"] = "ACKNOWLEDGED_ADAPTIVE_LOCK_SAME_SIGNAL_POSITION_PRE_CLOSE_V1"
            item["code"] = outcome

        item["payload"] = payload
        normalized.append(item)

    return tuple(normalized)

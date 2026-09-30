from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from math import isfinite
from typing import Any, Iterable, Sequence

from .execution.policy import load_execution_policy
from .storage.supabase_operational import SupabaseOperationalStore

SYMBOL = "XAUUSD"
WORKER_NAME = "ctrader_demo_xau_prepared_plan_lifecycle"
CONTRACT = "XAU_PREPARED_PLAN_LIFECYCLE_V1"
PREPARED_EVENT_TYPE = "DEMO_XAU_RIZAN_PREPARED_PLAN"
PREPARED_CODE = "XAU_RIZAN_PATH_PREPARED_V1"
FORECAST_EVENT_TYPE = "DEMO_XAU_RIZAN_FORECAST_STATE"
FORECAST_CODE = "XAU_RIZAN_PATH_STATE_V1"
LEGACY_PREPARED_EVENT_TYPE = "DEMO_XAU_AFIC_PREPARED_PLAN"
LEGACY_PREPARED_CODE = "XAU_AFIC_PATH_PREPARED_V1"
LEGACY_FORECAST_EVENT_TYPE = "DEMO_XAU_AFIC_FORECAST_STATE"
LEGACY_FORECAST_CODE = "XAU_AFIC_PATH_STATE_V1"
V280_STAGE_BLOCK_EVENT_TYPE = "DEMO_XAU_RIZAN_STAGE_BLOCK"
# Reconstruct only the recent active/recently-resolved window. Lifecycle rows are
# durable in xau_prepared_plan_lifecycle, so rescanning 30 days every maintenance
# cycle only increases PostgREST egress. Seven days is far beyond the V229 plan
# TTL / normal XAU outcome horizon while retaining late broker reconciliation.
LOOKBACK_DAYS = 7
MAX_EVENT_ROWS_PER_TYPE = 2000
MAX_PREPARED_ROWS_PER_TYPE = 500
MAX_SIGNAL_ROWS = 1500
MAX_OUTCOME_ROWS = 1500
EVENT_CUTOFF_PAD_MINUTES = 15

TRACKED_EVENT_TYPES = (
    PREPARED_EVENT_TYPE,
    LEGACY_PREPARED_EVENT_TYPE,
    FORECAST_EVENT_TYPE,
    LEGACY_FORECAST_EVENT_TYPE,
    "DEMO_SIGNAL_GEOMETRY",
    "ORDER_ACCEPTED",
    "POSITION_PROTECTION_VERIFIED",
    "DEMO_TRADE_CLOSED",
    V280_STAGE_BLOCK_EVENT_TYPE,
)

_CANCEL_GUARD_REASON = {
    # Legacy persisted guards are still accepted for historical continuity.
    "AFIC_MAP_SUPERSEDED": "H4_REMAP",
    "AFIC_MAP_NO_LONGER_CURRENT": "H4_REMAP",
    "RIZAN_MAP_SUPERSEDED": "H4_REMAP",
    "RIZAN_MAP_NO_LONGER_CURRENT": "H4_REMAP",
    "V280_MISSED_ENTRY_WAIT_NEXT_SETUP": "MISSED_ENTRY_NO_CHASE",
    "V280_BREAK_RISK": "BREAK_RISK",
    "V280_SETUP_INVALID": "SETUP_INVALID",
}


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


def _event_query(
    store: SupabaseOperationalStore,
    *,
    event_type: str,
    cutoff: datetime,
    limit: int,
) -> tuple[dict[str, Any], ...]:
    rich_types = {
        PREPARED_EVENT_TYPE,
        LEGACY_PREPARED_EVENT_TYPE,
        FORECAST_EVENT_TYPE,
        LEGACY_FORECAST_EVENT_TYPE,
    }
    select_fields = (
        "observed_at,event_type,signal_key,code,payload"
        if event_type in rich_types
        else "observed_at,event_type,signal_key,accepted,code"
        if event_type == V280_STAGE_BLOCK_EVENT_TYPE
        else "observed_at,event_type,signal_key,accepted"
    )
    query = (
        store.client.table("broker_order_events")
        .select(select_fields)
        .eq("event_type", event_type)
        .gte("observed_at", cutoff.isoformat())
        .order("observed_at", desc=True)
        .limit(int(limit))
    )
    if event_type == PREPARED_EVENT_TYPE:
        query = query.eq("code", PREPARED_CODE)
    elif event_type == LEGACY_PREPARED_EVENT_TYPE:
        query = query.eq("code", LEGACY_PREPARED_CODE)
    elif event_type == FORECAST_EVENT_TYPE:
        query = query.eq("code", FORECAST_CODE)
    elif event_type == LEGACY_FORECAST_EVENT_TYPE:
        query = query.eq("code", LEGACY_FORECAST_CODE)
    elif event_type in {"ORDER_ACCEPTED", "POSITION_PROTECTION_VERIFIED"}:
        query = query.eq("accepted", True)
    response = query.execute()
    return tuple(dict(row) for row in (response.data or []))


def _effective_event_cutoff(
    *,
    requested_cutoff: datetime,
    prepared_rows: Sequence[dict[str, Any]],
) -> datetime:
    parsed = [
        _dt(row.get("observed_at"))
        for row in prepared_rows
        if _dt(row.get("observed_at")) is not None
    ]
    if not parsed:
        return requested_cutoff
    earliest = min(value for value in parsed if value is not None)
    padded = earliest - timedelta(minutes=EVENT_CUTOFF_PAD_MINUTES)
    return max(requested_cutoff, padded)


def _events_with_diagnostics(
    store: SupabaseOperationalStore, *, cutoff: datetime
) -> tuple[tuple[dict[str, Any], ...], dict[str, Any]]:
    """Fetch only event families needed by actual recent prepared plans.

    RIZAN prepared plans are authoritative. Legacy AFIC prepared/forecast rows
    are queried only as a fallback when no current RIZAN prepared row exists.
    Each non-prepared event family is fail-soft so one PostgREST statement
    timeout does not erase all lifecycle telemetry.
    """
    rows: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    counts: dict[str, int] = {}

    def fetch(
        event_type: str,
        *,
        event_cutoff: datetime,
        limit: int = MAX_EVENT_ROWS_PER_TYPE,
        critical: bool = False,
    ) -> tuple[dict[str, Any], ...]:
        try:
            found = _event_query(
                store,
                event_type=event_type,
                cutoff=event_cutoff,
                limit=limit,
            )
        except Exception as exc:
            errors.append(
                {
                    "source": f"broker_order_events:{event_type}",
                    "error": f"{type(exc).__name__}:{exc}",
                    "severity": "CRITICAL" if critical else "DEGRADED",
                }
            )
            counts[event_type] = 0
            return ()
        counts[event_type] = len(found)
        rows.extend(found)
        return found

    rizan_prepared = fetch(
        PREPARED_EVENT_TYPE,
        event_cutoff=cutoff,
        limit=MAX_PREPARED_ROWS_PER_TYPE,
        critical=True,
    )
    legacy_fallback_used = False
    legacy_prepared: tuple[dict[str, Any], ...] = ()
    if not rizan_prepared and not any(
        item.get("severity") == "CRITICAL" for item in errors
    ):
        legacy_fallback_used = True
        legacy_prepared = fetch(
            LEGACY_PREPARED_EVENT_TYPE,
            event_cutoff=cutoff,
            limit=MAX_PREPARED_ROWS_PER_TYPE,
            critical=False,
        )

    prepared_rows = tuple(rizan_prepared) + tuple(legacy_prepared)
    event_cutoff = _effective_event_cutoff(
        requested_cutoff=cutoff,
        prepared_rows=prepared_rows,
    )

    # Only query rich forecast payloads if a prepared plan exists to consume
    # them. This avoids retransmitting thousands of wide JSON rows when there
    # is no plan to reconstruct.
    if prepared_rows:
        fetch(
            FORECAST_EVENT_TYPE,
            event_cutoff=event_cutoff,
        )
        if legacy_fallback_used:
            fetch(
                LEGACY_FORECAST_EVENT_TYPE,
                event_cutoff=event_cutoff,
            )

        for event_type in (
            "DEMO_SIGNAL_GEOMETRY",
            "ORDER_ACCEPTED",
            "POSITION_PROTECTION_VERIFIED",
            "DEMO_TRADE_CLOSED",
            V280_STAGE_BLOCK_EVENT_TYPE,
        ):
            fetch(
                event_type,
                event_cutoff=event_cutoff,
            )

    floor = datetime.min.replace(tzinfo=UTC)
    rows.sort(key=lambda row: _dt(row.get("observed_at")) or floor)
    diagnostics = {
        "requested_cutoff": cutoff.isoformat(),
        "effective_event_cutoff": event_cutoff.isoformat(),
        "prepared_rows": len(prepared_rows),
        "rizan_prepared_rows": len(rizan_prepared),
        "legacy_prepared_rows": len(legacy_prepared),
        "legacy_fallback_used": legacy_fallback_used,
        "event_counts": counts,
        "query_errors": errors,
        "degraded_sources": [
            item["source"]
            for item in errors
            if item.get("severity") == "DEGRADED"
        ],
        "critical_sources": [
            item["source"]
            for item in errors
            if item.get("severity") == "CRITICAL"
        ],
    }
    return tuple(rows), diagnostics


def _events(
    store: SupabaseOperationalStore, *, cutoff: datetime
) -> tuple[dict[str, Any], ...]:
    rows, _ = _events_with_diagnostics(store, cutoff=cutoff)
    return rows

def _signals(
    store: SupabaseOperationalStore, *, cutoff: datetime
) -> tuple[dict[str, Any], ...]:
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


def _outcomes(
    store: SupabaseOperationalStore, *, cutoff: datetime
) -> tuple[dict[str, Any], ...]:
    response = (
        store.client.table("xau_outcome_ledger")
        .select(
            "signal_id,observed_at,status,first_touch_at,outcome_at,outcome_class,mfe_r,mae_r,"
            "tp1_hit,tp2_hit,stop_hit,missed_execution"
        )
        .gte("observed_at", cutoff.isoformat())
        .order("observed_at", desc=True)
        .limit(MAX_OUTCOME_ROWS)
        .execute()
    )
    return tuple(dict(row) for row in (response.data or []))


def _prepared_events(events: Iterable[dict[str, Any]]) -> tuple[dict[str, Any], ...]:
    return tuple(
        row
        for row in events
        if (
            (str(row.get("event_type") or "") == PREPARED_EVENT_TYPE
             and str(row.get("code") or "") == PREPARED_CODE)
            or
            (str(row.get("event_type") or "") == LEGACY_PREPARED_EVENT_TYPE
             and str(row.get("code") or "") == LEGACY_PREPARED_CODE)
        )
    )


def _forecast_events(events: Iterable[dict[str, Any]]) -> tuple[dict[str, Any], ...]:
    return tuple(
        row
        for row in events
        if (
            (str(row.get("event_type") or "") == FORECAST_EVENT_TYPE
             and str(row.get("code") or "") == FORECAST_CODE)
            or
            (str(row.get("event_type") or "") == LEGACY_FORECAST_EVENT_TYPE
             and str(row.get("code") or "") == LEGACY_FORECAST_CODE)
        )
    )


def _events_by_signal(
    events: Iterable[dict[str, Any]],
) -> dict[str, tuple[dict[str, Any], ...]]:
    indexed: dict[str, list[dict[str, Any]]] = {}
    for row in events:
        key = str(row.get("signal_key") or "").strip()
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


def _zone_id(forecast: dict[str, Any]) -> str | None:
    zone = dict(forecast.get("zone") or {})
    value = str(zone.get("zone_id") or "").strip()
    return value or None


def _same_map_state_transition(
    forecast_events: Sequence[dict[str, Any]],
    *,
    created_at: datetime,
    map_at: str,
) -> tuple[datetime | None, str | None]:
    for row in forecast_events:
        at = _dt(row.get("observed_at"))
        if at is None or at < created_at:
            continue
        payload = dict(row.get("payload") or {})
        forecast = dict(payload.get("forecast") or {})
        if str(forecast.get("map_at") or "") != str(map_at or ""):
            continue
        state = str(forecast.get("state") or "").upper()
        diagnostics = dict(forecast.get("zone_diagnostics") or {})

        if state == "CONFIRM_TIMEOUT_REMAP_DUE":
            return at, "CONFIRMATION_TIMEOUT"
        if "INVALIDATED_AFTER_TOUCH" in state:
            return at, "PRICE_INVALIDATION_AFTER_TOUCH"
        if state.startswith("INVALIDATED"):
            return at, "PRICE_INVALIDATION"
        if state == "NO_MAP_ZONE":
            if int(diagnostics.get("invalidated_before_map") or 0) > 0:
                return at, "INVALIDATED_BEFORE_MAP"
            if int(diagnostics.get("wrong_side_of_anchor") or 0) > 0:
                return at, "WRONG_SIDE_OF_ANCHOR"
            return at, "NO_ELIGIBLE_MAP_ZONE"
        if state == "NO_ORIGIN_ZONE":
            return at, "NO_ORIGIN_ZONE"
    return None, None


def _same_map_touch_confirm(
    forecast_events: Sequence[dict[str, Any]],
    *,
    created_at: datetime,
    map_at: str,
) -> tuple[datetime | None, datetime | None]:
    touch: datetime | None = None
    confirm: datetime | None = None
    for row in forecast_events:
        at = _dt(row.get("observed_at"))
        if at is None or at < created_at:
            continue
        payload = dict(row.get("payload") or {})
        forecast = dict(payload.get("forecast") or {})
        if str(forecast.get("map_at") or "") != str(map_at or ""):
            continue
        candidate_touch = _dt(
            forecast.get("map_first_touch_at") or forecast.get("first_touch_at")
        )
        if (
            candidate_touch is not None
            and candidate_touch >= created_at
            and (touch is None or candidate_touch < touch)
        ):
            touch = candidate_touch
        candidate_confirm = _dt(forecast.get("confirm_at"))
        if (
            candidate_confirm is not None
            and candidate_confirm >= created_at
            and (confirm is None or candidate_confirm < confirm)
        ):
            confirm = candidate_confirm
    return touch, confirm


def _next_map_transition(
    forecast_events: Sequence[dict[str, Any]],
    *,
    created_at: datetime,
    map_at: str,
) -> datetime | None:
    for row in forecast_events:
        at = _dt(row.get("observed_at"))
        if at is None or at < created_at:
            continue
        payload = dict(row.get("payload") or {})
        forecast = dict(payload.get("forecast") or {})
        next_map = str(forecast.get("map_at") or "").strip()
        if next_map and next_map != str(map_at or ""):
            return at
    return None


def _v280_stage_block_transition(
    signal_events: Sequence[dict[str, Any]],
    *,
    created_at: datetime,
) -> tuple[datetime | None, str | None]:
    for row in signal_events:
        if str(row.get("event_type") or "") != V280_STAGE_BLOCK_EVENT_TYPE:
            continue
        at = _dt(row.get("observed_at"))
        if at is None or at < created_at:
            continue
        guard = str(row.get("code") or "").strip()
        reason = _CANCEL_GUARD_REASON.get(guard)
        if reason is not None:
            return at, reason
    return None, None


def _cancel_reason(
    signal: dict[str, Any],
    *,
    created_at: datetime,
    map_at: str,
    forecast_events: Sequence[dict[str, Any]],
    now: datetime,
    signal_events: Sequence[dict[str, Any]] = (),
) -> tuple[datetime | None, str | None]:
    state = str(signal.get("state") or "").upper()
    guards = [str(value) for value in (signal.get("active_guards") or [])]

    same_map_at, same_map_reason = _same_map_state_transition(
        forecast_events,
        created_at=created_at,
        map_at=map_at,
    )
    v280_at, v280_reason = _v280_stage_block_transition(
        signal_events,
        created_at=created_at,
    )
    transition_candidates = [
        (at, reason)
        for at, reason in (
            (same_map_at, same_map_reason),
            (v280_at, v280_reason),
        )
        if at is not None and reason is not None
    ]
    if transition_candidates:
        transition_candidates.sort(key=lambda item: item[0])
        return transition_candidates[0]

    if state == "INVALIDATED":
        for guard in guards:
            reason = _CANCEL_GUARD_REASON.get(guard)
            if reason is not None:
                return (
                    _next_map_transition(
                        forecast_events,
                        created_at=created_at,
                        map_at=map_at,
                    )
                    or created_at,
                    reason,
                )
        return created_at, "SIGNAL_INVALIDATED"

    expires_at = _dt(signal.get("expires_at"))
    if expires_at is not None and expires_at < now:
        return expires_at, "ZONE_EXPIRED"

    return None, None


def lifecycle_state(
    *,
    cancelled_at: datetime | None,
    first_touch_at: datetime | None,
    confirmed_at: datetime | None,
    execution_ready_at: datetime | None,
    order_accepted_at: datetime | None,
    protection_verified_at: datetime | None,
    closed_at: datetime | None,
) -> str:
    if closed_at is not None:
        return "CLOSED"
    if protection_verified_at is not None:
        return "PROTECTED"
    if order_accepted_at is not None:
        return "ORDER_ACCEPTED"
    if cancelled_at is not None:
        return "CANCELLED"
    if execution_ready_at is not None:
        return "BROKER_ELIGIBLE"
    if confirmed_at is not None:
        return "CONFIRMED"
    if first_touch_at is not None:
        return "ZONE_ENTERED"
    return "WAITING_PRICE"


def _lifecycle_rows(
    *,
    prepared_events: Sequence[dict[str, Any]],
    forecast_events: Sequence[dict[str, Any]],
    signals: Sequence[dict[str, Any]],
    all_events: Sequence[dict[str, Any]],
    outcomes: Sequence[dict[str, Any]],
    now: datetime,
) -> tuple[dict[str, Any], ...]:
    signals_by_id = {
        str(row.get("id") or ""): dict(row)
        for row in signals
        if row.get("id")
    }
    events_by_signal = _events_by_signal(all_events)
    outcomes_by_signal = {
        str(row.get("signal_id") or ""): dict(row)
        for row in outcomes
        if row.get("signal_id")
    }

    rows: list[dict[str, Any]] = []
    for event in prepared_events:
        created_at = _dt(event.get("observed_at"))
        payload = dict(event.get("payload") or {})
        plan = dict(payload.get("prepared_plan") or {})
        forecast = dict(payload.get("forecast") or {})
        signal_id = str(payload.get("signal_id") or event.get("signal_key") or "").strip()
        plan_key = str(payload.get("dedupe_key") or "").strip() or (
            f"SIGNAL:{signal_id}" if signal_id else ""
        )
        if created_at is None or not signal_id or not plan_key or not plan:
            continue

        signal = dict(signals_by_id.get(signal_id) or {})
        signal_events = events_by_signal.get(signal_id, ())
        outcome = dict(outcomes_by_signal.get(signal_id) or {})

        map_at = str(forecast.get("map_at") or "")
        zone = dict(forecast.get("zone") or {})
        event_touch_at, event_confirm_at = _same_map_touch_confirm(
            forecast_events,
            created_at=created_at,
            map_at=map_at,
        )
        outcome_touch_at = _dt(outcome.get("first_touch_at"))
        first_touch_at = (
            outcome_touch_at
            if outcome_touch_at is not None and outcome_touch_at >= created_at
            else event_touch_at
        )
        confirmed_at = event_confirm_at or (
            _dt(forecast.get("confirm_at"))
            if _dt(forecast.get("confirm_at")) is not None
            and _dt(forecast.get("confirm_at")) >= created_at
            else None
        )
        geometry_at = _event_time(signal_events, "DEMO_SIGNAL_GEOMETRY")
        order_at = _event_time(signal_events, "ORDER_ACCEPTED")
        protection_at = _event_time(signal_events, "POSITION_PROTECTION_VERIFIED")
        closed_at = _event_time(signal_events, "DEMO_TRADE_CLOSED")
        execution_ready_at = (
            geometry_at
            if geometry_at is not None
            else created_at
            if str(signal.get("state") or "").upper() == "EXECUTION_READY"
            else None
        )

        cancelled_at, cancel_reason = _cancel_reason(
            signal,
            created_at=created_at,
            map_at=map_at,
            forecast_events=forecast_events,
            now=now,
            signal_events=signal_events,
        )
        # Broker side-effects are authoritative. Never mark an already accepted
        # order as cancelled because a later H4 map superseded the forecast.
        if order_at is not None:
            cancelled_at = None
            cancel_reason = None

        touch_while_active = bool(
            first_touch_at is not None
            and (cancelled_at is None or first_touch_at <= cancelled_at)
        )
        post_cancel_touch = bool(
            first_touch_at is not None
            and cancelled_at is not None
            and first_touch_at > cancelled_at
        )
        confirmation_while_active = bool(
            confirmed_at is not None
            and (cancelled_at is None or confirmed_at <= cancelled_at)
        )

        state = lifecycle_state(
            cancelled_at=cancelled_at,
            first_touch_at=first_touch_at if touch_while_active else None,
            confirmed_at=confirmed_at if confirmation_while_active else None,
            execution_ready_at=execution_ready_at,
            order_accepted_at=order_at,
            protection_verified_at=protection_at,
            closed_at=closed_at,
        )

        outcome_at = _dt(outcome.get("outcome_at"))
        outcome_is_causal = bool(
            first_touch_at is not None
            and outcome_at is not None
            and outcome_at >= first_touch_at
        )
        qualified_tp1 = bool(outcome.get("tp1_hit")) and outcome_is_causal
        qualified_tp2 = bool(outcome.get("tp2_hit")) and outcome_is_causal
        qualified_stop = bool(outcome.get("stop_hit")) and outcome_is_causal
        terminal_hit_after_cancel = bool(
            cancelled_at is not None
            and outcome_at is not None
            and outcome_at > cancelled_at
            and qualified_tp2
            and not qualified_stop
        )
        terminal_at = (
            closed_at
            or protection_at
            or order_at
            or cancelled_at
            or confirmed_at
            or first_touch_at
            or now
        )
        lifetime_minutes = max(
            0.0, (terminal_at - created_at).total_seconds() / 60.0
        )

        direction = str(
            signal.get("direction")
            or forecast.get("continuation_direction")
            or ""
        ).upper()
        grade = str(plan.get("selector_grade") or "").upper() or None
        if direction not in {"LONG", "SHORT"}:
            direction = None
        if grade not in {"A", "B", "C"}:
            grade = None

        rows.append(
            {
                "plan_key": plan_key,
                "signal_id": signal_id,
                "zone_id": _zone_id(forecast),
                "map_at": map_at or None,
                "created_at": created_at.isoformat(),
                "updated_at": now.isoformat(),
                "direction": direction,
                "grade": grade,
                "zone_low": _finite(zone.get("low")),
                "zone_high": _finite(zone.get("high")),
                "entry_price": _finite(plan.get("entry")),
                "stop_price": _finite(plan.get("stop")),
                "tp1_price": _finite(plan.get("tp1")),
                "tp2_price": _finite(plan.get("tp2")),
                "lifecycle_state": state,
                "cancel_reason": cancel_reason,
                "cancelled_at": None if cancelled_at is None else cancelled_at.isoformat(),
                "first_touch_at": None if first_touch_at is None else first_touch_at.isoformat(),
                "confirmed_at": None if confirmed_at is None else confirmed_at.isoformat(),
                "execution_ready_at": None
                if execution_ready_at is None
                else execution_ready_at.isoformat(),
                "order_accepted_at": None if order_at is None else order_at.isoformat(),
                "protection_verified_at": None
                if protection_at is None
                else protection_at.isoformat(),
                "outcome_at": None if outcome_at is None else outcome_at.isoformat(),
                "outcome_class": outcome.get("outcome_class"),
                "tp1_hit": qualified_tp1,
                "tp2_hit": qualified_tp2,
                "stop_hit": qualified_stop,
                "mfe_r": _finite(outcome.get("mfe_r")) if outcome_is_causal else None,
                "mae_r": _finite(outcome.get("mae_r")) if outcome_is_causal else None,
                "post_cancel_terminal_hit": terminal_hit_after_cancel,
                "metadata": {
                    "contract": CONTRACT,
                    "blueprint_kind": payload.get("kind"),
                    "raw_signal_state": signal.get("state"),
                    "active_guards": list(signal.get("active_guards") or []),
                    "source_forecast_state": forecast.get("state"),
                    "touch_lifecycle": forecast.get("touch_lifecycle"),
                    "zone_lifecycle": forecast.get("zone_lifecycle"),
                    "lifetime_minutes": lifetime_minutes,
                    "eventual_outcome_status": outcome.get("status"),
                    "missed_execution": bool(outcome.get("missed_execution")),
                    "touch_while_active": touch_while_active,
                    "post_cancel_touch": post_cancel_touch,
                    "confirmation_while_active": confirmation_while_active,
                    "outcome_is_causal_after_entry_activation": outcome_is_causal,
                    "raw_outcome_at": outcome.get("outcome_at"),
                    "raw_tp1_hit": bool(outcome.get("tp1_hit")),
                    "raw_tp2_hit": bool(outcome.get("tp2_hit")),
                    "raw_stop_hit": bool(outcome.get("stop_hit")),
                    "post_cancel_terminal_hit_is_conservative_candidate": True,
                    "live_execution_enabled": False,
                },
            }
        )
    return tuple(rows)


def _upsert_rows(
    store: SupabaseOperationalStore, rows: Sequence[dict[str, Any]]
) -> int:
    if not rows:
        return 0
    store.client.table("xau_prepared_plan_lifecycle").upsert(
        list(rows),
        on_conflict="plan_key",
    ).execute()
    return len(rows)


def _metric_flag(row: dict[str, Any], key: str) -> bool:
    metadata = dict(row.get("metadata") or {})
    if key in metadata:
        return bool(metadata.get(key))
    touch_at = _dt(row.get("first_touch_at"))
    confirm_at = _dt(row.get("confirmed_at"))
    cancelled_at = _dt(row.get("cancelled_at"))
    if key == "touch_while_active":
        return bool(touch_at is not None and (cancelled_at is None or touch_at <= cancelled_at))
    if key == "post_cancel_touch":
        return bool(touch_at is not None and cancelled_at is not None and touch_at > cancelled_at)
    if key == "confirmation_while_active":
        return bool(confirm_at is not None and (cancelled_at is None or confirm_at <= cancelled_at))
    return False


def _minutes_between(start: Any, end: Any) -> float | None:
    start_at = _dt(start)
    end_at = _dt(end)
    if start_at is None or end_at is None or end_at < start_at:
        return None
    return (end_at - start_at).total_seconds() / 60.0


def _percentile(values: Sequence[float], q: float) -> float | None:
    clean = sorted(float(value) for value in values if isfinite(float(value)))
    if not clean:
        return None
    if len(clean) == 1:
        return clean[0]
    pos = (len(clean) - 1) * max(0.0, min(1.0, float(q)))
    lo = int(pos)
    hi = min(lo + 1, len(clean) - 1)
    weight = pos - lo
    return clean[lo] * (1.0 - weight) + clean[hi] * weight


def _latency_summary(values: Sequence[float]) -> dict[str, Any]:
    clean = [float(value) for value in values if isfinite(float(value))]
    return {
        "n": len(clean),
        "median_minutes": _percentile(clean, 0.50),
        "p90_minutes": _percentile(clean, 0.90),
        "max_minutes": None if not clean else max(clean),
    }


def lifecycle_metrics(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    active_reached = sum(_metric_flag(row, "touch_while_active") for row in rows)
    active_confirmed = sum(
        _metric_flag(row, "confirmation_while_active")
        and _metric_flag(row, "touch_while_active")
        for row in rows
    )
    cancelled = sum(str(row.get("lifecycle_state") or "") == "CANCELLED" for row in rows)
    ordered = sum(row.get("order_accepted_at") is not None for row in rows)
    post_cancel_reached = sum(
        _metric_flag(row, "post_cancel_touch")
        for row in rows
        if str(row.get("lifecycle_state") or "") == "CANCELLED"
    )
    post_cancel_terminal = sum(
        bool(row.get("post_cancel_terminal_hit"))
        for row in rows
        if str(row.get("lifecycle_state") or "") == "CANCELLED"
    )
    cancellation_reason_counts: dict[str, int] = {}
    for row in rows:
        reason = str(row.get("cancel_reason") or "").strip()
        if reason:
            cancellation_reason_counts[reason] = (
                cancellation_reason_counts.get(reason, 0) + 1
            )

    created_to_touch = []
    touch_to_confirm = []
    confirm_to_ready = []
    ready_to_order = []
    order_to_protection = []
    touch_to_cancel = []
    for row in rows:
        for bucket, start_key, end_key in (
            (created_to_touch, "created_at", "first_touch_at"),
            (touch_to_confirm, "first_touch_at", "confirmed_at"),
            (confirm_to_ready, "confirmed_at", "execution_ready_at"),
            (ready_to_order, "execution_ready_at", "order_accepted_at"),
            (order_to_protection, "order_accepted_at", "protection_verified_at"),
            (touch_to_cancel, "first_touch_at", "cancelled_at"),
        ):
            value = _minutes_between(row.get(start_key), row.get(end_key))
            if value is not None:
                bucket.append(value)

    v280_reasons = {
        "MISSED_ENTRY_NO_CHASE",
        "BREAK_RISK",
        "SETUP_INVALID",
    }
    v280_prevented = sum(
        count
        for reason, count in cancellation_reason_counts.items()
        if reason in v280_reasons
    )

    return {
        "plans": total,
        "active_zone_reach_rate": None if total == 0 else active_reached / total,
        "touch_to_confirmation_rate": None
        if active_reached == 0
        else active_confirmed / active_reached,
        "cancellation_rate": None if total == 0 else cancelled / total,
        "execution_conversion_rate": None if total == 0 else ordered / total,
        "post_cancel_zone_reach_rate": None
        if cancelled == 0
        else post_cancel_reached / cancelled,
        "post_cancel_terminal_hit_rate": None
        if cancelled == 0
        else post_cancel_terminal / cancelled,
        "cancellation_reason_counts": cancellation_reason_counts,
        "v280_prevented_entry_count": v280_prevented,
        "v280_no_chase_prevented_count": cancellation_reason_counts.get(
            "MISSED_ENTRY_NO_CHASE", 0
        ),
        "v280_break_risk_block_count": cancellation_reason_counts.get(
            "BREAK_RISK", 0
        ),
        "v280_setup_invalid_block_count": cancellation_reason_counts.get(
            "SETUP_INVALID", 0
        ),
        "latency": {
            "created_to_first_touch": _latency_summary(created_to_touch),
            "first_touch_to_confirmation": _latency_summary(touch_to_confirm),
            "confirmation_to_execution_ready": _latency_summary(confirm_to_ready),
            "execution_ready_to_order_accepted": _latency_summary(ready_to_order),
            "order_accepted_to_protection": _latency_summary(order_to_protection),
            "first_touch_to_cancel_or_invalidation": _latency_summary(
                touch_to_cancel
            ),
        },
    }


def run() -> int:
    policy = load_execution_policy(None)
    if str(policy.ctrader.get("environment", "")).upper() != "DEMO":
        raise SystemExit("XAU_PREPARED_PLAN_LIFECYCLE_DEMO_ONLY")
    if not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("XAU_PREPARED_PLAN_LIFECYCLE_REQUIRE_DEMO")

    store = SupabaseOperationalStore.from_env()
    now = datetime.now(tz=UTC)
    cutoff = now - timedelta(days=LOOKBACK_DAYS)
    rows: tuple[dict[str, Any], ...] = ()
    written = 0
    errors: list[dict[str, str]] = []
    event_diagnostics: dict[str, Any] = {}

    try:
        events, event_diagnostics = _events_with_diagnostics(
            store,
            cutoff=cutoff,
        )
    except Exception as exc:
        events = ()
        errors.append(
            {
                "source": "events",
                "severity": "CRITICAL",
                "error": f"{type(exc).__name__}:{exc}",
            }
        )

    errors.extend(list(event_diagnostics.get("query_errors") or []))

    try:
        signals = _signals(store, cutoff=cutoff)
    except Exception as exc:
        signals = ()
        errors.append(
            {
                "source": "signals",
                "severity": "CRITICAL",
                "error": f"{type(exc).__name__}:{exc}",
            }
        )

    try:
        outcomes = _outcomes(store, cutoff=cutoff)
    except Exception as exc:
        outcomes = ()
        errors.append(
            {
                "source": "outcomes",
                "severity": "DEGRADED",
                "error": f"{type(exc).__name__}:{exc}",
            }
        )

    try:
        rows = _lifecycle_rows(
            prepared_events=_prepared_events(events),
            forecast_events=_forecast_events(events),
            signals=signals,
            all_events=events,
            outcomes=outcomes,
            now=now,
        )
    except Exception as exc:
        rows = ()
        errors.append(
            {
                "source": "lifecycle_reconstruction",
                "severity": "CRITICAL",
                "error": f"{type(exc).__name__}:{exc}",
            }
        )

    if rows:
        try:
            written = _upsert_rows(store, rows)
        except Exception as exc:
            errors.append(
                {
                    "source": "lifecycle_upsert",
                    "severity": "CRITICAL",
                    "error": f"{type(exc).__name__}:{exc}",
                }
            )

    metrics = lifecycle_metrics(rows)
    critical_errors = [
        item for item in errors if str(item.get("severity") or "") == "CRITICAL"
    ]
    degraded_errors = [
        item for item in errors if str(item.get("severity") or "") == "DEGRADED"
    ]
    healthy = not critical_errors
    degraded = bool(errors)
    error = " | ".join(
        f"{item.get('source')}={item.get('error')}"
        for item in errors
    ) or None
    store.write_heartbeat(
        WORKER_NAME,
        healthy=healthy,
        lag_seconds=0.0,
        details={
            "contract": CONTRACT,
            "environment": "DEMO",
            "execution_influence": False,
            "live_execution_enabled": False,
            "lookback_days": LOOKBACK_DAYS,
            "event_read_contract": "V288_PLAN_SCOPED_FAIL_SOFT_RECONSTRUCTION",
            "max_event_rows_per_type": MAX_EVENT_ROWS_PER_TYPE,
            "max_prepared_rows_per_type": MAX_PREPARED_ROWS_PER_TYPE,
            "max_signal_rows": MAX_SIGNAL_ROWS,
            "max_outcome_rows": MAX_OUTCOME_ROWS,
            "event_cutoff_pad_minutes": EVENT_CUTOFF_PAD_MINUTES,
            "event_diagnostics": event_diagnostics,
            "degraded": degraded,
            "degraded_sources": [
                str(item.get("source") or "") for item in degraded_errors
            ],
            "critical_sources": [
                str(item.get("source") or "") for item in critical_errors
            ],
            "rows_upserted": written,
            "metrics": metrics,
            "error": error,
            "code_version": os.getenv("GITHUB_SHA", "LOCAL"),
        },
    )
    print(
        "CTRADER_DEMO_XAU_PREPARED_PLAN_LIFECYCLE "
        f"healthy={healthy} degraded={degraded} "
        f"plans={metrics['plans']} rows_upserted={written} "
        f"cancel_rate={metrics['cancellation_rate']} "
        f"execution_conversion={metrics['execution_conversion_rate']} "
        f"critical_sources={len(critical_errors)} "
        f"degraded_sources={len(degraded_errors)} "
        f"error={error or 'NONE'}"
    )
    return 0 if healthy else 2


if __name__ == "__main__":
    raise SystemExit(run())

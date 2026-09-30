from __future__ import annotations

import os
from dataclasses import replace
from datetime import UTC, datetime
from math import isfinite
from time import sleep
from typing import Any, Callable

from .xau_structure_admission import evaluate_structure_admission
from .demo_xau_structural_targets_v229 import build_structural_target_plan
from .demo_xau_v229_depth_execution import (
    ATLAS_WORKER,
    EVENT_TYPE,
    STRATEGY_ID,
    V226_WORKER,
    _dt,
    _latest_heartbeat,
)
from .demo_xau_v229_ladder_plan import (
    CHILD_LOT,
    MAX_CHILDREN,
    MIN_TERMINAL_RR,
    _target_pool,
    build_parent_ladder_plan,
    child_client_order_id,
)
from .execution.control_plane import ControlPlaneGate, ControlPlaneRefreshWorker
from .execution.demo_autotrade import SupabaseOrderAuditSink
from .execution.factory import build_broker_gateway
from .execution.models import ExecutionMode, OrderIntent, OrderSide, OrderType
from .execution.policy import load_execution_policy
from .execution.router import ExecutionRouter
from .storage.supabase_operational import SupabaseOperationalStore
from .transient import TRANSIENT_RETRY_DELAYS, is_transient_backend_error
from .xau_pressure_transition_v249 import (
    DOM_WORKER,
    evaluate_pressure_transition,
)
from .xau_reversal_stage_v280 import evaluate_reversal_stage
from .xau_dynamic_depth_hazard_v251 import (
    build_dynamic_depth_hazard,
    child_reference_depth,
)

SYMBOL = "XAUUSD"
WORKER_NAME = "ctrader_demo_xau_v229_child_executor"
CHILD_EVENT_TYPE = "DEMO_XAU_RIZAN_DEPTH_CHILD"
CHILD_EVENT_CODE = "XAU_RIZAN_DEPTH_CHILD_EXECUTION_V229_1"
CHILD_CANCEL_EVENT_TYPE = "DEMO_XAU_RIZAN_DEPTH_CHILD_CANCEL"
CHILD_CANCEL_EVENT_CODE = "XAU_RIZAN_DEPTH_CHILD_CANCEL_V292_1"
MAX_PARENT_EVENTS = 24
CALIBRATION_PROBE_ENABLED_ENV = "CTRADER_DEMO_DEPTH_CALIBRATION_PROBE_ENABLED"
CALIBRATION_PROBE_MIN_RR_ENV = "CTRADER_DEMO_DEPTH_CALIBRATION_PROBE_MIN_RR"
CALIBRATION_PROBE_MAX_DEPTH_ENV = "CTRADER_DEMO_DEPTH_CALIBRATION_PROBE_MAX_DEPTH"
CALIBRATION_REJECTION_MAX_AGE_SECONDS_ENV = (
    "CTRADER_DEMO_DEPTH_CALIBRATION_REJECTION_MAX_AGE_SECONDS"
)


def _f(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return bool(default)
    return raw.strip().upper() in {"1", "TRUE", "YES", "ON"}


def _float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw in (None, ""):
        return float(default)
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return float(default)
    return value if isfinite(value) else float(default)


def _account_label() -> str:
    return (
        os.getenv("CTRADER_ACCOUNT_ID", "").strip()
        or os.getenv("CTRADER_TRADER_LOGIN", "").strip()
    )


def _read_with_transient_retry(
    operation: Callable[[], Any],
    *,
    delays: tuple[float, ...] = TRANSIENT_RETRY_DELAYS,
    sleeper: Callable[[float], None] = sleep,
) -> Any:
    """Retry read-only backend I/O only for classified transient failures."""
    last_exc: BaseException | None = None
    for delay in delays:
        if delay:
            sleeper(float(delay))
        try:
            return operation()
        except Exception as exc:
            if not is_transient_backend_error(exc):
                raise
            last_exc = exc
    if last_exc is None:
        raise RuntimeError("TRANSIENT_READ_RETRY_EXHAUSTED_WITHOUT_ATTEMPT")
    raise last_exc


def _latest_parent_rows(store: SupabaseOperationalStore) -> list[dict[str, Any]]:
    def fetch() -> Any:
        return (
            store.client.table("broker_order_events")
            .select("signal_key,observed_at,payload,event_type,code")
            .eq("event_type", EVENT_TYPE)
            .eq("code", STRATEGY_ID)
            .order("observed_at", desc=True)
            .limit(MAX_PARENT_EVENTS)
            .execute()
        )

    response = _read_with_transient_retry(fetch)
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in response.data or []:
        signal_id = str(raw.get("signal_key") or "")
        if not signal_id or signal_id in seen:
            continue
        seen.add(signal_id)
        out.append(dict(raw))
    return out


def _signal_row(store: SupabaseOperationalStore, signal_id: str) -> dict[str, Any]:
    def fetch() -> Any:
        return (
            store.client.table("signals")
            .select("id,state,expires_at,active_guards,observed_at")
            .eq("id", signal_id)
            .limit(1)
            .execute()
        )

    response = _read_with_transient_retry(fetch)
    rows = list(response.data or [])
    return {} if not rows else dict(rows[0])


def _promote_armed_confirmation_window(
    store: SupabaseOperationalStore,
    signal_id: str,
) -> bool:
    """Atomically remove confirmation guards only after an executable M5 child exists."""
    result = (
        store.client.table("signals")
        .update({"state": "EXECUTION_READY", "active_guards": []})
        .eq("id", signal_id)
        .eq("state", "ARMED")
        .execute()
    )
    return len(list(result.data or [])) == 1


def _promote_armed_calibration_parent(
    store: SupabaseOperationalStore,
    signal_id: str,
) -> bool:
    """Promote a DEMO calibration parent only after strict pressure+depth become ready."""
    result = (
        store.client.table("signals")
        .update({"state": "EXECUTION_READY", "active_guards": []})
        .eq("id", signal_id)
        .eq("state", "ARMED")
        .execute()
    )
    return len(list(result.data or [])) == 1


def _invalidate_signal_for_reversal_stage(
    store: SupabaseOperationalStore,
    signal_id: str,
    stage: str,
) -> int:
    guards = [f"V280_{str(stage or 'BLOCK').upper()}"]
    updated = 0
    for prior_state in ("ARMED", "EXECUTION_READY", "COOLDOWN"):
        result = (
            store.client.table("signals")
            .update({"state": "INVALIDATED", "active_guards": guards})
            .eq("id", signal_id)
            .eq("state", prior_state)
            .execute()
        )
        updated += len(list(result.data or []))
    return updated


def _pending_orders(reconcile: Any) -> tuple[Any, ...]:
    return tuple(getattr(reconcile, "order", ()) or ())


def _positions(reconcile: Any) -> tuple[Any, ...]:
    return tuple(getattr(reconcile, "position", ()) or ())


def _order_client_id(order: Any) -> str:
    return str(getattr(order, "clientOrderId", "") or "")


def _position_comment(position: Any) -> str:
    trade_data = getattr(position, "tradeData", None)
    return str(getattr(trade_data, "comment", "") or "")


def _position_is_protected(position: Any) -> bool:
    return (
        float(getattr(position, "stopLoss", 0.0) or 0.0) > 0.0
        and float(getattr(position, "takeProfit", 0.0) or 0.0) > 0.0
    )


def _child_ids(plan: dict[str, Any]) -> dict[int, str]:
    plan_id = str(plan.get("plan_id") or "")
    return {
        slot: child_client_order_id(plan_id, slot)
        for slot in range(1, MAX_CHILDREN + 1)
    }


def _existing_slots(plan: dict[str, Any], reconcile: Any) -> set[int]:
    ids = _child_ids(plan)
    existing: set[int] = set()
    for order in _pending_orders(reconcile):
        cid = _order_client_id(order)
        for slot, child_id in ids.items():
            if cid == child_id:
                existing.add(slot)
    for position in _positions(reconcile):
        comment = _position_comment(position)
        for slot, child_id in ids.items():
            if child_id and child_id in comment:
                existing.add(slot)
    return existing


def _pending_for_plan(plan: dict[str, Any], reconcile: Any) -> list[Any]:
    wanted = set(_child_ids(plan).values())
    return [
        order
        for order in _pending_orders(reconcile)
        if _order_client_id(order) in wanted
    ]


def _cancel_pending_plan(
    session: Any,
    plan: dict[str, Any],
    reconcile: Any,
    *,
    store: SupabaseOperationalStore | None = None,
    parent_signal_id: str | None = None,
    reason: str = "UNSPECIFIED",
) -> list[str]:
    """Cancel only children belonging to one parent and durably audit the result.

    Broker cancellation remains authoritative. Audit/reconcile telemetry is
    fail-soft and must never turn a successful cancel ACK into a retry.
    """
    outcomes: list[str] = []
    attempts: list[dict[str, Any]] = []
    for order in _pending_for_plan(plan, reconcile):
        order_id = int(getattr(order, "orderId", 0) or 0)
        child_id = _order_client_id(order)
        if order_id <= 0:
            outcomes.append("ORDER_ID_MISSING")
            continue
        response = session.cancel_order(order_id)
        execution_type = int(getattr(response, "executionType", -1))
        broker_ack = execution_type == 5
        attempts.append(
            {
                "order_id": order_id,
                "child_id": child_id,
                "execution_type": execution_type,
                "broker_ack": broker_ack,
            }
        )
        if broker_ack:
            outcomes.append(f"CANCELLED:{order_id}")
        else:
            outcomes.append(f"CANCEL_REJECTED:{order_id}:{execution_type}")

    reconciled_pending_ids: set[int] | None = None
    reconcile_error: str | None = None
    if any(bool(row["broker_ack"]) for row in attempts):
        try:
            post_cancel = session.reconcile()
            reconciled_pending_ids = {
                int(getattr(order, "orderId", 0) or 0)
                for order in _pending_orders(post_cancel)
                if int(getattr(order, "orderId", 0) or 0) > 0
            }
        except Exception as exc:
            reconcile_error = f"{type(exc).__name__}:{exc}"

    if store is not None:
        for row in attempts:
            order_id = int(row["order_id"])
            broker_ack = bool(row["broker_ack"])
            reconciled_absent = (
                None
                if reconciled_pending_ids is None
                else order_id not in reconciled_pending_ids
            )
            if not broker_ack:
                audit_code = "CANCEL_REJECTED"
            elif reconciled_absent is True:
                audit_code = "CANCEL_ACK_RECONCILED_ABSENT"
            elif reconciled_absent is False:
                audit_code = "CANCEL_ACK_STILL_PENDING_ON_RECONCILE"
            else:
                audit_code = "CANCEL_ACK_RECONCILE_UNAVAILABLE"
            try:
                store.record_order_event(
                    backend="CTRADER",
                    account_id=_account_label(),
                    signal_key=str(parent_signal_id or row["child_id"] or plan.get("plan_id") or "UNKNOWN"),
                    event_type=CHILD_CANCEL_EVENT_TYPE,
                    broker_order_id=str(order_id),
                    accepted=broker_ack,
                    code=CHILD_CANCEL_EVENT_CODE,
                    message=audit_code,
                    payload={
                        "environment": "DEMO",
                        "plan_id": str(plan.get("plan_id") or ""),
                        "parent_signal_id": str(parent_signal_id or ""),
                        "child_id": str(row["child_id"] or ""),
                        "cancel_reason": str(reason or "UNSPECIFIED"),
                        "broker_execution_type": int(row["execution_type"]),
                        "broker_cancel_ack": broker_ack,
                        "reconciled_absent": reconciled_absent,
                        "reconcile_error": reconcile_error,
                    },
                )
            except Exception as exc:
                outcomes.append(
                    f"CANCEL_AUDIT_WRITE_FAILED:{order_id}:{type(exc).__name__}"
                )
    return outcomes


def _activation_entry(
    *,
    slot: int,
    direction: str,
    child: dict[str, Any],
    micro: dict[str, Any],
) -> tuple[float | None, str]:
    if slot <= 2:
        return _f(child.get("reference_price")), "PRE_TOUCH_LIMIT"
    if str(micro.get("direction") or "").upper() != direction:
        return None, "M5_DIRECTION_MISMATCH"
    if slot == 3:
        if not bool(micro.get("reclaim_confirmed")) or not bool(micro.get("mss_confirmed")):
            return None, "WAIT_M5_RECLAIM_MSS"
        pocket = dict(micro.get("candidate_entry_pocket") or {})
        entry = _f(pocket.get("high" if direction == "LONG" else "low"))
        return entry, "M5_RECLAIM_MSS_RETEST"
    if slot == 4:
        if not bool(micro.get("displacement_confirmed")):
            return None, "WAIT_M5_DISPLACEMENT"
        pocket = dict(micro.get("refined_entry_pocket") or {})
        entry = _f(pocket.get("high" if direction == "LONG" else "low"))
        return entry, "M5_DISPLACEMENT_RETEST"
    return None, "INVALID_SLOT"


def _calibration_probe_entry(
    *,
    direction: str,
    micro: dict[str, Any],
) -> tuple[float | None, str]:
    """Use the favorable edge of a real M5 pocket for one DEMO-only probe."""
    if str(micro.get("direction") or "").upper() != direction:
        return None, "PROBE_M5_DIRECTION_MISMATCH"
    refined = dict(micro.get("refined_entry_pocket") or {})
    candidate = dict(micro.get("candidate_entry_pocket") or {})
    pocket = refined or candidate
    if not pocket:
        return None, "WAIT_M5_POCKET"
    low = _f(pocket.get("low"))
    high = _f(pocket.get("high"))
    if low is None or high is None or high <= low:
        return None, "WAIT_VALID_M5_POCKET"
    entry = float(low) if direction == "LONG" else float(high)
    state = (
        "M5_REFINED_CALIBRATION_PROBE"
        if refined
        else "M5_CANDIDATE_CALIBRATION_PROBE"
    )
    return entry, state


def _calibration_rejection_retest_entry(
    *,
    direction: str,
    micro: dict[str, Any],
    depth_hazard: dict[str, Any],
    now: datetime,
    max_age_seconds: float,
) -> tuple[float | None, str]:
    """Convert a real deep M5 pocket rejection into a bounded retest LIMIT.

    This is DEMO calibration only. It never uses the display-only projected M5
    pocket. The actual M5 candidate/refined pocket must have been touched, then a
    closed M5 price must reject out of that pocket in the intended direction.
    The resulting LIMIT sits inside the current Dynamic Depth no-chase band.
    """
    if str(micro.get("direction") or "").upper() != direction:
        return None, "PROBE_REJECTION_M5_DIRECTION_MISMATCH"
    if not bool(depth_hazard.get("calibration_probe_depth_eligible")):
        return None, "PROBE_REJECTION_DEPTH_NOT_ELIGIBLE"

    refined = dict(micro.get("refined_entry_pocket") or {})
    candidate = dict(micro.get("candidate_entry_pocket") or {})
    pocket = refined or candidate
    if not pocket:
        return None, "PROBE_REJECTION_WAIT_M5_POCKET"

    low = _f(pocket.get("low"))
    high = _f(pocket.get("high"))
    last_close = _f(micro.get("last_closed_m5_price"))
    if low is None or high is None or last_close is None or high <= low:
        return None, "PROBE_REJECTION_INVALID_M5_GEOMETRY"

    if direction == "SHORT":
        rejected = float(last_close) < float(low)
    elif direction == "LONG":
        rejected = float(last_close) > float(high)
    else:
        return None, "PROBE_REJECTION_INVALID_DIRECTION"
    if not rejected:
        return None, "PROBE_REJECTION_WAIT_CLOSED_M5_EXIT"

    sweep = dict(micro.get("sweep") or {})
    origin_at = _dt(
        pocket.get("origin_at")
        or sweep.get("at")
        or micro.get("first_eligible_touch_at")
    )
    if origin_at is None:
        return None, "PROBE_REJECTION_M5_TIME_MISSING"
    age_seconds = (now - origin_at).total_seconds()
    if age_seconds < 0 or age_seconds > float(max_age_seconds):
        return None, "PROBE_REJECTION_M5_TOO_OLD"

    recommended_low = _f(depth_hazard.get("recommended_price_low"))
    recommended_high = _f(depth_hazard.get("recommended_price_high"))
    if (
        recommended_low is None
        or recommended_high is None
        or recommended_high <= recommended_low
    ):
        return None, "PROBE_REJECTION_DEPTH_PRICE_WINDOW_MISSING"

    entry = (
        float(recommended_low)
        if direction == "LONG"
        else float(recommended_high)
    )
    return entry, (
        "M5_REFINED_REJECTION_RETEST_PROBE"
        if refined
        else "M5_CANDIDATE_REJECTION_RETEST_PROBE"
    )


def _source_depth_boundary_price(
    *,
    atlas_evaluation: dict[str, Any],
    direction: str,
    depth: float,
) -> float | None:
    """Map normalized source-zone depth back to price.

    SHORT supply depth grows from proximal low -> distal high.
    LONG demand depth grows from proximal high -> distal low.
    """
    path_map = dict(atlas_evaluation.get("path_map") or {})
    active_path = dict(path_map.get("active_path") or {})
    source = dict(active_path.get("source_zone") or {})
    if not source:
        projection = dict(atlas_evaluation.get("m5_path_projection") or {})
        current_leg = dict(projection.get("current_leg") or {})
        source = dict(current_leg.get("source_zone") or {})
    side = str(direction or "").upper()
    if str(source.get("direction") or "").upper() != side:
        return None
    low = _f(source.get("low"))
    high = _f(source.get("high"))
    if low is None or high is None or high <= low:
        return None
    d = min(1.0, max(0.0, float(depth)))
    width = float(high) - float(low)
    if side == "SHORT":
        return float(low) + width * d
    if side == "LONG":
        return float(high) - width * d
    return None


def _calibration_rejection_exit_stop_entry(
    *,
    direction: str,
    micro: dict[str, Any],
    atlas_evaluation: dict[str, Any],
    max_depth: float,
    now: datetime,
    max_age_seconds: float,
) -> tuple[float | None, str]:
    """Stage a DEMO-only STOP at the no-chase boundary after a deep M5 rejection.

    The real M5 pocket must first reject in the intended reversal direction.
    Unlike the LIMIT retest path, current live depth may still be beyond the
    no-chase ceiling; the STOP waits at the ceiling and only triggers once price
    actually exits the deep zone.
    """
    side = str(direction or "").upper()
    if str(micro.get("direction") or "").upper() != side:
        return None, "PROBE_EXIT_STOP_M5_DIRECTION_MISMATCH"
    refined = dict(micro.get("refined_entry_pocket") or {})
    candidate = dict(micro.get("candidate_entry_pocket") or {})
    pocket = refined or candidate
    if not pocket:
        return None, "PROBE_EXIT_STOP_WAIT_M5_POCKET"
    low = _f(pocket.get("low"))
    high = _f(pocket.get("high"))
    last_close = _f(micro.get("last_closed_m5_price"))
    if low is None or high is None or last_close is None or high <= low:
        return None, "PROBE_EXIT_STOP_INVALID_M5_GEOMETRY"
    if side == "SHORT":
        rejected = float(last_close) < float(low)
    elif side == "LONG":
        rejected = float(last_close) > float(high)
    else:
        return None, "PROBE_EXIT_STOP_INVALID_DIRECTION"
    if not rejected:
        return None, "PROBE_EXIT_STOP_WAIT_CLOSED_M5_REJECTION"

    sweep = dict(micro.get("sweep") or {})
    origin_at = _dt(
        pocket.get("origin_at")
        or sweep.get("at")
        or micro.get("first_eligible_touch_at")
    )
    if origin_at is None:
        return None, "PROBE_EXIT_STOP_M5_TIME_MISSING"
    age_seconds = (now - origin_at).total_seconds()
    if age_seconds < 0 or age_seconds > float(max_age_seconds):
        return None, "PROBE_EXIT_STOP_M5_TOO_OLD"

    entry = _source_depth_boundary_price(
        atlas_evaluation=atlas_evaluation,
        direction=side,
        depth=float(max_depth),
    )
    if entry is None:
        return None, "PROBE_EXIT_STOP_SOURCE_DEPTH_UNAVAILABLE"
    return float(entry), (
        "M5_REFINED_DEEP_REJECTION_EXIT_STOP"
        if refined
        else "M5_CANDIDATE_DEEP_REJECTION_EXIT_STOP"
    )


def _composite_calibration_pressure_allowed(
    *,
    direction: str,
    composite_pressure: dict[str, Any],
) -> tuple[bool, str]:
    """Allow only the tiny DEMO calibration lane to fall back from stale DOM.

    The V272 price-derived pressure has no standalone execution authority. It
    can merely replace a stale/unavailable DOM sample for the 0.01-lot
    calibration child. Fresh materially-opposing DOM still wins and blocks.
    """
    side = str(direction or "").upper()
    if not bool(composite_pressure.get("available")):
        return False, "COMPOSITE_PRESSURE_UNAVAILABLE"
    if side == "LONG":
        allowed = bool(composite_pressure.get("long_calibration_allowed"))
    elif side == "SHORT":
        allowed = bool(composite_pressure.get("short_calibration_allowed"))
    else:
        return False, "COMPOSITE_PRESSURE_NO_DIRECTION"
    return (
        allowed,
        "COMPOSITE_PRICE_PRESSURE_NOT_MATERIALLY_OPPOSING"
        if allowed
        else "COMPOSITE_PRICE_PRESSURE_OPPOSING",
    )


def _entry_inside_active_source(
    *,
    direction: str,
    entry: float,
    atlas_evaluation: dict[str, Any],
) -> bool:
    path_map = dict(atlas_evaluation.get("path_map") or {})
    active_path = dict(path_map.get("active_path") or {})
    source = dict(active_path.get("source_zone") or {})
    if not source:
        projection = dict(atlas_evaluation.get("m5_path_projection") or {})
        current_leg = dict(projection.get("current_leg") or {})
        source = dict(current_leg.get("source_zone") or {})
    if str(source.get("direction") or "").upper() != direction:
        return False
    low = _f(source.get("low"))
    high = _f(source.get("high"))
    return bool(
        low is not None
        and high is not None
        and float(low) <= float(entry) <= float(high)
    )


def _target_with_min_rr(
    *,
    direction: str,
    entry: float,
    stop: float,
    atlas_evaluation: dict[str, Any],
    minimum_rr: float,
) -> tuple[float | None, dict[str, Any]]:
    m15_targets, htf_targets = _target_pool(atlas_evaluation)
    structural = build_structural_target_plan(
        direction=direction,
        entry=entry,
        stop=stop,
        m15_zones=m15_targets,
        htf_zones=htf_targets,
        minimum_rr=float(minimum_rr),
    )
    terminal = dict(structural.get("terminal_structural_target") or {})
    if not bool(structural.get("terminal_rr_eligible")):
        return None, structural
    return _f(terminal.get("target_price")), structural


def _limit_side_valid(direction: str, entry: float, *, bid: float, ask: float) -> bool:
    if direction == "LONG":
        return entry < ask
    return entry > bid


def _pending_side_valid(
    direction: str,
    order_type: OrderType,
    entry: float,
    *,
    bid: float,
    ask: float,
) -> bool:
    if order_type == OrderType.LIMIT:
        return _limit_side_valid(direction, entry, bid=bid, ask=ask)
    if order_type == OrderType.STOP:
        if direction == "LONG":
            return entry > ask
        if direction == "SHORT":
            return entry < bid
    return False


def _slot_target(
    *,
    slot: int,
    direction: str,
    entry: float,
    stop: float,
    atlas_evaluation: dict[str, Any],
) -> tuple[float | None, dict[str, Any]]:
    m15_targets, htf_targets = _target_pool(atlas_evaluation)
    structural = build_structural_target_plan(
        direction=direction,
        entry=entry,
        stop=stop,
        m15_zones=m15_targets,
        htf_zones=htf_targets,
        minimum_rr=MIN_TERMINAL_RR,
    )
    targets = [dict(x) for x in list(structural.get("broker_scaleout_targets") or [])]
    if not targets:
        return None, structural
    if slot == 1:
        chosen = targets[0]
    elif slot == 2 and len(targets) >= 2:
        chosen = targets[1]
    else:
        chosen = targets[-1]
    return _f(chosen.get("target_price")), structural


def _calibration_probe_already_accepted(
    store: SupabaseOperationalStore,
    parent_signal_id: str,
) -> bool:
    """A parent gets at most one broker-accepted DEMO calibration probe."""
    response = (
        store.client.table("broker_order_events")
        .select("accepted,payload,event_type")
        .eq("signal_key", parent_signal_id)
        .eq("event_type", CHILD_EVENT_TYPE)
        .order("observed_at", desc=True)
        .limit(20)
        .execute()
    )
    for row in response.data or []:
        payload = dict(row.get("payload") or {})
        if bool(row.get("accepted")) and bool(payload.get("calibration_only")):
            return True
    return False


def _record_child_event(
    store: SupabaseOperationalStore,
    *,
    parent_signal_id: str,
    child_id: str,
    slot: int,
    accepted: bool | None,
    broker_order_id: str | None,
    code: str,
    message: str,
    payload: dict[str, Any],
) -> None:
    store.record_order_event(
        backend="CTRADER",
        account_id=_account_label() or "UNKNOWN",
        signal_key=parent_signal_id,
        broker_order_id=broker_order_id,
        event_type=CHILD_EVENT_TYPE,
        accepted=accepted,
        code=CHILD_EVENT_CODE,
        message=message,
        payload={
            "parent_signal_id": parent_signal_id,
            "child_id": child_id,
            "slot": int(slot),
            "environment": "DEMO",
            **payload,
        },
    )


def _submit_child(
    *,
    router: ExecutionRouter,
    store: SupabaseOperationalStore,
    parent_signal_id: str,
    plan: dict[str, Any],
    child: dict[str, Any],
    entry: float,
    target: float,
    activation: str,
    now: datetime,
    calibration_only: bool = False,
    minimum_rr: float | None = None,
    order_type: OrderType = OrderType.LIMIT,
) -> tuple[bool, str]:
    slot = int(child["slot"])
    child_id = child_client_order_id(str(plan["plan_id"]), slot)
    direction = str(plan["direction"])
    side = OrderSide.BUY if direction == "LONG" else OrderSide.SELL
    intent = OrderIntent(
        signal_id=child_id,
        symbol=SYMBOL,
        side=side,
        order_type=order_type,
        created_at=now,
        volume=CHILD_LOT,
        entry_price=float(entry),
        stop_loss=float(plan["sl"]),
        take_profit=float(target),
        risk_pct=1.0,
        comment=f"DEMO_AUTO:RIZAN_DEPTH_L{slot}",
    )
    try:
        receipt = router.execute(intent)
    except Exception as exc:
        _record_child_event(
            store,
            parent_signal_id=parent_signal_id,
            child_id=child_id,
            slot=slot,
            accepted=False,
            broker_order_id=None,
            code=type(exc).__name__,
            message=str(exc),
            payload={
                "activation": activation,
                "entry": entry,
                "sl": plan["sl"],
                "tp": target,
                "calibration_only": bool(calibration_only),
                "minimum_rr": minimum_rr,
                "order_type": order_type.value,
            },
        )
        return False, f"L{slot}:{type(exc).__name__}:{exc}"
    _record_child_event(
        store,
        parent_signal_id=parent_signal_id,
        child_id=child_id,
        slot=slot,
        accepted=bool(receipt.accepted),
        broker_order_id=receipt.broker_order_id,
        code="ORDER_ACCEPTED" if receipt.accepted else "ORDER_NOT_ACCEPTED",
        message=receipt.message,
        payload={
            "activation": activation,
            "entry": entry,
            "sl": plan["sl"],
            "tp": target,
            "lot": CHILD_LOT,
            "calibration_only": bool(calibration_only),
            "minimum_rr": minimum_rr,
            "order_type": order_type.value,
        },
    )
    return bool(receipt.accepted), f"L{slot}:{'ACCEPTED' if receipt.accepted else 'REJECTED'}"


def run() -> int:
    base_policy = load_execution_policy(None)
    if str(base_policy.ctrader.get("environment", "")).upper() != "DEMO":
        raise SystemExit("RIZAN_CHILD_EXECUTOR_DEMO_ONLY")
    if not bool(base_policy.ctrader.get("require_demo", False)):
        raise SystemExit("RIZAN_CHILD_EXECUTOR_REQUIRE_DEMO")

    enabled = os.getenv("CTRADER_DEMO_DEPTH_EXECUTION_ENABLED", "0").strip() == "1"
    calibration_probe_enabled = _bool_env(
        CALIBRATION_PROBE_ENABLED_ENV,
        True,
    )
    calibration_probe_min_rr = max(
        0.50,
        _float_env(CALIBRATION_PROBE_MIN_RR_ENV, 1.00),
    )
    calibration_probe_max_depth = min(
        1.0,
        max(0.10, _float_env(CALIBRATION_PROBE_MAX_DEPTH_ENV, 0.70)),
    )
    calibration_rejection_max_age_seconds = min(
        7200.0,
        max(
            300.0,
            _float_env(CALIBRATION_REJECTION_MAX_AGE_SECONDS_ENV, 3600.0),
        ),
    )
    store = SupabaseOperationalStore.from_env(execution_ready_score_floor=65.0)
    now = datetime.now(tz=UTC)
    if not enabled:
        store.write_heartbeat(
            WORKER_NAME,
            healthy=True,
            lag_seconds=0.0,
            details={"enabled": False, "reason": "DEPTH_EXECUTION_DISABLED"},
        )
        return 0

    policy = replace(base_policy, mode=ExecutionMode.AUTO)
    gateway, session = build_broker_gateway(policy, (SYMBOL,), backend="CTRADER")
    gate = ControlPlaneGate(
        max_age_seconds=float(policy.live_safety.get("control_state_max_age_seconds", 5))
    )
    # Keep background control-plane I/O on a dedicated Supabase client so
    # periodic refreshes cannot contend with the main executor's operational
    # reads/writes on the same HTTP connection pool.
    control_store = SupabaseOperationalStore.from_env(execution_ready_score_floor=65.0)
    control = ControlPlaneRefreshWorker(control_store, gate, interval_seconds=1.0)
    router = ExecutionRouter(
        policy,
        gateway=gateway,
        session=session,
        control_gate=gate,
        audit_sink=SupabaseOrderAuditSink(store),
    )

    actions: list[str] = []
    error: str | None = None
    try:
        # Keep the execution control snapshot fresh for the entire one-shot
        # child-executor cycle. V266 only refreshed once at startup; by the time
        # structure/DOM/reconcile checks finished, the 5s fail-closed cache could
        # legitimately be stale even though Supabase control state was healthy.
        control.refresh_once()
        if hasattr(control, "start"):
            control.start()
        parents = _latest_parent_rows(store)
        v226_hb = _latest_heartbeat(store, V226_WORKER)
        atlas_hb = _latest_heartbeat(store, ATLAS_WORKER)
        v226_eval = dict(dict(v226_hb.get("details") or {}).get("evaluation") or {})
        atlas_eval = dict(dict(atlas_hb.get("details") or {}).get("evaluation") or {})
        dom_hb = _latest_heartbeat(store, DOM_WORKER)
        quote = gateway.market_quote(SYMBOL)
        direction = str(v226_eval.get("focus_direction") or "").upper()
        live_price = (
            float(quote.ask)
            if direction == "LONG"
            else float(quote.bid)
            if direction == "SHORT"
            else (float(quote.bid) + float(quote.ask)) / 2.0
        )
        admission = evaluate_structure_admission(
            v226_heartbeat=v226_hb, atlas_heartbeat=atlas_hb, now=datetime.now(UTC),
        )
        if not admission["allowed"]:
            actions.append("STRUCTURE_BLOCK:" + admission["reason"])
        current_plan = build_parent_ladder_plan(
            v226_evaluation=v226_eval,
            atlas_evaluation=atlas_eval,
            live_price=live_price,
        )
        if not admission["allowed"]:
            current_plan = None
        current_key = None if current_plan is None else str(current_plan.get("candidate_key") or "")
        pressure_transition = evaluate_pressure_transition(
            direction=direction,
            dom_heartbeat=dom_hb,
            now=now,
        )
        composite_pressure = dict(atlas_eval.get("composite_pressure_v272") or {})
        composite_calibration_allowed, composite_calibration_reason = (
            _composite_calibration_pressure_allowed(
                direction=direction,
                composite_pressure=composite_pressure,
            )
        )
        if current_plan is None:
            # The parent geometry is no longer canonical. Keep telemetry
            # fail-closed too, so a stale V226 hazard cannot look live in
            # diagnostics after the V182 local-remap rule retired the plan.
            depth_hazard = {
                "state": "UNAVAILABLE",
                "reason": "NO_CURRENT_ALIGNED_V229_PLAN",
                "action": "WAIT_STRUCTURE_REMAP",
                "execution_ready": False,
            }
        else:
            depth_hazard = build_dynamic_depth_hazard(
                v226_evaluation=v226_eval,
                direction=direction,
                live_price=live_price,
                pressure_transition=pressure_transition,
            )
        reversal_stage = (
            evaluate_reversal_stage(
                plan=current_plan,
                atlas_evaluation=atlas_eval,
                depth_hazard=depth_hazard,
                pressure_transition=pressure_transition,
                live_price=live_price,
                bid=float(quote.bid),
                ask=float(quote.ask),
                now=now,
            )
            if current_plan is not None
            else {
                "stage": "PREPARE",
                "hard_execution_block": True,
                "reasons": ["NO_CURRENT_ALIGNED_V229_PLAN"],
            }
        )

        for parent in parents:
            parent_signal_id = str(parent.get("signal_key") or "")
            payload = dict(parent.get("payload") or {})
            plan = {
                "plan_id": payload.get("plan_id"),
                "candidate_key": payload.get("candidate_key"),
                "direction": payload.get("direction"),
                "sl": payload.get("planned_sl"),
                "children": list(payload.get("children") or []),
                "confirmation_window_only": bool(
                    payload.get("confirmation_window_only")
                ),
                "calibration_only_armed": bool(
                    payload.get("calibration_only_armed")
                ),
                "confirmation_entry_low": payload.get("confirmation_entry_low"),
                "confirmation_entry_high": payload.get("confirmation_entry_high"),
                "confirmation_rr_threshold": payload.get(
                    "confirmation_rr_threshold"
                ),
            }
            if not plan["plan_id"] or len(plan["children"]) != MAX_CHILDREN:
                continue
            signal = _signal_row(store, parent_signal_id)
            state = str(signal.get("state") or "").upper()
            expires_at = _dt(signal.get("expires_at"))
            reconcile = session.reconcile()

            invalid_parent = bool(
                not current_key
                or str(plan.get("candidate_key") or "") != current_key
                or expires_at is None
                or datetime.now(UTC) > expires_at
                or state == "INVALIDATED"
            )
            if invalid_parent:
                outcomes = _cancel_pending_plan(
                    session,
                    plan,
                    reconcile,
                    store=store,
                    parent_signal_id=parent_signal_id,
                    reason="PARENT_INVALID_OR_SUPERSEDED",
                )
                actions.extend(f"{parent_signal_id}:{x}" for x in outcomes)
                continue

            if bool(reversal_stage.get("hard_execution_block")):
                outcomes = _cancel_pending_plan(
                    session,
                    plan,
                    reconcile,
                    store=store,
                    parent_signal_id=parent_signal_id,
                    reason=(
                        "V280_"
                        + str(reversal_stage.get("stage") or "BLOCK").upper()
                    ),
                )
                actions.extend(
                    f"{parent_signal_id}:V280_CANCEL:{x}" for x in outcomes
                )
                stage = str(reversal_stage.get("stage") or "BLOCK").upper()
                _invalidate_signal_for_reversal_stage(
                    store,
                    parent_signal_id,
                    stage,
                )
                actions.append(
                    f"{parent_signal_id}:V280_BLOCK:{stage}:"
                    + "|".join(
                        str(x) for x in list(reversal_stage.get("reasons") or [])
                    )
                )
                continue

            armed_confirmation_window = bool(
                state == "ARMED" and plan.get("confirmation_window_only")
            )
            armed_calibration_first_touch = bool(
                state == "ARMED" and plan.get("calibration_only_armed")
            )
            if state == "EXECUTION_READY":
                if not store.claim_signal_for_execution(parent_signal_id):
                    actions.append(f"{parent_signal_id}:CLAIM_LOST")
                    continue
                actions.append(f"{parent_signal_id}:PARENT_CLAIMED")
            elif state == "COOLDOWN":
                pass
            elif armed_confirmation_window:
                actions.append(
                    f"{parent_signal_id}:ARMED_WAIT_M5_ACTUAL_ENTRY_AND_RR"
                )
            elif armed_calibration_first_touch:
                actions.append(
                    f"{parent_signal_id}:ARMED_FRESH_FIRST_TOUCH_CALIBRATION_L1_ONLY"
                )
            else:
                continue

            reconcile = session.reconcile()
            if any(not _position_is_protected(p) for p in _positions(reconcile)):
                actions.append(f"{parent_signal_id}:UNPROTECTED_POSITION_BLOCK")
                continue

            # Strict children still require the normal two-sample pressure
            # transition. A retest-parent DEMO calibration probe may continue on
            # WAIT_SECOND_SAMPLE only when the current fresh absolute DOM sample
            # is neutral/supportive. Existing pending orders are always cancelled
            # before this calibration-only bypass is considered.
            pressure_hard_block = bool(pressure_transition.get("hard_block"))
            dom_wait_second_sample = (
                str(pressure_transition.get("state") or "") == "WAIT_SECOND_SAMPLE"
            )
            dom_state = str(pressure_transition.get("state") or "")
            dom_calibration_allowed = bool(
                pressure_transition.get("calibration_entry_allowed")
            )
            composite_fallback_allowed = bool(
                pressure_hard_block
                and (
                    dom_wait_second_sample
                    or dom_state in {
                        "DOM_STALE",
                        "UNAVAILABLE",
                        "DOM_SCORE_MISSING",
                    }
                )
                and composite_calibration_allowed
            )
            calibration_pressure_allowed = bool(
                dom_calibration_allowed or composite_fallback_allowed
            )
            calibration_pressure_bypass = bool(
                pressure_hard_block
                and (
                    armed_confirmation_window
                    or armed_calibration_first_touch
                )
                and calibration_probe_enabled
                and calibration_pressure_allowed
            )
            strict_parent_ready = bool(
                not pressure_hard_block
                and (
                    pressure_transition.get("pre_touch_entry_allowed")
                    or pressure_transition.get("confirmation_entry_allowed")
                )
                and bool(depth_hazard.get("execution_ready"))
            )
            if armed_calibration_first_touch and strict_parent_ready:
                if not _promote_armed_calibration_parent(
                    store,
                    parent_signal_id,
                ):
                    actions.append(
                        f"{parent_signal_id}:CALIBRATION_STRICT_PROMOTION_LOST"
                    )
                    continue
                if not store.claim_signal_for_execution(parent_signal_id):
                    actions.append(
                        f"{parent_signal_id}:CALIBRATION_STRICT_CLAIM_LOST"
                    )
                    continue
                armed_calibration_first_touch = False
                actions.append(
                    f"{parent_signal_id}:CALIBRATION_PARENT_PROMOTED_STRICT"
                )
            if pressure_hard_block:
                outcomes = _cancel_pending_plan(
                    session,
                    plan,
                    reconcile,
                    store=store,
                    parent_signal_id=parent_signal_id,
                    reason="PRESSURE_HARD_BLOCK",
                )
                actions.extend(f"{parent_signal_id}:PRESSURE_CANCEL:{x}" for x in outcomes)
                if calibration_pressure_bypass:
                    pressure_reason = (
                        composite_calibration_reason
                        if composite_fallback_allowed
                        else str(
                            pressure_transition.get("calibration_pressure_reason")
                            or "DOM_CALIBRATION_ALLOWED"
                        )
                    )
                    actions.append(
                        f"{parent_signal_id}:PRESSURE_CALIBRATION_ONLY:"
                        f"{pressure_reason}"
                    )
                else:
                    actions.append(
                        f"{parent_signal_id}:PRESSURE_BLOCK:{pressure_transition.get('state')}:"
                        f"{pressure_transition.get('reason')}"
                    )
                    continue
            if str(depth_hazard.get("state") or "") != "DYNAMIC_DEPTH_HAZARD_AVAILABLE":
                outcomes = _cancel_pending_plan(
                    session,
                    plan,
                    reconcile,
                    store=store,
                    parent_signal_id=parent_signal_id,
                    reason="DYNAMIC_DEPTH_HAZARD_UNAVAILABLE",
                )
                actions.extend(f"{parent_signal_id}:HAZARD_CANCEL:{x}" for x in outcomes)
                actions.append(
                    f"{parent_signal_id}:HAZARD_BLOCK:{depth_hazard.get('reason','UNAVAILABLE')}"
                )
                continue

            existing = _existing_slots(plan, reconcile)
            future_exposure = len(_positions(reconcile)) + len(_pending_orders(reconcile))
            max_positions = int(policy.demo_safety.get("max_concurrent_positions", 10))
            micro = dict(
                atlas_eval.get("micro_refinement")
                or dict(atlas_eval.get("path_map") or {}).get("micro_refinement")
                or {}
            )
            probe_already_accepted = _calibration_probe_already_accepted(
                store,
                parent_signal_id,
            )

            for child in list(plan["children"]):
                slot = int(child.get("slot") or 0)
                if slot in existing or slot not in {1, 2, 3, 4}:
                    continue
                calibration_probe = bool(
                    calibration_probe_enabled
                    and (
                        armed_confirmation_window
                        or armed_calibration_first_touch
                    )
                    and slot == 1
                    and not probe_already_accepted
                )
                if (
                    calibration_probe_enabled
                    and (
                        armed_confirmation_window
                        or armed_calibration_first_touch
                    )
                    and slot == 1
                    and probe_already_accepted
                ):
                    actions.append(
                        f"{parent_signal_id}:L1:CALIBRATION_PROBE_ALREADY_ACCEPTED"
                    )
                    continue
                if armed_calibration_first_touch and slot != 1:
                    actions.append(
                        f"{parent_signal_id}:L{slot}:DISABLED_CALIBRATION_ARM"
                    )
                    continue
                if not bool(child.get("execution_enabled", True)) and not calibration_probe:
                    actions.append(f"{parent_signal_id}:L{slot}:DISABLED_BY_EXECUTION_PHASE")
                    continue
                if len(existing) >= MAX_CHILDREN:
                    actions.append(f"{parent_signal_id}:L{slot}:FOUR_SLOT_CAP")
                    break
                if future_exposure >= max_positions:
                    actions.append(f"{parent_signal_id}:L{slot}:ACCOUNT_CAP")
                    break

                if calibration_probe and not bool(
                    calibration_pressure_allowed
                ):
                    actions.append(
                        f"{parent_signal_id}:L{slot}:PROBE_WAIT_PRESSURE_TRANSITION:"
                        f"{pressure_transition.get('state')}"
                    )
                    continue
                if slot <= 2 and not calibration_probe and not bool(
                    pressure_transition.get("pre_touch_entry_allowed")
                ):
                    actions.append(
                        f"{parent_signal_id}:L{slot}:WAIT_PRESSURE_TRANSITION:"
                        f"{pressure_transition.get('state')}"
                    )
                    continue
                if slot >= 3 and not bool(
                    pressure_transition.get("confirmation_entry_allowed")
                ):
                    actions.append(
                        f"{parent_signal_id}:L{slot}:WAIT_PRESSURE_TRANSITION:"
                        f"{pressure_transition.get('state')}"
                    )
                    continue

                child_order_type = OrderType.LIMIT
                if calibration_probe and armed_calibration_first_touch:
                    entry = _f(child.get("reference_price"))
                    activation = "FRESH_FIRST_TOUCH_CALIBRATION_LIMIT"
                elif calibration_probe:
                    entry, activation = _calibration_probe_entry(
                        direction=str(plan["direction"]),
                        micro=micro,
                    )
                else:
                    entry, activation = _activation_entry(
                        slot=slot,
                        direction=str(plan["direction"]),
                        child=child,
                        micro=micro,
                    )
                if entry is None:
                    actions.append(f"{parent_signal_id}:L{slot}:{activation}")
                    continue

                if slot <= 2:
                    child_depth = child_reference_depth(
                        v226_evaluation=v226_eval,
                        direction=str(plan["direction"]),
                        price=float(entry),
                    )
                    min_depth = _f(depth_hazard.get("recommended_depth_low"))
                    if (
                        child_depth is not None
                        and min_depth is not None
                        and float(child_depth) + 1e-9 < float(min_depth)
                    ):
                        actions.append(
                            f"{parent_signal_id}:L{slot}:WAIT_DEEPER_HAZARD:"
                            f"child_depth={child_depth:.3f}:min={min_depth:.3f}"
                        )
                        continue
                    recommended_high = _f(
                        depth_hazard.get("recommended_depth_high")
                    )
                    effective_probe_max_depth = float(calibration_probe_max_depth)
                    if recommended_high is not None:
                        effective_probe_max_depth = min(
                            effective_probe_max_depth,
                            float(recommended_high) + 0.10,
                        )
                    if (
                        calibration_probe
                        and child_depth is not None
                        and float(child_depth) > effective_probe_max_depth + 1e-9
                    ):
                        fallback_entry, fallback_activation = (
                            _calibration_rejection_retest_entry(
                                direction=str(plan["direction"]),
                                micro=micro,
                                depth_hazard=depth_hazard,
                                now=datetime.now(UTC),
                                max_age_seconds=calibration_rejection_max_age_seconds,
                            )
                        )
                        fallback_depth = (
                            None
                            if fallback_entry is None
                            else child_reference_depth(
                                v226_evaluation=v226_eval,
                                direction=str(plan["direction"]),
                                price=float(fallback_entry),
                            )
                        )
                        limit_fallback_eligible = bool(
                            fallback_entry is not None
                            and fallback_depth is not None
                            and float(fallback_depth)
                            <= effective_probe_max_depth + 1e-9
                            and (
                                min_depth is None
                                or float(fallback_depth) + 1e-9 >= float(min_depth)
                            )
                        )
                        if limit_fallback_eligible:
                            entry = float(fallback_entry)
                            child_depth = float(fallback_depth)
                            activation = fallback_activation
                            child_order_type = OrderType.LIMIT
                            actions.append(
                                f"{parent_signal_id}:L{slot}:PROBE_REJECTION_RETEST_ARMED:"
                                f"entry={entry:.3f}:depth={child_depth:.3f}"
                            )
                        else:
                            exit_entry, exit_activation = (
                                _calibration_rejection_exit_stop_entry(
                                    direction=str(plan["direction"]),
                                    micro=micro,
                                    atlas_evaluation=atlas_eval,
                                    max_depth=effective_probe_max_depth,
                                    now=datetime.now(UTC),
                                    max_age_seconds=calibration_rejection_max_age_seconds,
                                )
                            )
                            exit_depth = (
                                None
                                if exit_entry is None
                                else child_reference_depth(
                                    v226_evaluation=v226_eval,
                                    direction=str(plan["direction"]),
                                    price=float(exit_entry),
                                )
                            )
                            if (
                                exit_entry is None
                                or exit_depth is None
                                or float(exit_depth)
                                > effective_probe_max_depth + 1e-9
                            ):
                                actions.append(
                                    f"{parent_signal_id}:L{slot}:PROBE_DEPTH_TOO_DEEP:"
                                    f"child_depth={child_depth:.3f}:max={effective_probe_max_depth:.3f}:"
                                    f"limit_fallback={fallback_activation}:"
                                    f"exit_stop={exit_activation}"
                                )
                                continue
                            entry = float(exit_entry)
                            child_depth = float(exit_depth)
                            activation = exit_activation
                            child_order_type = OrderType.STOP
                            actions.append(
                                f"{parent_signal_id}:L{slot}:PROBE_DEEP_REJECTION_EXIT_STOP_ARMED:"
                                f"entry={entry:.3f}:depth={child_depth:.3f}"
                            )
                    if calibration_probe and not _entry_inside_active_source(
                        direction=str(plan["direction"]),
                        entry=float(entry),
                        atlas_evaluation=atlas_eval,
                    ):
                        actions.append(
                            f"{parent_signal_id}:L{slot}:PROBE_OUTSIDE_ACTIVE_SOURCE"
                        )
                        continue

                quote = gateway.market_quote(SYMBOL)
                submit_now = datetime.now(UTC)
                admission = evaluate_structure_admission(
                    v226_heartbeat=v226_hb, atlas_heartbeat=atlas_hb, now=submit_now,
                )
                if not admission["allowed"] or expires_at is None or submit_now > expires_at:
                    actions.append(f"{parent_signal_id}:STRUCTURE_BLOCK_OR_EXPIRED")
                    actions.extend(
                        _cancel_pending_plan(
                            session,
                            plan,
                            session.reconcile(),
                            store=store,
                            parent_signal_id=parent_signal_id,
                            reason="STRUCTURE_BLOCK_OR_EXPIRED",
                        )
                    )
                    break
                if not _pending_side_valid(
                    str(plan["direction"]),
                    child_order_type,
                    float(entry),
                    bid=float(quote.bid),
                    ask=float(quote.ask),
                ):
                    actions.append(
                        f"{parent_signal_id}:L{slot}:WAIT_{child_order_type.value}_SIDE"
                    )
                    continue
                if calibration_probe:
                    target, structural = _target_with_min_rr(
                        direction=str(plan["direction"]),
                        entry=float(entry),
                        stop=float(plan["sl"]),
                        atlas_evaluation=atlas_eval,
                        minimum_rr=calibration_probe_min_rr,
                    )
                else:
                    target, structural = _slot_target(
                        slot=slot,
                        direction=str(plan["direction"]),
                        entry=float(entry),
                        stop=float(plan["sl"]),
                        atlas_evaluation=atlas_eval,
                    )
                if target is None or not bool(structural.get("terminal_rr_eligible")):
                    actions.append(
                        f"{parent_signal_id}:L{slot}:"
                        + (
                            f"PROBE_RR_BELOW_{calibration_probe_min_rr:.2f}"
                            if calibration_probe
                            else "NO_VALID_STRUCTURAL_TP"
                        )
                    )
                    continue

                if armed_confirmation_window and not calibration_probe:
                    if not _promote_armed_confirmation_window(
                        store,
                        parent_signal_id,
                    ):
                        actions.append(
                            f"{parent_signal_id}:CONFIRMATION_PROMOTION_LOST"
                        )
                        break
                    if not store.claim_signal_for_execution(parent_signal_id):
                        actions.append(
                            f"{parent_signal_id}:CONFIRMATION_CLAIM_LOST"
                        )
                        break
                    armed_confirmation_window = False
                    actions.append(
                        f"{parent_signal_id}:CONFIRMATION_PROMOTED_AFTER_M5_RR"
                    )

                # Re-anchor control state immediately before crossing into the
                # broker path; the background worker then keeps it fresh across
                # preflight and the router's final mutable-safety recheck.
                control.refresh_once()
                accepted, detail = _submit_child(
                    router=router,
                    store=store,
                    parent_signal_id=parent_signal_id,
                    plan=plan,
                    child=child,
                    entry=float(entry),
                    target=float(target),
                    activation=(
                        f"{activation}|PRESSURE_{pressure_transition.get('state')}"
                    ),
                    now=now,
                    calibration_only=calibration_probe,
                    minimum_rr=(
                        calibration_probe_min_rr
                        if calibration_probe
                        else MIN_TERMINAL_RR
                    ),
                    order_type=child_order_type,
                )
                actions.append(f"{parent_signal_id}:{detail}")
                if accepted:
                    existing.add(slot)
                    future_exposure += 1
                    if calibration_probe:
                        probe_already_accepted = True

            # Only the newest current parent may own execution. Older rows are
            # reconciled/cancelled above, then ignored.
            break
    except Exception as exc:
        error = f"{type(exc).__name__}:{exc}"
    finally:
        try:
            control.stop(timeout=2.0)
        except Exception:
            pass
        try:
            session.close()
        except Exception:
            pass

    store.write_heartbeat(
        WORKER_NAME,
        healthy=error is None,
        lag_seconds=0.0,
        details={
            "enabled": enabled,
            "environment": "DEMO",
            "max_children_per_parent": MAX_CHILDREN,
            "child_lot": CHILD_LOT,
            "calibration_probe_enabled": calibration_probe_enabled,
            "fresh_first_touch_calibration_arm_supported": True,
            "fresh_first_touch_calibration_slots": [1],
            "calibration_probe_lot": CHILD_LOT,
            "calibration_probe_min_rr": calibration_probe_min_rr,
            "calibration_probe_max_depth_ceiling": calibration_probe_max_depth,
            "calibration_probe_dynamic_depth_buffer": 0.10,
            "calibration_rejection_retest_enabled": True,
            "calibration_rejection_max_age_seconds": (
                calibration_rejection_max_age_seconds
            ),
            "calibration_probe_exit_stop_enabled": True,
            "calibration_probe_exit_stop_boundary": "NO_CHASE_MAX_DEPTH",
            "calibration_probe_exit_stop_role": (
                "SECONDARY_RECOVERY_ONLY_AFTER_PRIMARY_NEAR_EDGE_MISSED"
            ),
            "calibration_probe_policy": (
                "ONE_L1_REAL_M5_POCKET_OR_POST_REJECTION_RETEST_PROBE_PER_"
                "ARMED_RETEST_PARENT_DYNAMIC_DEPTH_PLUS_10PCT_CAPPED_DEMO_ONLY"
            ),
            "pending_plus_open_guard": True,
            "server_side_sl_tp_required": True,
            "control_plane_refresh_worker": (
                control.health() if hasattr(control, "health") else {}
            ),
            "control_plane_refresh_interval_seconds": 1.0,
            "control_plane_pre_submit_refresh": True,
            "control_plane_dedicated_store": True,
            "operational_read_transient_retry_delays": list(TRANSIENT_RETRY_DELAYS),
            "generic_market_handoff_allowed": False,
            "pressure_transition_required": True,
            "strict_pressure_transition_requires_two_samples": True,
            "calibration_single_sample_pressure_allowed": True,
            "calibration_composite_pressure_fallback_allowed": True,
            "composite_pressure_v272": composite_pressure if 'composite_pressure' in locals() else {},
            "calibration_single_sample_max_opposing_pressure": 15.0,
            "pressure_transition": pressure_transition if 'pressure_transition' in locals() else {},
            "dynamic_depth_hazard_required": True,
            "dynamic_depth_hazard": depth_hazard if 'depth_hazard' in locals() else {},
            "reversal_stage": reversal_stage if 'reversal_stage' in locals() else {},
            "structure_admission": admission if "admission" in locals() else {},
            "actions": actions[:40],
            "error": error,
            "observed_at": now.isoformat(),
            "code_version": os.getenv("GITHUB_SHA", "LOCAL"),
        },
    )
    print(
        "CTRADER_DEMO_XAU_RIZAN_CHILD_EXECUTOR "
        f"healthy={int(error is None)} actions={len(actions)} error={error or 'NONE'}"
    )
    return 0 if error is None else 2


if __name__ == "__main__":
    raise SystemExit(run())

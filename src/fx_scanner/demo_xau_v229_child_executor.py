from __future__ import annotations

import os
from dataclasses import replace
from datetime import UTC, datetime
from math import isfinite
from typing import Any

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

SYMBOL = "XAUUSD"
WORKER_NAME = "ctrader_demo_xau_v229_child_executor"
CHILD_EVENT_TYPE = "DEMO_XAU_RIZAN_DEPTH_CHILD"
CHILD_EVENT_CODE = "XAU_RIZAN_DEPTH_CHILD_EXECUTION_V229_1"
MAX_PARENT_EVENTS = 24


def _f(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _account_label() -> str:
    return (
        os.getenv("CTRADER_ACCOUNT_ID", "").strip()
        or os.getenv("CTRADER_TRADER_LOGIN", "").strip()
    )


def _latest_parent_rows(store: SupabaseOperationalStore) -> list[dict[str, Any]]:
    response = (
        store.client.table("broker_order_events")
        .select("signal_key,observed_at,payload,event_type,code")
        .eq("event_type", EVENT_TYPE)
        .eq("code", STRATEGY_ID)
        .order("observed_at", desc=True)
        .limit(MAX_PARENT_EVENTS)
        .execute()
    )
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
    response = (
        store.client.table("signals")
        .select("id,state,expires_at,active_guards,observed_at")
        .eq("id", signal_id)
        .limit(1)
        .execute()
    )
    rows = list(response.data or [])
    return {} if not rows else dict(rows[0])


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


def _cancel_pending_plan(session: Any, plan: dict[str, Any], reconcile: Any) -> list[str]:
    outcomes: list[str] = []
    for order in _pending_for_plan(plan, reconcile):
        order_id = int(getattr(order, "orderId", 0) or 0)
        if order_id <= 0:
            outcomes.append("ORDER_ID_MISSING")
            continue
        response = session.cancel_order(order_id)
        execution_type = int(getattr(response, "executionType", -1))
        if execution_type != 5:
            outcomes.append(f"CANCEL_REJECTED:{order_id}:{execution_type}")
        else:
            outcomes.append(f"CANCELLED:{order_id}")
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


def _limit_side_valid(direction: str, entry: float, *, bid: float, ask: float) -> bool:
    if direction == "LONG":
        return entry < ask
    return entry > bid


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
) -> tuple[bool, str]:
    slot = int(child["slot"])
    child_id = child_client_order_id(str(plan["plan_id"]), slot)
    direction = str(plan["direction"])
    side = OrderSide.BUY if direction == "LONG" else OrderSide.SELL
    intent = OrderIntent(
        signal_id=child_id,
        symbol=SYMBOL,
        side=side,
        order_type=OrderType.LIMIT,
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
    control = ControlPlaneRefreshWorker(store, gate, interval_seconds=1.0)
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
        control.refresh_once()
        parents = _latest_parent_rows(store)
        v226_hb = _latest_heartbeat(store, V226_WORKER)
        atlas_hb = _latest_heartbeat(store, ATLAS_WORKER)
        v226_eval = dict(dict(v226_hb.get("details") or {}).get("evaluation") or {})
        atlas_eval = dict(dict(atlas_hb.get("details") or {}).get("evaluation") or {})
        quote = gateway.market_quote(SYMBOL)
        direction = str(v226_eval.get("focus_direction") or "").upper()
        live_price = (
            float(quote.ask)
            if direction == "LONG"
            else float(quote.bid)
            if direction == "SHORT"
            else (float(quote.bid) + float(quote.ask)) / 2.0
        )
        current_plan = build_parent_ladder_plan(
            v226_evaluation=v226_eval,
            atlas_evaluation=atlas_eval,
            live_price=live_price,
        )
        current_key = None if current_plan is None else str(current_plan.get("candidate_key") or "")

        for parent in parents:
            parent_signal_id = str(parent.get("signal_key") or "")
            payload = dict(parent.get("payload") or {})
            plan = {
                "plan_id": payload.get("plan_id"),
                "candidate_key": payload.get("candidate_key"),
                "direction": payload.get("direction"),
                "sl": payload.get("planned_sl"),
                "children": list(payload.get("children") or []),
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
                or (expires_at is not None and now > expires_at)
                or state == "INVALIDATED"
            )
            if invalid_parent:
                outcomes = _cancel_pending_plan(session, plan, reconcile)
                actions.extend(f"{parent_signal_id}:{x}" for x in outcomes)
                continue

            if state == "EXECUTION_READY":
                if not store.claim_signal_for_execution(parent_signal_id):
                    actions.append(f"{parent_signal_id}:CLAIM_LOST")
                    continue
                actions.append(f"{parent_signal_id}:PARENT_CLAIMED")
            elif state != "COOLDOWN":
                continue

            reconcile = session.reconcile()
            if any(not _position_is_protected(p) for p in _positions(reconcile)):
                actions.append(f"{parent_signal_id}:UNPROTECTED_POSITION_BLOCK")
                continue
            existing = _existing_slots(plan, reconcile)
            future_exposure = len(_positions(reconcile)) + len(_pending_orders(reconcile))
            max_positions = int(policy.demo_safety.get("max_concurrent_positions", 10))
            micro = dict(
                atlas_eval.get("micro_refinement")
                or dict(atlas_eval.get("path_map") or {}).get("micro_refinement")
                or {}
            )

            for child in list(plan["children"]):
                slot = int(child.get("slot") or 0)
                if slot in existing or slot not in {1, 2, 3, 4}:
                    continue
                if len(existing) >= MAX_CHILDREN:
                    actions.append(f"{parent_signal_id}:L{slot}:FOUR_SLOT_CAP")
                    break
                if future_exposure >= max_positions:
                    actions.append(f"{parent_signal_id}:L{slot}:ACCOUNT_CAP")
                    break

                entry, activation = _activation_entry(
                    slot=slot,
                    direction=str(plan["direction"]),
                    child=child,
                    micro=micro,
                )
                if entry is None:
                    actions.append(f"{parent_signal_id}:L{slot}:{activation}")
                    continue
                quote = gateway.market_quote(SYMBOL)
                if not _limit_side_valid(
                    str(plan["direction"]),
                    float(entry),
                    bid=float(quote.bid),
                    ask=float(quote.ask),
                ):
                    actions.append(f"{parent_signal_id}:L{slot}:WAIT_RETEST_LIMIT_SIDE")
                    continue
                target, structural = _slot_target(
                    slot=slot,
                    direction=str(plan["direction"]),
                    entry=float(entry),
                    stop=float(plan["sl"]),
                    atlas_evaluation=atlas_eval,
                )
                if target is None or not bool(structural.get("terminal_rr_eligible")):
                    actions.append(f"{parent_signal_id}:L{slot}:NO_VALID_STRUCTURAL_TP")
                    continue
                accepted, detail = _submit_child(
                    router=router,
                    store=store,
                    parent_signal_id=parent_signal_id,
                    plan=plan,
                    child=child,
                    entry=float(entry),
                    target=float(target),
                    activation=activation,
                    now=now,
                )
                actions.append(f"{parent_signal_id}:{detail}")
                if accepted:
                    existing.add(slot)
                    future_exposure += 1

            # Only the newest current parent may own execution. Older rows are
            # reconciled/cancelled above, then ignored.
            break
    except Exception as exc:
        error = f"{type(exc).__name__}:{exc}"
    finally:
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
            "pending_plus_open_guard": True,
            "server_side_sl_tp_required": True,
            "generic_market_handoff_allowed": False,
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

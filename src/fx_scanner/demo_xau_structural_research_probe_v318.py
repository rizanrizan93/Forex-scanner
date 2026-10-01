from __future__ import annotations

import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from math import isfinite
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from .demo_xau_v229_child_executor import _limit_side_valid
from .demo_xau_v229_ladder_plan import build_parent_ladder_plan
from .execution.control_plane import ControlPlaneGate, ControlPlaneRefreshWorker
from .execution.demo_autotrade import SupabaseOrderAuditSink
from .execution.factory import build_broker_gateway
from .execution.models import ExecutionMode, OrderIntent, OrderSide, OrderType
from .execution.policy import load_execution_policy
from .execution.router import ExecutionRouter
from .storage.supabase_operational import SupabaseOperationalStore

SYMBOL = "XAUUSD"
WORKER_NAME = "ctrader_demo_xau_structural_research_probe_v318"
ATLAS_WORKER = "ctrader_demo_xau_supply_demand_atlas_v182"
V226_WORKER = "ctrader_demo_xau_v226_rizan_depth_map"
EVENT_WORKER = "ctrader_demo_xau_event_risk_v192"
SHOCK_WORKER = "ctrader_demo_xau_v203_volatility_shock_guard"
FEATURE_ENV = "CTRADER_DEMO_XAU_STRUCTURAL_RESEARCH_PROBE_ENABLED"
SETUP_TYPE = "RIZAN_STRUCTURAL_RESEARCH_PROBE_V318"
ORDER_EVENT_TYPE = "DEMO_XAU_STRUCTURAL_RESEARCH_PROBE"
ORDER_EVENT_CODE = "XAU_STRUCTURAL_RESEARCH_PROBE_V318_1"
CANCEL_EVENT_TYPE = "DEMO_XAU_STRUCTURAL_RESEARCH_PROBE_CANCEL"
CANCEL_EVENT_CODE = "XAU_STRUCTURAL_RESEARCH_PROBE_CANCEL_V318_1"
LOT = 0.01
MIN_RR = 1.0
MAX_STRUCTURE_AGE_SECONDS = 900.0
MAX_RISK_CONTEXT_AGE_SECONDS = 900.0


def _f(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


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


def _age_seconds(value: Any, *, now: datetime) -> float | None:
    observed = _dt(value)
    if observed is None:
        return None
    return max(0.0, (now - observed).total_seconds())


def probe_signal_id(candidate_key: str) -> str:
    key = str(candidate_key or "").strip()
    if not key:
        raise ValueError("candidate_key is required")
    return str(uuid5(NAMESPACE_URL, f"rizan-structural-probe-v318:{key}"))


def _latest_heartbeat(
    store: SupabaseOperationalStore,
    worker_name: str,
) -> dict[str, Any] | None:
    response = (
        store.client.table("runtime_heartbeats")
        .select("worker_name,observed_at,healthy,details")
        .eq("worker_name", worker_name)
        .order("observed_at", desc=True)
        .limit(1)
        .execute()
    )
    rows = [dict(row or {}) for row in (response.data or [])]
    return rows[0] if rows else None


def _recent_probe_signals(
    store: SupabaseOperationalStore,
) -> dict[str, dict[str, Any]]:
    response = (
        store.client.table("signals")
        .select("id,state,observed_at,expires_at")
        .eq("symbol", SYMBOL)
        .eq("setup_type", SETUP_TYPE)
        .order("observed_at", desc=True)
        .limit(64)
        .execute()
    )
    return {
        str(row.get("id")): dict(row or {})
        for row in (response.data or [])
        if row.get("id")
    }


def _position_comment(position: Any) -> str:
    trade = getattr(position, "tradeData", None)
    return str(
        getattr(trade, "comment", "")
        or getattr(position, "comment", "")
        or ""
    ).strip()


def _order_client_id(order: Any) -> str:
    return str(getattr(order, "clientOrderId", "") or "").strip()


def _probe_position_signal_id(
    position: Any,
    known_ids: set[str],
) -> str | None:
    comment = _position_comment(position)
    for signal_id in known_ids:
        if signal_id and signal_id in comment:
            return signal_id
    return None


def _strict_depth_exposure(reconcile: Any) -> bool:
    for order in tuple(getattr(reconcile, "order", ()) or ()):
        if _order_client_id(order).startswith("RZ229:"):
            return True
    for position in tuple(getattr(reconcile, "position", ()) or ()):
        comment = _position_comment(position).upper()
        if "RZ229:" in comment or "RIZAN_DEPTH" in comment:
            return True
    return False


def _heartbeat_is_fresh(
    heartbeat: dict[str, Any] | None,
    *,
    now: datetime,
    max_age_seconds: float,
) -> bool:
    if not heartbeat or not bool(heartbeat.get("healthy")):
        return False
    age = _age_seconds(heartbeat.get("observed_at"), now=now)
    return bool(age is not None and age <= float(max_age_seconds))


def _explicit_risk_block(
    *,
    event_heartbeat: dict[str, Any] | None,
    shock_heartbeat: dict[str, Any] | None,
    now: datetime,
) -> tuple[bool, str, dict[str, Any]]:
    event_fresh = _heartbeat_is_fresh(
        event_heartbeat,
        now=now,
        max_age_seconds=MAX_RISK_CONTEXT_AGE_SECONDS,
    )
    shock_fresh = _heartbeat_is_fresh(
        shock_heartbeat,
        now=now,
        max_age_seconds=MAX_RISK_CONTEXT_AGE_SECONDS,
    )
    event_risk = (
        dict(dict(event_heartbeat.get("details") or {}).get("risk") or {})
        if event_heartbeat
        else {}
    )
    shock = dict(shock_heartbeat.get("details") or {}) if shock_heartbeat else {}
    event_state = str(event_risk.get("state") or "UNAVAILABLE").upper()
    shock_state = str(shock.get("state") or "UNAVAILABLE").upper()
    context = {
        "event_fresh": event_fresh,
        "event_state": event_state,
        "event_action": event_risk.get("action"),
        "shock_fresh": shock_fresh,
        "shock_state": shock_state,
        "shock_action": shock.get("shadow_action"),
    }
    if event_fresh and event_state == "EVENT_WINDOW":
        return True, "EVENT_WINDOW_BLOCK", context
    if shock_fresh and shock_state == "SHOCK":
        return True, "VOLATILITY_SHOCK_BLOCK", context
    return False, "CLEAR_OF_EXPLICIT_EXTREME_RISK", context


def _target_for_rr(
    *,
    direction: str,
    entry: float,
    stop: float,
    plan: dict[str, Any],
    minimum_rr: float = MIN_RR,
) -> tuple[float | None, float | None, str]:
    risk = (
        float(entry) - float(stop)
        if direction == "LONG"
        else float(stop) - float(entry)
    )
    if risk <= 0:
        return None, None, "INVALID_STRUCTURAL_RISK"
    for key in ("tp1", "tp2"):
        target = _f(plan.get(key))
        if target is None:
            continue
        reward = (
            float(target) - float(entry)
            if direction == "LONG"
            else float(entry) - float(target)
        )
        rr = reward / risk
        if reward > 0 and rr + 1e-9 >= float(minimum_rr):
            return float(target), float(rr), key.upper()
    return None, None, "STRUCTURAL_RR_BELOW_1R"


def _select_probe_geometry(
    *,
    plan: dict[str, Any],
    bid: float,
    ask: float,
    minimum_rr: float = MIN_RR,
) -> tuple[dict[str, Any] | None, str]:
    direction = str(plan.get("direction") or "").upper()
    if direction not in {"LONG", "SHORT"}:
        return None, "STRUCTURAL_DIRECTION_INVALID"
    source_timeframe = str(plan.get("source_timeframe") or "").upper()
    if source_timeframe not in {"H4", "H1"}:
        return None, "STRUCTURAL_SOURCE_NOT_H4_H1"

    low = _f(plan.get("entry_low"))
    high = _f(plan.get("entry_high"))
    stop = _f(plan.get("sl"))
    if low is None or high is None or stop is None or high <= low:
        return None, "STRUCTURAL_GEOMETRY_INVALID"

    confirmation_only = bool(plan.get("confirmation_window_only"))
    entry = (
        _f(plan.get("confirmation_entry_reference"))
        if confirmation_only
        else None
    )
    activation = (
        "H1_H4_CONFIRMATION_WINDOW_EARLY_PROBE"
        if entry is not None
        else "H1_H4_PRETOUCH_EARLY_PROBE"
    )
    if entry is None:
        children = sorted(
            [dict(row) for row in list(plan.get("children") or [])],
            key=lambda row: int(row.get("slot") or 99),
        )
        for child in children:
            if int(child.get("slot") or 0) not in {1, 2}:
                continue
            reference = _f(child.get("reference_price"))
            if reference is not None:
                entry = float(reference)
                break
    if entry is None:
        entry = _f(dict(plan.get("candidate") or {}).get("entry_reference"))
    if entry is None:
        entry = _f(plan.get("entry"))
    if entry is None:
        return None, "STRUCTURAL_ENTRY_UNAVAILABLE"
    if not (float(low) <= float(entry) <= float(high)):
        return None, "STRUCTURAL_ENTRY_OUTSIDE_CANDIDATE"
    if not _limit_side_valid(
        direction,
        float(entry),
        bid=float(bid),
        ask=float(ask),
    ):
        return None, "NO_CHASE_LIMIT_SIDE_INVALID"

    target, rr, target_basis = _target_for_rr(
        direction=direction,
        entry=float(entry),
        stop=float(stop),
        plan=plan,
        minimum_rr=minimum_rr,
    )
    if target is None or rr is None:
        return None, target_basis

    return {
        "direction": direction,
        "entry": float(entry),
        "sl": float(stop),
        "tp": float(target),
        "rr": float(rr),
        "target_basis": target_basis,
        "activation": activation,
        "plan_id": plan.get("plan_id"),
        "candidate_key": plan.get("candidate_key"),
        "source_layer": plan.get("source_layer"),
        "source_timeframe": source_timeframe,
        "source_zone_id": plan.get("structural_stop_zone_id"),
        "confirmation_window_only": confirmation_only,
        "strict_broker_entry_authorized": bool(plan.get("broker_entry_authorized")),
        "m15_confirmation_bypassed_for_demo_research": confirmation_only,
    }, "STRUCTURAL_PROBE_ELIGIBLE"


def _write_signal(
    store: SupabaseOperationalStore,
    *,
    signal_id: str,
    geometry: dict[str, Any],
    now: datetime,
) -> None:
    direction = str(geometry["direction"])
    entry = float(geometry["entry"])
    rr = float(geometry["rr"])
    store.write_signal_rows(
        [
            {
                "id": signal_id,
                "run_id": None,
                "observed_at": now.isoformat(),
                "symbol": SYMBOL,
                "direction": direction,
                "setup_type": SETUP_TYPE,
                "state": "ARMED",
                "pair_score": None,
                "execution_score": None,
                "final_score": None,
                "entry_low": entry,
                "entry_high": entry,
                "sl": float(geometry["sl"]),
                "tp1": float(geometry["tp"]),
                "tp2": float(geometry["tp"]),
                "tp3": None,
                "rr1": rr,
                "rr2": rr,
                "rr3": None,
                "macro_bias": "",
                "h4_bias": direction,
                "h1_bias": direction,
                "active_guards": ["DEMO_STRUCTURAL_RESEARCH_ONLY"],
                "data_coverage": 1.0,
                "expires_at": (now + timedelta(hours=4)).isoformat(),
            }
        ]
    )


def _update_signal_state(
    store: SupabaseOperationalStore,
    signal_id: str,
    *,
    state: str,
    guards: list[str],
) -> None:
    (
        store.client.table("signals")
        .update({"state": str(state), "active_guards": list(guards)})
        .eq("id", signal_id)
        .execute()
    )


def _record_event(
    store: SupabaseOperationalStore,
    session: Any,
    *,
    signal_id: str,
    event_type: str,
    code: str,
    message: str,
    accepted: bool | None,
    broker_order_id: str | None,
    payload: dict[str, Any],
) -> None:
    store.record_order_event(
        backend="CTRADER",
        account_id=str(getattr(session, "account_id", "UNKNOWN")),
        signal_key=signal_id,
        broker_order_id=broker_order_id,
        event_type=event_type,
        accepted=accepted,
        code=code,
        message=message,
        payload={"environment": "DEMO", **payload},
    )


def _cancel_old_probe_pending(
    *,
    store: SupabaseOperationalStore,
    session: Any,
    reconcile: Any,
    known_ids: set[str],
    keep_signal_id: str | None,
) -> tuple[list[str], bool]:
    actions: list[str] = []
    safe = True
    for order in tuple(getattr(reconcile, "order", ()) or ()):
        client_id = _order_client_id(order)
        if client_id not in known_ids:
            continue
        if keep_signal_id and client_id == keep_signal_id:
            continue
        order_id = int(getattr(order, "orderId", 0) or 0)
        if order_id <= 0:
            safe = False
            actions.append(f"{client_id}:CANCEL_ORDER_ID_MISSING")
            continue
        try:
            response = session.cancel_order(order_id)
            execution_type = int(getattr(response, "executionType", -1))
        except Exception as exc:
            safe = False
            actions.append(f"{client_id}:CANCEL_EXCEPTION:{type(exc).__name__}")
            continue
        if execution_type != 5:
            safe = False
            actions.append(f"{client_id}:CANCEL_REJECTED:{order_id}:{execution_type}")
            continue
        actions.append(f"{client_id}:CANCELLED:{order_id}")
        try:
            _record_event(
                store,
                session,
                signal_id=client_id,
                event_type=CANCEL_EVENT_TYPE,
                code=CANCEL_EVENT_CODE,
                message="CANCELLED_SUPERSEDED_STRUCTURAL_PROBE",
                accepted=True,
                broker_order_id=str(order_id),
                payload={"cancel_reason": "STRUCTURAL_CANDIDATE_CHANGED"},
            )
        except Exception:
            actions.append(f"{client_id}:CANCEL_AUDIT_WRITE_FAILED")
    return actions, safe


def _heartbeat(
    store: SupabaseOperationalStore,
    *,
    healthy: bool,
    state: str,
    actions: list[str],
    details: dict[str, Any],
) -> None:
    store.write_heartbeat(
        WORKER_NAME,
        healthy=healthy,
        lag_seconds=0.0,
        details={
            "state": state,
            "actions": actions[-40:],
            "environment": "DEMO",
            "lot": LOT,
            "minimum_rr": MIN_RR,
            "strict_lane_independent": True,
            "m15_confirmation_required": False,
            "pressure_confirmation_required": False,
            "structure_admission_required": False,
            "dashboard_bridge_required": False,
            "fresh_ctrader_quote_required": True,
            "server_side_sl_tp_required": True,
            "live_execution_enabled": False,
            "code_version": os.getenv("GITHUB_SHA", "LOCAL"),
            **details,
        },
    )


def run() -> int:
    base_policy = load_execution_policy(None)
    if str(base_policy.ctrader.get("environment") or "").upper() != "DEMO":
        raise SystemExit("XAU_STRUCTURAL_RESEARCH_PROBE_DEMO_ONLY")
    if not bool(base_policy.ctrader.get("require_demo", False)):
        raise SystemExit("XAU_STRUCTURAL_RESEARCH_PROBE_REQUIRE_DEMO")

    store = SupabaseOperationalStore.from_env(execution_ready_score_floor=65.0)
    enabled = os.getenv(FEATURE_ENV, "0").strip() == "1"
    if not enabled:
        _heartbeat(
            store,
            healthy=True,
            state="DISABLED",
            actions=[],
            details={"reason": "STRUCTURAL_RESEARCH_PROBE_DISABLED"},
        )
        return 0

    now = datetime.now(tz=UTC)
    atlas_hb = _latest_heartbeat(store, ATLAS_WORKER)
    v226_hb = _latest_heartbeat(store, V226_WORKER)
    event_hb = _latest_heartbeat(store, EVENT_WORKER)
    shock_hb = _latest_heartbeat(store, SHOCK_WORKER)

    if not _heartbeat_is_fresh(
        atlas_hb,
        now=now,
        max_age_seconds=MAX_STRUCTURE_AGE_SECONDS,
    ):
        _heartbeat(
            store,
            healthy=True,
            state="WAIT",
            actions=[],
            details={"reason": "ATLAS_V182_STALE_OR_UNHEALTHY"},
        )
        return 0
    if not _heartbeat_is_fresh(
        v226_hb,
        now=now,
        max_age_seconds=MAX_STRUCTURE_AGE_SECONDS,
    ):
        _heartbeat(
            store,
            healthy=True,
            state="WAIT",
            actions=[],
            details={"reason": "V226_STALE_OR_UNHEALTHY"},
        )
        return 0

    risk_block, risk_reason, risk_context = _explicit_risk_block(
        event_heartbeat=event_hb,
        shock_heartbeat=shock_hb,
        now=now,
    )
    if risk_block:
        _heartbeat(
            store,
            healthy=True,
            state="WAIT_EXTREME_RISK",
            actions=[],
            details={"reason": risk_reason, "risk_context": risk_context},
        )
        return 0

    atlas_eval = dict(dict(atlas_hb.get("details") or {}).get("evaluation") or {})
    v226_eval = dict(dict(v226_hb.get("details") or {}).get("evaluation") or {})
    direction = str(v226_eval.get("focus_direction") or "").upper()
    if direction not in {"LONG", "SHORT"}:
        _heartbeat(
            store,
            healthy=True,
            state="WAIT",
            actions=[],
            details={"reason": "V226_DIRECTION_WAIT"},
        )
        return 0

    policy = replace(base_policy, mode=ExecutionMode.AUTO)
    gateway, session = build_broker_gateway(
        policy,
        (SYMBOL,),
        backend="CTRADER",
    )
    gate = ControlPlaneGate(
        max_age_seconds=float(
            policy.live_safety.get("control_state_max_age_seconds", 5)
        )
    )
    control_store = SupabaseOperationalStore.from_env(
        execution_ready_score_floor=65.0
    )
    control = ControlPlaneRefreshWorker(
        control_store,
        gate,
        interval_seconds=1.0,
    )
    router = ExecutionRouter(
        policy,
        gateway=gateway,
        session=session,
        control_gate=gate,
        audit_sink=SupabaseOrderAuditSink(store),
    )

    actions: list[str] = []
    try:
        control.refresh_once()
        if hasattr(control, "start"):
            control.start()

        quote = gateway.market_quote(SYMBOL)
        live_price = (
            float(quote.ask)
            if direction == "LONG"
            else float(quote.bid)
        )
        diagnostics: dict[str, Any] = {}
        plan = build_parent_ladder_plan(
            v226_evaluation=v226_eval,
            atlas_evaluation=atlas_eval,
            live_price=live_price,
            diagnostics=diagnostics,
        )
        if plan is None:
            _heartbeat(
                store,
                healthy=True,
                state="WAIT",
                actions=actions,
                details={
                    "reason": str(
                        diagnostics.get("reason")
                        or "NO_STRUCTURAL_H1_H4_PROBE_PLAN"
                    ),
                    "plan_diagnostics": diagnostics,
                    "risk_context": risk_context,
                },
            )
            return 0

        geometry, geometry_reason = _select_probe_geometry(
            plan=plan,
            bid=float(quote.bid),
            ask=float(quote.ask),
            minimum_rr=MIN_RR,
        )
        if geometry is None:
            _heartbeat(
                store,
                healthy=True,
                state="WAIT",
                actions=actions,
                details={
                    "reason": geometry_reason,
                    "plan_id": plan.get("plan_id"),
                    "candidate_key": plan.get("candidate_key"),
                    "risk_context": risk_context,
                },
            )
            return 0

        signal_id = probe_signal_id(str(plan.get("candidate_key") or ""))
        prior = _recent_probe_signals(store)
        known_ids = set(prior)
        known_ids.add(signal_id)

        reconcile = session.reconcile()
        cancel_actions, cancel_safe = _cancel_old_probe_pending(
            store=store,
            session=session,
            reconcile=reconcile,
            known_ids=known_ids,
            keep_signal_id=signal_id,
        )
        actions.extend(cancel_actions)
        if not cancel_safe:
            _heartbeat(
                store,
                healthy=False,
                state="CANCEL_RECONCILE_BLOCK",
                actions=actions,
                details={
                    "reason": "OLD_STRUCTURAL_PROBE_NOT_SAFELY_CANCELLED",
                    "signal_id": signal_id,
                },
            )
            return 2

        reconcile = session.reconcile()
        open_probe_ids = [
            probe_id
            for position in tuple(getattr(reconcile, "position", ()) or ())
            for probe_id in [
                _probe_position_signal_id(position, known_ids)
            ]
            if probe_id
        ]
        if open_probe_ids:
            _heartbeat(
                store,
                healthy=True,
                state="PROBE_POSITION_OPEN",
                actions=actions,
                details={
                    "reason": "ONE_STRUCTURAL_RESEARCH_POSITION_MAX",
                    "open_probe_signal_ids": open_probe_ids,
                    "current_signal_id": signal_id,
                    "geometry": geometry,
                },
            )
            return 0

        if _strict_depth_exposure(reconcile):
            _heartbeat(
                store,
                healthy=True,
                state="STRICT_DEPTH_EXPOSURE_ACTIVE",
                actions=actions,
                details={
                    "reason": "AVOID_DUPLICATING_STRICT_RIZAN_DEPTH_EXPOSURE",
                    "current_signal_id": signal_id,
                    "geometry": geometry,
                },
            )
            return 0

        pending_current = any(
            _order_client_id(order) == signal_id
            for order in tuple(getattr(reconcile, "order", ()) or ())
        )
        if pending_current:
            _heartbeat(
                store,
                healthy=True,
                state="PROBE_PENDING_ACTIVE",
                actions=actions,
                details={
                    "reason": "CURRENT_STRUCTURAL_PROBE_PENDING_ALREADY_EXISTS",
                    "signal_id": signal_id,
                    "geometry": geometry,
                },
            )
            return 0

        if signal_id in prior:
            _heartbeat(
                store,
                healthy=True,
                state="ALREADY_SAMPLED",
                actions=actions,
                details={
                    "reason": "ONE_PROBE_PER_STRUCTURAL_CANDIDATE",
                    "signal_id": signal_id,
                    "geometry": geometry,
                },
            )
            return 0

        _write_signal(
            store,
            signal_id=signal_id,
            geometry=geometry,
            now=now,
        )

        side = (
            OrderSide.BUY
            if str(geometry["direction"]) == "LONG"
            else OrderSide.SELL
        )
        intent = OrderIntent(
            signal_id=signal_id,
            symbol=SYMBOL,
            side=side,
            order_type=OrderType.LIMIT,
            created_at=now,
            volume=LOT,
            entry_price=float(geometry["entry"]),
            stop_loss=float(geometry["sl"]),
            take_profit=float(geometry["tp"]),
            risk_pct=1.0,
            comment="DEMO_AUTO:RIZAN_STRUCT_PROBE_V318",
        )
        control.refresh_once()
        receipt = router.execute(intent)
        accepted = bool(receipt.accepted)
        _record_event(
            store,
            session,
            signal_id=signal_id,
            event_type=ORDER_EVENT_TYPE,
            code=ORDER_EVENT_CODE,
            message=(
                f"ACCEPTED:{receipt.message}"
                if accepted
                else f"REJECTED:{receipt.message}"
            ),
            accepted=accepted,
            broker_order_id=receipt.broker_order_id,
            payload={
                **geometry,
                "lot": LOT,
                "risk_context": risk_context,
                "dashboard_bridge_state_ignored_for_execution": True,
                "strict_confirmation_chain_bypassed_for_demo_research": True,
            },
        )
        _update_signal_state(
            store,
            signal_id,
            state="COOLDOWN" if accepted else "INVALIDATED",
            guards=[] if accepted else ["STRUCTURAL_RESEARCH_ORDER_REJECTED"],
        )
        actions.append(
            f"{signal_id}:"
            + ("ORDER_ACCEPTED" if accepted else "ORDER_REJECTED")
        )
        _heartbeat(
            store,
            healthy=True,
            state="ORDER_ACCEPTED" if accepted else "ORDER_REJECTED",
            actions=actions,
            details={
                "reason": geometry_reason,
                "signal_id": signal_id,
                "broker_order_id": receipt.broker_order_id,
                "accepted": accepted,
                "geometry": geometry,
                "risk_context": risk_context,
            },
        )
        return 0
    except Exception as exc:
        error = f"{type(exc).__name__}:{exc}"
        try:
            _heartbeat(
                store,
                healthy=False,
                state="ERROR",
                actions=actions,
                details={"reason": error},
            )
        except Exception:
            pass
        return 2
    finally:
        try:
            if "control" in locals() and hasattr(control, "stop"):
                control.stop()
        except Exception:
            pass
        try:
            if "gateway" in locals() and hasattr(gateway, "close"):
                gateway.close()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(run())

from __future__ import annotations

import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from math import isfinite
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from .demo_xau_v229_child_executor import (
    _calibration_probe_entry,
    _entry_inside_active_source,
    _limit_side_valid,
)
from .execution.control_plane import ControlPlaneGate, ControlPlaneRefreshWorker
from .execution.demo_autotrade import SupabaseOrderAuditSink
from .execution.factory import build_broker_gateway
from .execution.models import ExecutionMode, OrderIntent, OrderSide, OrderType
from .execution.policy import load_execution_policy
from .execution.router import ExecutionRouter
from .storage.supabase_operational import SupabaseOperationalStore
from .xau_dynamic_depth_hazard_v251 import child_reference_depth


SYMBOL = "XAUUSD"
WORKER_NAME = "ctrader_demo_xau_meta_research_sampler_v297"
META_WORKER = "ctrader_demo_xau_decision_center_v296"
ATLAS_WORKER = "ctrader_demo_xau_supply_demand_atlas_v182"
V226_WORKER = "ctrader_demo_xau_v226_rizan_depth_map"
CHILD_WORKER = "ctrader_demo_xau_v229_child_executor"

FEATURE_ENV = "CTRADER_DEMO_XAU_META_RESEARCH_SAMPLER_ENABLED"
SETUP_TYPE = "RIZAN_META_RESEARCH_V297"
ORDER_EVENT_TYPE = "DEMO_XAU_META_RESEARCH_ORDER"
ORDER_EVENT_CODE = "XAU_META_RESEARCH_ORDER_V297_1"
CANCEL_EVENT_TYPE = "DEMO_XAU_META_RESEARCH_CANCEL"
CANCEL_EVENT_CODE = "XAU_META_RESEARCH_CANCEL_V297_1"

LOT = 0.01
MIN_RR = 1.0
MAX_DEPTH = 0.85
MAX_META_AGE_SECONDS = 180.0


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


def meta_signal_id(decision_signature: str) -> str:
    signature = str(decision_signature or "").strip()
    if not signature:
        raise ValueError("decision_signature is required")
    return str(uuid5(NAMESPACE_URL, f"rizan-meta-research:{signature}"))


def _latest_heartbeat(
    store: SupabaseOperationalStore,
    worker_name: str,
) -> dict[str, Any] | None:
    response = (
        store.client.table("runtime_heartbeats")
        .select("worker_name,observed_at,healthy,details")
        .eq("worker_name", worker_name)
        .limit(1)
        .execute()
    )
    rows = [dict(row or {}) for row in (response.data or [])]
    return rows[0] if rows else None


def _recent_meta_signals(
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


def _order_client_id(order: Any) -> str:
    return str(getattr(order, "clientOrderId", "") or "").strip()


def _position_comment(position: Any) -> str:
    trade = getattr(position, "tradeData", None)
    return str(
        getattr(trade, "comment", "")
        or getattr(position, "comment", "")
        or ""
    ).strip()


def _meta_position_signal_id(position: Any, known: set[str]) -> str | None:
    comment = _position_comment(position)
    for signal_id in known:
        if comment.endswith(signal_id):
            return signal_id
    return None


def _decision_state(
    meta_hb: dict[str, Any] | None,
    *,
    now: datetime,
) -> tuple[dict[str, Any], str]:
    if not meta_hb or not bool(meta_hb.get("healthy")):
        return {}, "META_HEARTBEAT_UNAVAILABLE"
    observed = _dt(meta_hb.get("observed_at"))
    if observed is None:
        return {}, "META_OBSERVED_AT_INVALID"
    age = max(0.0, (now - observed).total_seconds())
    if age > MAX_META_AGE_SECONDS:
        return {}, f"META_STALE:{age:.1f}s"
    decision = dict(dict(meta_hb.get("details") or {}).get("decision") or {})
    if not decision:
        return {}, "META_DECISION_EMPTY"
    return decision, "OK"


def _research_eligible(decision: dict[str, Any]) -> tuple[bool, str]:
    if str(decision.get("action") or "") != "DEMO_RESEARCH_PROBE_ELIGIBLE":
        return False, f"META_ACTION:{decision.get('action') or 'WAIT'}"
    direction = str(decision.get("consensus_direction") or "").upper()
    if direction not in {"LONG", "SHORT"}:
        return False, "META_DIRECTION_WAIT"
    geometry = dict(decision.get("geometry") or {})
    if str(geometry.get("engine") or "") != "RIZAN_DEPTH":
        return False, "META_GEOMETRY_NOT_RIZAN_DEPTH"
    if str(geometry.get("direction") or "").upper() != direction:
        return False, "META_GEOMETRY_DIRECTION_MISMATCH"
    if str(geometry.get("state") or "").upper() not in {"ARMED", "EXECUTION_READY"}:
        return False, "META_GEOMETRY_STATE_NOT_RESEARCH_READY"
    if list(decision.get("hard_blocks") or []):
        return False, "META_HARD_BLOCK_PRESENT"
    if not bool(decision.get("research_probe_eligible")):
        return False, "META_RESEARCH_FLAG_FALSE"
    return True, "META_RESEARCH_ELIGIBLE"


def _actual_micro_entry(
    *,
    direction: str,
    geometry: dict[str, Any],
    atlas_eval: dict[str, Any],
    v226_eval: dict[str, Any],
    child_details: dict[str, Any],
    bid: float,
    ask: float,
) -> tuple[float | None, float | None, str]:
    micro = dict(
        atlas_eval.get("micro_refinement")
        or dict(atlas_eval.get("path_map") or {}).get("micro_refinement")
        or {}
    )
    entry, activation = _calibration_probe_entry(
        direction=direction,
        micro=micro,
    )
    if entry is None:
        return None, None, activation

    low = _f(geometry.get("entry_low"))
    high = _f(geometry.get("entry_high"))
    if low is None or high is None or high <= low:
        return None, None, "META_GEOMETRY_ENTRY_RANGE_INVALID"
    if not (float(low) <= float(entry) <= float(high)):
        return None, None, "META_M5_ENTRY_OUTSIDE_CANONICAL_RANGE"
    if not _entry_inside_active_source(
        direction=direction,
        entry=float(entry),
        atlas_evaluation=atlas_eval,
    ):
        return None, None, "META_M5_ENTRY_OUTSIDE_ACTIVE_SOURCE"
    if not _limit_side_valid(direction, float(entry), bid=float(bid), ask=float(ask)):
        return None, None, "META_LIMIT_SIDE_INVALID"

    depth = child_reference_depth(
        v226_evaluation=v226_eval,
        direction=direction,
        price=float(entry),
    )
    if depth is None:
        return None, None, "META_ENTRY_DEPTH_UNAVAILABLE"

    hazard = dict(child_details.get("dynamic_depth_hazard") or {})
    pressure = dict(child_details.get("pressure_transition") or {})
    reversal = dict(child_details.get("reversal_stage") or {})

    if bool(pressure.get("hard_block")) or not bool(
        pressure.get("calibration_entry_allowed")
    ):
        return None, depth, "META_PRESSURE_BLOCK"
    if bool(reversal.get("hard_execution_block")) or bool(
        reversal.get("setup_invalid")
    ):
        return None, depth, "META_V280_BLOCK"

    min_depth = _f(hazard.get("recommended_depth_low"))
    recommended_high = _f(hazard.get("recommended_depth_high"))
    max_depth = MAX_DEPTH
    if recommended_high is not None:
        max_depth = min(max_depth, float(recommended_high) + 0.10)
    if min_depth is not None and float(depth) + 1e-9 < float(min_depth):
        return None, depth, "META_WAIT_DEEPER"
    if float(depth) > float(max_depth) + 1e-9:
        return None, depth, "META_NO_CHASE_DEPTH"

    return float(entry), float(depth), activation


def _target_for_rr(
    *,
    direction: str,
    entry: float,
    stop: float,
    geometry: dict[str, Any],
    minimum_rr: float = MIN_RR,
) -> tuple[float | None, float | None]:
    risk = (
        float(entry) - float(stop)
        if direction == "LONG"
        else float(stop) - float(entry)
    )
    if risk <= 0:
        return None, None
    for key in ("tp2", "tp1"):
        target = _f(geometry.get(key))
        if target is None:
            continue
        reward = (
            float(target) - float(entry)
            if direction == "LONG"
            else float(entry) - float(target)
        )
        rr = reward / risk
        if reward > 0 and rr + 1e-9 >= float(minimum_rr):
            return float(target), float(rr)
    return None, None


def _write_signal(
    store: SupabaseOperationalStore,
    *,
    signal_id: str,
    decision: dict[str, Any],
    direction: str,
    entry: float,
    stop: float,
    target: float,
    rr: float,
    now: datetime,
) -> None:
    geometry = dict(decision.get("geometry") or {})
    coverage = _f(decision.get("coverage"))
    confidence = _f(decision.get("confidence"))
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
                "pair_score": confidence,
                "execution_score": confidence,
                "final_score": confidence,
                "entry_low": float(entry),
                "entry_high": float(entry),
                "sl": float(stop),
                "tp1": float(target),
                "tp2": float(target),
                "tp3": None,
                "rr1": float(rr),
                "rr2": float(rr),
                "rr3": None,
                "macro_bias": str(decision.get("consensus_direction") or ""),
                "h4_bias": str(geometry.get("direction") or ""),
                "h1_bias": str(geometry.get("direction") or ""),
                "active_guards": ["DEMO_META_RESEARCH_ONLY"],
                "data_coverage": max(0.0, min(1.0, float(coverage or 0.0))),
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
    store.client.table("signals").update(
        {"state": str(state), "active_guards": list(guards)}
    ).eq("id", signal_id).execute()


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


def _cancel_stale_meta_pending(
    *,
    store: SupabaseOperationalStore,
    session: Any,
    reconcile: Any,
    known_meta_ids: set[str],
    keep_signal_id: str | None,
) -> tuple[list[str], bool]:
    actions: list[str] = []
    cancelled_ids: list[int] = []
    safe = True
    for order in tuple(getattr(reconcile, "order", ()) or ()):
        client_id = _order_client_id(order)
        if client_id not in known_meta_ids:
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
        broker_ack = execution_type == 5
        if broker_ack:
            cancelled_ids.append(order_id)
            actions.append(f"{client_id}:CANCEL_ACK:{order_id}")
        else:
            safe = False
            actions.append(f"{client_id}:CANCEL_REJECTED:{order_id}:{execution_type}")

    if not cancelled_ids:
        return actions, safe

    try:
        after = session.reconcile()
        remaining = {
            int(getattr(order, "orderId", 0) or 0)
            for order in tuple(getattr(after, "order", ()) or ())
            if int(getattr(order, "orderId", 0) or 0) > 0
        }
    except Exception as exc:
        remaining = set(cancelled_ids)
        safe = False
        actions.append(f"CANCEL_RECONCILE_EXCEPTION:{type(exc).__name__}")

    for order_id in cancelled_ids:
        absent = order_id not in remaining
        if not absent:
            safe = False
        client_id = ""
        for order in tuple(getattr(reconcile, "order", ()) or ()):
            if int(getattr(order, "orderId", 0) or 0) == order_id:
                client_id = _order_client_id(order)
                break
        if client_id:
            try:
                _record_event(
                    store,
                    session,
                    signal_id=client_id,
                    event_type=CANCEL_EVENT_TYPE,
                    code=CANCEL_EVENT_CODE,
                    message=(
                        "CANCEL_ACK_RECONCILED_ABSENT"
                        if absent
                        else "CANCEL_ACK_STILL_PENDING"
                    ),
                    accepted=True,
                    broker_order_id=str(order_id),
                    payload={
                        "cancel_reason": "META_DECISION_CHANGED_OR_BLOCKED",
                        "reconciled_absent": absent,
                    },
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
            "max_depth": MAX_DEPTH,
            "one_meta_position_or_pending_max": True,
            "execution_influence": "DEMO_RESEARCH_ONLY",
            "code_version": os.getenv("GITHUB_SHA", "LOCAL"),
            **details,
        },
    )


def run() -> int:
    base_policy = load_execution_policy(None)
    if str(base_policy.ctrader.get("environment") or "").upper() != "DEMO":
        raise SystemExit("XAU_META_RESEARCH_SAMPLER_DEMO_ONLY")
    if not bool(base_policy.ctrader.get("require_demo", False)):
        raise SystemExit("XAU_META_RESEARCH_SAMPLER_REQUIRE_DEMO")

    store = SupabaseOperationalStore.from_env(execution_ready_score_floor=65.0)
    enabled = os.getenv(FEATURE_ENV, "0").strip() == "1"
    if not enabled:
        _heartbeat(
            store,
            healthy=True,
            state="DISABLED",
            actions=[],
            details={"reason": "META_RESEARCH_SAMPLER_DISABLED"},
        )
        return 0

    now = datetime.now(tz=UTC)
    meta_hb = _latest_heartbeat(store, META_WORKER)
    decision, decision_reason = _decision_state(meta_hb, now=now)
    eligible, eligibility_reason = _research_eligible(decision)
    signature = str(decision.get("decision_signature") or "")
    current_signal_id = meta_signal_id(signature) if eligible and signature else None

    policy = replace(base_policy, mode=ExecutionMode.AUTO)
    gateway, session = build_broker_gateway(policy, (SYMBOL,), backend="CTRADER")
    gate = ControlPlaneGate(
        max_age_seconds=float(
            policy.live_safety.get("control_state_max_age_seconds", 5)
        )
    )
    control_store = SupabaseOperationalStore.from_env(
        execution_ready_score_floor=65.0
    )
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
        control.refresh_once()
        control.start()

        meta_signals = _recent_meta_signals(store)
        known_meta_ids = set(meta_signals)
        if current_signal_id:
            known_meta_ids.add(current_signal_id)

        reconcile = session.reconcile()
        cancel_actions, cancel_safe = _cancel_stale_meta_pending(
            store=store,
            session=session,
            reconcile=reconcile,
            known_meta_ids=known_meta_ids,
            keep_signal_id=current_signal_id if eligible else None,
        )
        actions.extend(cancel_actions)
        if not cancel_safe:
            _heartbeat(
                store,
                healthy=False,
                state="CANCEL_RECONCILE_BLOCK",
                actions=actions,
                details={
                    "reason": "META_STALE_PENDING_NOT_SAFELY_CANCELLED",
                    "decision_reason": decision_reason,
                    "eligibility_reason": eligibility_reason,
                },
            )
            return 2

        reconcile = session.reconcile()
        pending_current = any(
            current_signal_id
            and _order_client_id(order) == current_signal_id
            for order in tuple(getattr(reconcile, "order", ()) or ())
        )
        open_meta = [
            signal_id
            for position in tuple(getattr(reconcile, "position", ()) or ())
            for signal_id in [_meta_position_signal_id(position, known_meta_ids)]
            if signal_id
        ]
        if open_meta:
            _heartbeat(
                store,
                healthy=True,
                state="META_POSITION_OPEN",
                actions=actions,
                details={
                    "reason": "ONE_META_POSITION_MAX",
                    "open_meta_signal_ids": open_meta,
                    "decision_reason": decision_reason,
                    "eligibility_reason": eligibility_reason,
                },
            )
            return 0
        if pending_current:
            _heartbeat(
                store,
                healthy=True,
                state="META_PENDING_ACTIVE",
                actions=actions,
                details={
                    "reason": "CURRENT_META_PENDING_ALREADY_EXISTS",
                    "signal_id": current_signal_id,
                    "decision_signature": signature,
                },
            )
            return 0

        if not eligible or not current_signal_id:
            _heartbeat(
                store,
                healthy=True,
                state="WAIT",
                actions=actions,
                details={
                    "reason": eligibility_reason,
                    "decision_reason": decision_reason,
                    "decision_signature": signature or None,
                },
            )
            return 0

        if current_signal_id in meta_signals:
            _heartbeat(
                store,
                healthy=True,
                state="ALREADY_SAMPLED",
                actions=actions,
                details={
                    "reason": "ONE_ORDER_PER_DECISION_SIGNATURE",
                    "signal_id": current_signal_id,
                    "decision_signature": signature,
                },
            )
            return 0

        atlas_hb = _latest_heartbeat(store, ATLAS_WORKER)
        v226_hb = _latest_heartbeat(store, V226_WORKER)
        child_hb = _latest_heartbeat(store, CHILD_WORKER)
        if not atlas_hb or not v226_hb or not child_hb:
            _heartbeat(
                store,
                healthy=True,
                state="WAIT",
                actions=actions,
                details={"reason": "META_SUPPORT_HEARTBEAT_MISSING"},
            )
            return 0

        atlas_eval = dict(dict(atlas_hb.get("details") or {}).get("evaluation") or {})
        v226_eval = dict(dict(v226_hb.get("details") or {}).get("evaluation") or {})
        child_details = dict(child_hb.get("details") or {})
        geometry = dict(decision.get("geometry") or {})
        direction = str(decision.get("consensus_direction") or "").upper()

        quote = gateway.market_quote(SYMBOL)
        entry, depth, activation = _actual_micro_entry(
            direction=direction,
            geometry=geometry,
            atlas_eval=atlas_eval,
            v226_eval=v226_eval,
            child_details=child_details,
            bid=float(quote.bid),
            ask=float(quote.ask),
        )
        if entry is None:
            _heartbeat(
                store,
                healthy=True,
                state="WAIT",
                actions=actions,
                details={
                    "reason": activation,
                    "decision_signature": signature,
                    "candidate_depth": depth,
                },
            )
            return 0

        stop = _f(geometry.get("sl"))
        if stop is None:
            _heartbeat(
                store,
                healthy=True,
                state="WAIT",
                actions=actions,
                details={"reason": "META_STOP_UNAVAILABLE"},
            )
            return 0
        target, rr = _target_for_rr(
            direction=direction,
            entry=float(entry),
            stop=float(stop),
            geometry=geometry,
            minimum_rr=MIN_RR,
        )
        if target is None or rr is None:
            _heartbeat(
                store,
                healthy=True,
                state="WAIT",
                actions=actions,
                details={"reason": "META_RR_BELOW_1R", "entry": entry, "sl": stop},
            )
            return 0

        _write_signal(
            store,
            signal_id=current_signal_id,
            decision=decision,
            direction=direction,
            entry=float(entry),
            stop=float(stop),
            target=float(target),
            rr=float(rr),
            now=now,
        )

        side = OrderSide.BUY if direction == "LONG" else OrderSide.SELL
        intent = OrderIntent(
            signal_id=current_signal_id,
            symbol=SYMBOL,
            side=side,
            order_type=OrderType.LIMIT,
            created_at=now,
            volume=LOT,
            entry_price=float(entry),
            stop_loss=float(stop),
            take_profit=float(target),
            risk_pct=1.0,
            comment="DEMO_AUTO:RIZAN_META_RESEARCH_V297",
        )
        control.refresh_once()
        receipt = router.execute(intent)
        accepted = bool(receipt.accepted)
        _record_event(
            store,
            session,
            signal_id=current_signal_id,
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
                "decision_signature": signature,
                "consensus_direction": direction,
                "meta_confidence": decision.get("confidence"),
                "meta_agreement": decision.get("agreement"),
                "entry": entry,
                "depth": depth,
                "activation": activation,
                "sl": stop,
                "tp": target,
                "rr": rr,
                "lot": LOT,
                "geometry_engine": geometry.get("engine"),
                "geometry_signal_id": geometry.get("signal_id"),
            },
        )
        _update_signal_state(
            store,
            current_signal_id,
            state="COOLDOWN" if accepted else "INVALIDATED",
            guards=[] if accepted else ["META_RESEARCH_ORDER_REJECTED"],
        )
        actions.append(
            f"{current_signal_id}:"
            + ("ORDER_ACCEPTED" if accepted else "ORDER_REJECTED")
        )
        _heartbeat(
            store,
            healthy=True,
            state="ORDER_ACCEPTED" if accepted else "ORDER_REJECTED",
            actions=actions,
            details={
                "signal_id": current_signal_id,
                "decision_signature": signature,
                "broker_order_id": receipt.broker_order_id,
                "entry": entry,
                "depth": depth,
                "sl": stop,
                "tp": target,
                "rr": rr,
                "activation": activation,
                "accepted": accepted,
            },
        )
        return 0
    except Exception as exc:
        error = f"{type(exc).__name__}:{exc}"
        try:
            _heartbeat(
                store,
                healthy=False,
                state="ERROR_FAIL_CLOSED",
                actions=actions,
                details={
                    "reason": error,
                    "decision_reason": decision_reason,
                    "eligibility_reason": eligibility_reason,
                    "signal_id": current_signal_id,
                },
            )
        except Exception:
            pass
        return 2
    finally:
        try:
            control.stop(timeout=2.0)
        except Exception:
            pass
        try:
            session.close()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(run())

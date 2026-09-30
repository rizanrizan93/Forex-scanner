from __future__ import annotations

import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from math import isfinite
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from .demo_xau_v229_child_executor import _limit_side_valid
from .execution.control_plane import ControlPlaneGate, ControlPlaneRefreshWorker
from .execution.demo_autotrade import SupabaseOrderAuditSink
from .execution.factory import build_broker_gateway
from .execution.models import ExecutionMode, OrderIntent, OrderSide, OrderType
from .execution.policy import load_execution_policy
from .execution.router import ExecutionRouter
from .storage.supabase_operational import SupabaseOperationalStore
from .xau_decision_meta_v296 import calibrate_outcomes


SYMBOL = "XAUUSD"
WORKER_NAME = "ctrader_demo_xau_structural_control_sampler_v303"
ATLAS_WORKER = "ctrader_demo_xau_supply_demand_atlas_v182"
V226_WORKER = "ctrader_demo_xau_v226_rizan_depth_map"
EVENT_WORKER = "ctrader_demo_xau_event_risk_v192"

FEATURE_ENV = "CTRADER_DEMO_XAU_STRUCTURAL_CONTROL_SAMPLER_ENABLED"
SETUP_TYPE = "RIZAN_STRUCTURAL_CONTROL_V303"
META_SETUP_TYPE = "RIZAN_META_RESEARCH_V297"
ORDER_EVENT_TYPE = "DEMO_XAU_STRUCTURAL_CONTROL_ORDER"
ORDER_EVENT_CODE = "XAU_STRUCTURAL_CONTROL_ORDER_V303_1"
CANCEL_EVENT_TYPE = "DEMO_XAU_STRUCTURAL_CONTROL_CANCEL"
CANCEL_EVENT_CODE = "XAU_STRUCTURAL_CONTROL_CANCEL_V303_1"

LOT = 0.01
MIN_RR = 1.0
MAX_SOURCE_AGE_SECONDS = 180.0
SIGNAL_TTL = timedelta(hours=4)


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


def _heartbeat_age_seconds(row: dict[str, Any] | None, now: datetime) -> float | None:
    if not row:
        return None
    observed = _dt(row.get("observed_at"))
    if observed is None:
        return None
    return max(0.0, (now - observed).total_seconds())


def control_signal_id(signature: str) -> str:
    token = str(signature or "").strip()
    if not token:
        raise ValueError("control signature is required")
    return str(uuid5(NAMESPACE_URL, f"rizan-structural-control-v303:{token}"))


def _build_control_geometry(
    *,
    atlas_heartbeat: dict[str, Any] | None,
    v226_heartbeat: dict[str, Any] | None,
    now: datetime,
) -> tuple[dict[str, Any], str]:
    if not atlas_heartbeat or not bool(atlas_heartbeat.get("healthy")):
        return {}, "ATLAS_UNAVAILABLE"
    if not v226_heartbeat or not bool(v226_heartbeat.get("healthy")):
        return {}, "V226_UNAVAILABLE"

    atlas_age = _heartbeat_age_seconds(atlas_heartbeat, now)
    v226_age = _heartbeat_age_seconds(v226_heartbeat, now)
    if atlas_age is None or atlas_age > MAX_SOURCE_AGE_SECONDS:
        return {}, "ATLAS_STALE"
    if v226_age is None or v226_age > MAX_SOURCE_AGE_SECONDS:
        return {}, "V226_STALE"

    atlas_eval = dict(dict(atlas_heartbeat.get("details") or {}).get("evaluation") or {})
    v226_eval = dict(dict(v226_heartbeat.get("details") or {}).get("evaluation") or {})
    path = dict(dict(atlas_eval.get("path_map") or {}).get("active_path") or {})
    candidate = dict(v226_eval.get("depth_entry_candidate") or {})
    if not path:
        return {}, "NO_ACTIVE_ATLAS_PATH"
    if not candidate:
        return {}, "NO_V226_DEPTH_CANDIDATE"

    direction = str(candidate.get("direction") or "").upper()
    path_direction = str(path.get("reaction_direction") or "").upper()
    if direction not in {"LONG", "SHORT"}:
        return {}, "CANDIDATE_DIRECTION_INVALID"
    if path_direction != direction:
        return {}, "ATLAS_V226_DIRECTION_MISMATCH"

    # This sampler is a control cohort for geometry that has not earned execution
    # authority. If V226 is already executable, the strict/meta lanes own it.
    if bool(candidate.get("execution_authority")) or bool(candidate.get("execution_influence")):
        return {}, "CANDIDATE_ALREADY_AUTHORITATIVE"
    if bool(candidate.get("pre_touch_execution_eligible")) or bool(
        candidate.get("confirmation_execution_eligible")
    ):
        return {}, "CANDIDATE_OWNED_BY_STRICT_LANE"

    source = dict(path.get("source_zone") or {})
    lifecycle = dict(source.get("lifecycle") or {})
    if not source or not bool(lifecycle.get("active")) or lifecycle.get("invalidated_at"):
        return {}, "SOURCE_ZONE_NOT_ACTIVE"
    if str(source.get("direction") or "").upper() != direction:
        return {}, "SOURCE_ZONE_DIRECTION_MISMATCH"

    low = _f(source.get("low"))
    high = _f(source.get("high"))
    distal = _f(source.get("distal"))
    entry = _f(candidate.get("entry_reference"))
    reaction_target = dict(path.get("reaction_target") or {})
    target = _f(reaction_target.get("price"))
    if None in {low, high, distal, entry, target}:
        return {}, "STRUCTURAL_GEOMETRY_INCOMPLETE"
    assert low is not None and high is not None and distal is not None
    assert entry is not None and target is not None
    if not (low <= entry <= high):
        return {}, "ENTRY_OUTSIDE_SOURCE_ZONE"

    stop = float(distal)
    if direction == "LONG":
        if not (stop < entry < target):
            return {}, "LONG_GEOMETRY_INVALID"
        risk = entry - stop
        reward = target - entry
    else:
        if not (target < entry < stop):
            return {}, "SHORT_GEOMETRY_INVALID"
        risk = stop - entry
        reward = entry - target
    if risk <= 0.0 or reward <= 0.0:
        return {}, "NON_POSITIVE_RISK_REWARD"
    rr = reward / risk
    if rr + 1e-9 < MIN_RR:
        return {}, "STRUCTURAL_CONTROL_RR_BELOW_1R"

    source_zone_id = str(source.get("zone_id") or "")
    if not source_zone_id:
        return {}, "SOURCE_ZONE_ID_MISSING"
    signature = "|".join(
        [
            direction,
            source_zone_id,
            str(candidate.get("source_layer") or ""),
            f"{entry:.3f}",
            f"{stop:.3f}",
            f"{target:.3f}",
        ]
    )
    return {
        "signature": signature,
        "direction": direction,
        "entry": float(entry),
        "sl": float(stop),
        "tp": float(target),
        "rr": float(rr),
        "source_zone_id": source_zone_id,
        "source_timeframe": str(source.get("timeframe") or ""),
        "source_status": str(source.get("status") or ""),
        "source_research_score": _f(source.get("research_score")),
        "source_low": float(low),
        "source_high": float(high),
        "candidate_status": str(candidate.get("display_status") or ""),
        "candidate_source_layer": str(candidate.get("source_layer") or ""),
        "path_state": str(path.get("state") or ""),
        "target_source": str(reaction_target.get("source") or ""),
        "atlas_age_seconds": float(atlas_age),
        "v226_age_seconds": float(v226_age),
        "execution_authority": False,
        "execution_influence": "DEMO_RESEARCH_CONTROL_ONLY",
    }, "CONTROL_GEOMETRY_READY"


def _recent_research_signals(
    store: SupabaseOperationalStore,
) -> dict[str, dict[str, Any]]:
    response = (
        store.client.table("signals")
        .select("id,setup_type,state,observed_at,expires_at")
        .eq("symbol", SYMBOL)
        .in_("setup_type", [SETUP_TYPE, META_SETUP_TYPE])
        .order("observed_at", desc=True)
        .limit(128)
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


def _research_position_signal_id(position: Any, known: set[str]) -> str | None:
    comment = _position_comment(position)
    for signal_id in known:
        if comment.endswith(signal_id):
            return signal_id
    return None


def _write_signal(
    store: SupabaseOperationalStore,
    *,
    signal_id: str,
    geometry: dict[str, Any],
    now: datetime,
) -> None:
    direction = str(geometry["direction"])
    score = _f(geometry.get("source_research_score")) or 0.0
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
                "pair_score": score,
                "execution_score": score,
                "final_score": score,
                "entry_low": float(geometry["entry"]),
                "entry_high": float(geometry["entry"]),
                "sl": float(geometry["sl"]),
                "tp1": float(geometry["tp"]),
                "tp2": float(geometry["tp"]),
                "tp3": None,
                "rr1": float(geometry["rr"]),
                "rr2": float(geometry["rr"]),
                "rr3": None,
                "macro_bias": direction,
                "h4_bias": direction,
                "h1_bias": direction,
                "active_guards": ["DEMO_STRUCTURAL_CONTROL_ONLY"],
                "data_coverage": 1.0,
                "expires_at": (now + SIGNAL_TTL).isoformat(),
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
        payload={"environment": "DEMO", "strategy_id": SETUP_TYPE, **payload},
    )


def _cancel_stale_control_pending(
    *,
    store: SupabaseOperationalStore,
    session: Any,
    reconcile: Any,
    control_ids: set[str],
    keep_signal_id: str | None,
) -> tuple[list[str], bool]:
    actions: list[str] = []
    cancelled: list[int] = []
    safe = True
    for order in tuple(getattr(reconcile, "order", ()) or ()):
        client_id = _order_client_id(order)
        if client_id not in control_ids:
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
        actions.append(
            f"{client_id}:"
            + (f"CANCEL_ACK:{order_id}" if broker_ack else f"CANCEL_REJECTED:{order_id}:{execution_type}")
        )
        if broker_ack:
            cancelled.append(order_id)
        else:
            safe = False

    pending_after: set[int] | None = None
    reconcile_error: str | None = None
    if cancelled:
        try:
            after = session.reconcile()
            pending_after = {
                int(getattr(order, "orderId", 0) or 0)
                for order in tuple(getattr(after, "order", ()) or ())
                if int(getattr(order, "orderId", 0) or 0) > 0
            }
        except Exception as exc:
            reconcile_error = f"{type(exc).__name__}:{exc}"
            safe = False

    for order_id in cancelled:
        reconciled_absent = (
            None if pending_after is None else order_id not in pending_after
        )
        if reconciled_absent is not True:
            safe = False
        try:
            _record_event(
                store,
                session,
                signal_id=next(
                    (
                        cid
                        for cid in control_ids
                        if any(
                            int(getattr(order, "orderId", 0) or 0) == order_id
                            and _order_client_id(order) == cid
                            for order in tuple(getattr(reconcile, "order", ()) or ())
                        )
                    ),
                    "UNKNOWN_CONTROL_SIGNAL",
                ),
                event_type=CANCEL_EVENT_TYPE,
                code=CANCEL_EVENT_CODE,
                message=(
                    "CANCEL_ACK_RECONCILED_ABSENT"
                    if reconciled_absent is True
                    else "CANCEL_ACK_RECONCILE_UNCERTAIN"
                ),
                accepted=True,
                broker_order_id=str(order_id),
                payload={
                    "cancel_reason": "CONTROL_SIGNATURE_SUPERSEDED",
                    "broker_cancel_ack": True,
                    "reconciled_absent": reconciled_absent,
                    "reconcile_error": reconcile_error,
                },
            )
        except Exception:
            actions.append(f"CANCEL_AUDIT_WRITE_FAILED:{order_id}")
    return actions, safe


def _control_calibration(
    store: SupabaseOperationalStore,
) -> dict[str, Any]:
    try:
        response = (
            store.client.table("xau_outcome_ledger")
            .select(
                "order_accepted_at,outcome_class,tp1_hit,stop_hit,mfe_r,mae_r"
            )
            .eq("strategy_id", SETUP_TYPE)
            .order("observed_at", desc=True)
            .limit(500)
            .execute()
        )
        rows = [dict(row or {}) for row in (response.data or [])]
    except Exception as exc:
        return {
            "state": "LEDGER_UNAVAILABLE",
            "accepted_orders": 0,
            "decisive": 0,
            "win_rate": None,
            "wilson_lower_95": None,
            "error": f"{type(exc).__name__}:{exc}",
        }

    calibrated = calibrate_outcomes(rows)
    return {
        **calibrated,
        "accepted_orders": sum(
            1 for row in rows if row.get("order_accepted_at") is not None
        ),
        "ledger_rows": len(rows),
        "basis": "EXECUTED_DEMO_CONTROL_OUTCOMES",
        "execution_influence": False,
    }


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
            "one_research_position_or_pending_max": True,
            "setup_type": SETUP_TYPE,
            "control_calibration": _control_calibration(store),
            "execution_influence": "DEMO_RESEARCH_CONTROL_ONLY",
            "code_version": os.getenv("GITHUB_SHA", "LOCAL"),
            **details,
        },
    )


def run() -> int:
    base_policy = load_execution_policy(None)
    if str(base_policy.ctrader.get("environment") or "").upper() != "DEMO":
        raise SystemExit("XAU_STRUCTURAL_CONTROL_SAMPLER_DEMO_ONLY")
    if not bool(base_policy.ctrader.get("require_demo", False)):
        raise SystemExit("XAU_STRUCTURAL_CONTROL_SAMPLER_REQUIRE_DEMO")

    store = SupabaseOperationalStore.from_env(execution_ready_score_floor=65.0)
    enabled = os.getenv(FEATURE_ENV, "0").strip() == "1"
    if not enabled:
        _heartbeat(
            store,
            healthy=True,
            state="DISABLED",
            actions=[],
            details={"reason": "STRUCTURAL_CONTROL_SAMPLER_DISABLED"},
        )
        return 0

    now = datetime.now(tz=UTC)
    atlas_hb = _latest_heartbeat(store, ATLAS_WORKER)
    v226_hb = _latest_heartbeat(store, V226_WORKER)
    geometry, geometry_reason = _build_control_geometry(
        atlas_heartbeat=atlas_hb,
        v226_heartbeat=v226_hb,
        now=now,
    )
    signature = str(geometry.get("signature") or "")
    current_signal_id = control_signal_id(signature) if signature else None

    event_hb = _latest_heartbeat(store, EVENT_WORKER)
    event_risk = (
        {}
        if not event_hb
        else dict(dict(event_hb.get("details") or {}).get("risk") or {})
    )
    event_state = str(event_risk.get("state") or "UNAVAILABLE").upper()
    if event_state in {"PRE_EVENT", "EVENT_WINDOW"}:
        geometry = {}
        geometry_reason = f"EVENT_RISK_{event_state}"
        current_signal_id = None

    policy = replace(base_policy, mode=ExecutionMode.AUTO)
    gateway, session = build_broker_gateway(policy, (SYMBOL,), backend="CTRADER")
    gate = ControlPlaneGate(
        max_age_seconds=float(policy.live_safety.get("control_state_max_age_seconds", 5))
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
    try:
        control.refresh_once()
        control.start()

        research_signals = _recent_research_signals(store)
        known_research_ids = set(research_signals)
        control_ids = {
            signal_id
            for signal_id, row in research_signals.items()
            if str(row.get("setup_type") or "") == SETUP_TYPE
        }
        if current_signal_id:
            known_research_ids.add(current_signal_id)
            control_ids.add(current_signal_id)

        reconcile = session.reconcile()
        cancel_actions, cancel_safe = _cancel_stale_control_pending(
            store=store,
            session=session,
            reconcile=reconcile,
            control_ids=control_ids,
            keep_signal_id=current_signal_id,
        )
        actions.extend(cancel_actions)
        if not cancel_safe:
            _heartbeat(
                store,
                healthy=False,
                state="CANCEL_RECONCILE_BLOCK",
                actions=actions,
                details={
                    "reason": "CONTROL_STALE_PENDING_NOT_SAFELY_CANCELLED",
                    "geometry_reason": geometry_reason,
                },
            )
            return 2

        reconcile = session.reconcile()
        open_research = [
            signal_id
            for position in tuple(getattr(reconcile, "position", ()) or ())
            for signal_id in [_research_position_signal_id(position, known_research_ids)]
            if signal_id
        ]
        pending_research = [
            _order_client_id(order)
            for order in tuple(getattr(reconcile, "order", ()) or ())
            if _order_client_id(order) in known_research_ids
        ]
        if open_research or pending_research:
            _heartbeat(
                store,
                healthy=True,
                state="WAIT_RESEARCH_EXPOSURE",
                actions=actions,
                details={
                    "reason": "ONE_RESEARCH_EXPOSURE_MAX",
                    "open_research_signal_ids": open_research,
                    "pending_research_signal_ids": pending_research,
                    "geometry_reason": geometry_reason,
                },
            )
            return 0

        if not geometry or not current_signal_id:
            _heartbeat(
                store,
                healthy=True,
                state="WAIT",
                actions=actions,
                details={
                    "reason": geometry_reason,
                    "event_risk_state": event_state,
                },
            )
            return 0

        if current_signal_id in research_signals:
            _heartbeat(
                store,
                healthy=True,
                state="ALREADY_SAMPLED",
                actions=actions,
                details={
                    "reason": "ONE_SAMPLE_PER_STRUCTURAL_SIGNATURE",
                    "signal_id": current_signal_id,
                    "geometry": geometry,
                },
            )
            return 0

        quote = gateway.market_quote(SYMBOL)
        direction = str(geometry["direction"])
        entry = float(geometry["entry"])
        if not _limit_side_valid(
            direction,
            entry,
            bid=float(quote.bid),
            ask=float(quote.ask),
        ):
            _heartbeat(
                store,
                healthy=True,
                state="WAIT_LIMIT_SIDE",
                actions=actions,
                details={
                    "reason": "STRUCTURAL_CONTROL_LIMIT_SIDE_INVALID",
                    "bid": float(quote.bid),
                    "ask": float(quote.ask),
                    "geometry": geometry,
                },
            )
            return 0

        _write_signal(
            store,
            signal_id=current_signal_id,
            geometry=geometry,
            now=now,
        )
        _record_event(
            store,
            session,
            signal_id=current_signal_id,
            event_type="DEMO_SIGNAL_GEOMETRY",
            code=SETUP_TYPE,
            message="V303 structural control geometry; DEMO research only",
            accepted=None,
            broker_order_id=None,
            payload={
                "entry_mode": "STRUCTURAL_CONTROL_LIMIT",
                "source_zone_id": geometry.get("source_zone_id"),
                "source_timeframe": geometry.get("source_timeframe"),
                "candidate_status": geometry.get("candidate_status"),
                "entry": entry,
                "sl": geometry.get("sl"),
                "tp": geometry.get("tp"),
                "rr": geometry.get("rr"),
            },
        )

        side = OrderSide.BUY if direction == "LONG" else OrderSide.SELL
        intent = OrderIntent(
            signal_id=current_signal_id,
            symbol=SYMBOL,
            side=side,
            order_type=OrderType.LIMIT,
            created_at=now,
            volume=LOT,
            entry_price=entry,
            stop_loss=float(geometry["sl"]),
            take_profit=float(geometry["tp"]),
            risk_pct=1.0,
            comment="DEMO_AUTO:RIZAN_STRUCTURAL_CONTROL_V303",
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
                **geometry,
                "bid": float(quote.bid),
                "ask": float(quote.ask),
                "lot": LOT,
                "event_risk_state": event_state,
            },
        )
        _update_signal_state(
            store,
            current_signal_id,
            state="COOLDOWN" if accepted else "INVALIDATED",
            guards=[] if accepted else ["STRUCTURAL_CONTROL_ORDER_REJECTED"],
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
                "reason": "STRUCTURAL_CONTROL_SAMPLE_SUBMITTED",
                "signal_id": current_signal_id,
                "broker_order_id": receipt.broker_order_id,
                "accepted": accepted,
                "geometry": geometry,
                "event_risk_state": event_state,
            },
        )
        return 0
    except Exception as exc:
        try:
            _heartbeat(
                store,
                healthy=False,
                state="ERROR_FAIL_CLOSED",
                actions=actions,
                details={
                    "reason": f"{type(exc).__name__}:{exc}",
                    "geometry_reason": geometry_reason,
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

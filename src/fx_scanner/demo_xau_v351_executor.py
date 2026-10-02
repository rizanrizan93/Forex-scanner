from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
import hashlib
import os
from math import isfinite
from typing import Any

from .execution.control_plane import ControlPlaneGate, ControlPlaneRefreshWorker
from .execution.demo_autotrade import SupabaseOrderAuditSink
from .execution.factory import build_broker_gateway
from .execution.models import ExecutionMode, OrderIntent, OrderSide, OrderType
from .execution.policy import load_execution_policy
from .execution.router import ExecutionRouter
from .storage.supabase_operational import SupabaseOperationalStore

SYMBOL = "XAUUSD"
SOURCE_WORKER = "ctrader_demo_xau_sd_liquidity_v342"
WORKER_NAME = "ctrader_demo_xau_v351_executor"
ENGINE_CONTRACT_PREFIX = "XAU_RIZAN_SD_LIQUIDITY_V342_"
EVENT_TYPE = "DEMO_XAU_V351_EXECUTION"
EXECUTION_SCOPE = "DEMO_ONLY"
LOT = 0.01
RISK_PCT = 1.0
MIN_RR = 1.50
MAX_SOURCE_AGE_SECONDS = 120.0
MAX_MARGIN_USAGE_FRACTION = 0.50
FRESH_CONFIRMATION_MAX_AGE_SECONDS = 420.0
FRESH_CONFIRMATION_MAX_DRIFT_ATR = 0.35
EARLY_CONFIRMATION_MAX_AGE_SECONDS = 300.0
EARLY_CONFIRMATION_MAX_DRIFT_ATR = 0.25


def _f(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if isfinite(out) else None


def _dt(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        out = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if out.tzinfo is None:
        return None
    return out.astimezone(UTC)


def _latest_source(store: SupabaseOperationalStore) -> dict[str, Any]:
    response = (
        store.client.table("runtime_heartbeats")
        .select("worker_name,observed_at,healthy,details")
        .eq("worker_name", SOURCE_WORKER)
        .order("observed_at", desc=True)
        .limit(1)
        .execute()
    )
    rows = list(response.data or [])
    return {} if not rows else dict(rows[0])


def _signal_id(evaluation: dict[str, Any]) -> str:
    parent = dict(evaluation.get("main_reversal_zone") or {})
    micro = dict(evaluation.get("micro_confirmation") or {})
    destination = dict(evaluation.get("structural_destination") or {})
    raw = "|".join(
        [
            str(parent.get("zone_id") or "NO_PARENT"),
            str(evaluation.get("expected_reversal_direction") or "WAIT"),
            str(micro.get("reclaim_at") or "NO_RECLAIM"),
            str(destination.get("zone_id") or "NO_DESTINATION"),
        ]
    )
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]
    return f"XAU_V351_{digest}"


def _already_accepted(store: SupabaseOperationalStore, signal_id: str) -> bool:
    response = (
        store.client.table("broker_order_events")
        .select("accepted,event_type")
        .eq("signal_key", signal_id)
        .eq("accepted", True)
        .limit(1)
        .execute()
    )
    return bool(response.data or [])


def _protected_positions_only(session: Any) -> tuple[bool, str]:
    reconcile = session.reconcile()
    for position in tuple(getattr(reconcile, "position", ())):
        position_id = int(getattr(position, "positionId", 0) or 0)
        stop_loss = _f(getattr(position, "stopLoss", None))
        take_profit = _f(getattr(position, "takeProfit", None))
        if stop_loss is None or stop_loss <= 0 or take_profit is None or take_profit <= 0:
            return False, f"UNPROTECTED_POSITION:{position_id or 'UNKNOWN'}"
    return True, "ALL_OPEN_POSITIONS_PROTECTED"


def _margin_room_ok(gateway: Any) -> tuple[bool, str, float | None]:
    account = gateway.account_snapshot()
    equity = _f(getattr(account, "equity", None))
    margin = _f(getattr(account, "margin", None))
    margin_free = _f(getattr(account, "margin_free", None))
    if equity is None or equity <= 0:
        return False, "ACCOUNT_EQUITY_UNAVAILABLE", None

    # cTrader's gateway snapshot exposes margin_free rather than a dedicated
    # margin field. Prefer explicit broker margin when present; otherwise derive
    # used margin from equity - margin_free. Missing both remains fail-closed.
    if margin is not None:
        used_margin = max(0.0, margin)
        margin_source = "EXPLICIT_MARGIN"
    elif margin_free is not None:
        used_margin = max(0.0, equity - margin_free)
        margin_source = "DERIVED_FROM_MARGIN_FREE"
    else:
        return False, "ACCOUNT_MARGIN_UNAVAILABLE", None

    usage = used_margin / equity
    if usage >= MAX_MARGIN_USAGE_FRACTION:
        return False, f"MARGIN_USAGE_AT_OR_ABOVE_50PCT:{margin_source}", usage
    return True, f"MARGIN_ROOM_OK:{margin_source}", usage


def _candidate(
    *,
    heartbeat: dict[str, Any],
    bid: float,
    ask: float,
    now: datetime,
) -> tuple[dict[str, Any] | None, str]:
    if not heartbeat or not bool(heartbeat.get("healthy")):
        return None, "SOURCE_HEARTBEAT_UNHEALTHY"

    observed_at = _dt(heartbeat.get("observed_at"))
    if observed_at is None:
        return None, "SOURCE_TIME_INVALID"
    age = (now - observed_at).total_seconds()
    if age < -1.0 or age > MAX_SOURCE_AGE_SECONDS:
        return None, f"SOURCE_STALE:{age:.1f}s"

    evaluation = dict(dict(heartbeat.get("details") or {}).get("evaluation") or {})
    contract = str(evaluation.get("contract") or "")
    if not contract.startswith(ENGINE_CONTRACT_PREFIX):
        return None, "ENGINE_CONTRACT_MISMATCH"
    if not bool(evaluation.get("execution_authority")):
        return None, "ENGINE_DEMO_EXECUTION_NOT_AUTHORIZED"
    if bool(evaluation.get("live_execution_enabled")):
        return None, "LIVE_EXECUTION_FLAG_FORBIDDEN"

    guide = dict(evaluation.get("entry_guide") or {})
    micro = dict(evaluation.get("micro_confirmation") or {})
    structural_room = dict(evaluation.get("structural_room") or {})
    roadblock_room = dict(evaluation.get("roadblock_room") or {})
    news = dict(evaluation.get("news_zone") or {})
    destination = dict(evaluation.get("structural_destination") or {})
    roadblock = dict(evaluation.get("nearest_roadblock") or {})

    guide_state = str(guide.get("state") or "")
    early_lane = guide_state == "EARLY_CONFIRMED_GUIDANCE"
    full_lane = guide_state == "CONFIRMED_GUIDANCE"
    if not (early_lane or full_lane):
        return None, f"ENTRY_GATE:{guide_state or 'WAIT'}"
    if full_lane and not bool(micro.get("confirmed")):
        return None, "MICRO_NOT_CONFIRMED"
    if early_lane and not bool(micro.get("early_confirmed")):
        return None, "MICRO_EARLY_CONFIRMATION_MISSING"
    if bool(structural_room.get("blocked")):
        return None, f"STRUCTURAL_ROOM_BLOCK:{structural_room.get('state') or 'BLOCK'}"
    if bool(roadblock_room.get("blocked")):
        return None, f"ROADBLOCK_ROOM_BLOCK:{roadblock_room.get('state') or 'BLOCK'}"
    effective_news = str(news.get("effective_entry_state") or guide_state or "")
    allowed_news_states = {"CONFIRMED_GUIDANCE", "EARLY_CONFIRMED_GUIDANCE"}
    if effective_news not in allowed_news_states:
        return None, f"NEWS_GATE:{effective_news or 'WAIT'}"
    if early_lane and effective_news != "EARLY_CONFIRMED_GUIDANCE":
        # Do not silently promote an early setup through a mismatched news state.
        return None, f"NEWS_GATE_TIER_MISMATCH:{effective_news or 'WAIT'}"

    direction = str(guide.get("direction") or evaluation.get("expected_reversal_direction") or "").upper()
    if direction not in {"LONG", "SHORT"}:
        return None, "DIRECTION_INVALID"

    entry_low = _f(guide.get("entry_low"))
    entry_high = _f(guide.get("entry_high"))
    stop_loss = _f(guide.get("invalidation"))
    if (
        entry_low is None
        or entry_high is None
        or stop_loss is None
        or entry_low <= 0
        or entry_high <= entry_low
        or stop_loss <= 0
    ):
        return None, "ENTRY_OR_STOP_GEOMETRY_INVALID"

    executable = float(ask if direction == "LONG" else bid)
    entry_mode = "RETEST_ENTRY" if entry_low <= executable <= entry_high else None
    confirmation_age_seconds = None
    confirmation_drift_atr = None

    if entry_mode is None:
        confirmation_at = _dt(micro.get("reclaim_at"))
        confirmation_close = _f(micro.get("confirmation_close"))
        local_atr = _f(micro.get("local_atr"))
        moving_with_setup = (
            direction == "LONG" and executable > entry_high
        ) or (
            direction == "SHORT" and executable < entry_low
        )
        if (
            confirmation_at is not None
            and confirmation_close is not None
            and local_atr is not None
            and local_atr > 0
            and moving_with_setup
        ):
            confirmation_age_seconds = (now - confirmation_at).total_seconds()
            confirmation_drift_atr = abs(executable - confirmation_close) / local_atr
            max_age = (
                EARLY_CONFIRMATION_MAX_AGE_SECONDS
                if early_lane
                else FRESH_CONFIRMATION_MAX_AGE_SECONDS
            )
            max_drift = (
                EARLY_CONFIRMATION_MAX_DRIFT_ATR
                if early_lane
                else FRESH_CONFIRMATION_MAX_DRIFT_ATR
            )
            if (
                -1.0 <= confirmation_age_seconds <= max_age
                and confirmation_drift_atr <= max_drift
            ):
                entry_mode = (
                    "EARLY_CONFIRMATION_DEMO_PROBE"
                    if early_lane
                    else "FRESH_CONFIRMATION_ENTRY"
                )

    if entry_mode is None:
        return None, "WAIT_ENTRY_RETEST_OR_FRESH_CONFIRMATION"

    target = None
    target_source = None
    rb_target = _f(roadblock.get("near_edge"))
    if rb_target is not None:
        target = rb_target
        target_source = "NEAREST_ROADBLOCK"
    else:
        target = _f(destination.get("price"))
        target_source = "H4_DESTINATION"
    if target is None or target <= 0:
        return None, "STRUCTURAL_TARGET_MISSING"

    if direction == "LONG":
        if not (stop_loss < executable < target):
            return None, "LONG_SLTP_GEOMETRY_INVALID"
        risk = executable - stop_loss
        reward = target - executable
    else:
        if not (target < executable < stop_loss):
            return None, "SHORT_SLTP_GEOMETRY_INVALID"
        risk = stop_loss - executable
        reward = executable - target
    if risk <= 0 or reward <= 0:
        return None, "RISK_REWARD_GEOMETRY_INVALID"

    rr = reward / risk
    if rr + 1e-9 < MIN_RR:
        return None, f"RR_BELOW_{MIN_RR:.2f}:{rr:.3f}"

    signal_id = _signal_id(evaluation)
    return {
        "signal_id": signal_id,
        "direction": direction,
        "entry": executable,
        "entry_mode": entry_mode,
        "confirmation_tier": "EARLY" if early_lane else "FULL",
        "entry_low": entry_low,
        "entry_high": entry_high,
        "confirmation_age_seconds": confirmation_age_seconds,
        "confirmation_drift_atr": confirmation_drift_atr,
        "stop_loss": stop_loss,
        "take_profit": target,
        "target_source": target_source,
        "rr": rr,
        "observed_at": observed_at,
        "parent_zone_id": dict(evaluation.get("main_reversal_zone") or {}).get("zone_id"),
        "destination_zone_id": destination.get("zone_id"),
        "reclaim_at": micro.get("reclaim_at"),
    }, "ELIGIBLE"


def _zone_audit(zone: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "zone_id",
        "timeframe",
        "hierarchy_role",
        "direction",
        "low",
        "high",
        "proximal",
        "distal",
        "condition",
        "pattern",
        "score",
        "parent_zone_id",
        "source",
        "lifecycle_state",
        "current_role",
        "status",
    )
    return {key: zone.get(key) for key in keys if zone.get(key) is not None}


def _evidence_ledger(
    heartbeat: dict[str, Any],
    candidate: dict[str, Any],
) -> dict[str, Any]:
    evaluation = dict(dict(heartbeat.get("details") or {}).get("evaluation") or {})
    parent = dict(evaluation.get("main_reversal_zone") or {})
    refinement = dict(evaluation.get("refinement_zone") or {})
    liquidity = dict(evaluation.get("liquidity_map") or {})
    roadblock = dict(evaluation.get("nearest_roadblock") or {})
    roadblock_room = dict(evaluation.get("roadblock_room") or {})
    structural_room = dict(evaluation.get("structural_room") or {})
    news = dict(evaluation.get("news_zone") or {})
    focal_event = dict(news.get("focal_event") or {})
    micro = dict(evaluation.get("micro_confirmation") or {})

    return {
        "schema": "XAU_RIZAN_DEMO_EVIDENCE_LEDGER_V354_1",
        "setup_observed_at": heartbeat.get("observed_at"),
        "engine_contract": evaluation.get("contract"),
        "execution_scope": EXECUTION_SCOPE,
        "direction": evaluation.get("expected_reversal_direction"),
        "parent_h4": _zone_audit(parent),
        "h1_refinement": _zone_audit(refinement),
        "liquidity": {
            "side": liquidity.get("side"),
            "low": liquidity.get("low"),
            "high": liquidity.get("high"),
            "warning": liquidity.get("warning"),
            "extension_atr": liquidity.get("extension_atr"),
            "sweep_seen": bool(micro.get("sweep_seen")),
        },
        "roadblock": _zone_audit(roadblock),
        "roadblock_room": {
            "state": roadblock_room.get("state"),
            "blocked": bool(roadblock_room.get("blocked")),
        },
        "structural_room": {
            "state": structural_room.get("state"),
            "blocked": bool(structural_room.get("blocked")),
            "distance_parent_atr": structural_room.get("distance_parent_atr"),
            "planned_rr": structural_room.get("planned_rr"),
        },
        "news": {
            "risk_state": news.get("risk_state"),
            "effective_entry_state": news.get("effective_entry_state"),
            "overshoot_risk": news.get("overshoot_risk"),
            "focal_event": {
                "event_id": focal_event.get("event_id"),
                "category": focal_event.get("category"),
                "impact": focal_event.get("impact"),
                "scheduled_at": focal_event.get("scheduled_at"),
                "scheduled_at_wib": focal_event.get("scheduled_at_wib"),
                "source_tier": focal_event.get("source_tier"),
            },
        },
        "micro_confirmation": {
            "stage": micro.get("stage"),
            "confirmed": bool(micro.get("confirmed")),
            "touched": bool(micro.get("touched")),
            "sweep_seen": bool(micro.get("sweep_seen")),
            "reclaim_at": micro.get("reclaim_at"),
            "mss_confirmed": bool(micro.get("mss_confirmed")),
            "displacement_confirmed": bool(micro.get("displacement_confirmed")),
            "entry_low": micro.get("entry_low"),
            "entry_high": micro.get("entry_high"),
            "entry_reference": micro.get("entry_reference"),
            "invalidation": micro.get("invalidation"),
        },
        "order_plan": {
            "signal_id": candidate.get("signal_id"),
            "entry": candidate.get("entry"),
            "sl": candidate.get("stop_loss"),
            "tp": candidate.get("take_profit"),
            "rr": candidate.get("rr"),
            "target_source": candidate.get("target_source"),
            "parent_zone_id": candidate.get("parent_zone_id"),
            "destination_zone_id": candidate.get("destination_zone_id"),
            "reclaim_at": candidate.get("reclaim_at"),
        },
    }


def run() -> int:
    base_policy = load_execution_policy(None)
    if str(base_policy.broker.get("execution", "")).upper() != "CTRADER":
        raise SystemExit("V351_EXECUTOR_CTRADER_ONLY")
    if str(base_policy.ctrader.get("environment", "")).upper() != "DEMO":
        raise SystemExit("V351_EXECUTOR_DEMO_ONLY")
    if not bool(base_policy.ctrader.get("require_demo", False)):
        raise SystemExit("V351_EXECUTOR_REQUIRE_DEMO")

    policy = replace(base_policy, mode=ExecutionMode.AUTO)
    store = SupabaseOperationalStore.from_env(execution_ready_score_floor=65.0)
    control_store = SupabaseOperationalStore.from_env(execution_ready_score_floor=65.0)
    gateway, session = build_broker_gateway(policy, (SYMBOL,), backend="CTRADER")
    gate = ControlPlaneGate(
        max_age_seconds=float(policy.live_safety.get("control_state_max_age_seconds", 5))
    )
    control = ControlPlaneRefreshWorker(control_store, gate, interval_seconds=1.0)
    router = ExecutionRouter(
        policy,
        gateway=gateway,
        session=session,
        control_gate=gate,
        audit_sink=SupabaseOrderAuditSink(store),
    )

    now = datetime.now(tz=UTC)
    state = "WAIT"
    reason = "NOT_EVALUATED"
    candidate: dict[str, Any] | None = None
    accepted = False
    broker_order_id: str | None = None
    error: str | None = None
    margin_usage: float | None = None

    try:
        control.refresh_once()
        control.start()
        gate.assert_orders_allowed(ExecutionMode.AUTO.value)
        if hasattr(session, "ensure_connected"):
            session.ensure_connected()

        protected, protection_reason = _protected_positions_only(session)
        if not protected:
            state = "BLOCKED"
            reason = protection_reason
        else:
            margin_ok, margin_reason, margin_usage = _margin_room_ok(gateway)
            if not margin_ok:
                state = "BLOCKED"
                reason = margin_reason
            else:
                heartbeat = _latest_source(store)
                quote = gateway.market_quote(SYMBOL)
                candidate, reason = _candidate(
                    heartbeat=heartbeat,
                    bid=float(quote.bid),
                    ask=float(quote.ask),
                    now=now,
                )
                if candidate is None:
                    state = "WAIT"
                elif _already_accepted(store, str(candidate["signal_id"])):
                    state = "DUPLICATE_BLOCK"
                    reason = "SIGNAL_ALREADY_ACCEPTED"
                else:
                    side = (
                        OrderSide.BUY
                        if str(candidate["direction"]) == "LONG"
                        else OrderSide.SELL
                    )
                    intent = OrderIntent(
                        signal_id=str(candidate["signal_id"]),
                        symbol=SYMBOL,
                        side=side,
                        order_type=OrderType.MARKET,
                        created_at=now,
                        volume=min(LOT, float(policy.demo_safety.get("max_order_lots", LOT))),
                        entry_price=float(candidate["entry"]),
                        stop_loss=float(candidate["stop_loss"]),
                        take_profit=float(candidate["take_profit"]),
                        risk_pct=RISK_PCT,
                        comment="DEMO_AUTO:RIZAN_V351",
                    )
                    control.refresh_once()
                    receipt = router.execute(intent)
                    accepted = bool(receipt.accepted)
                    broker_order_id = receipt.broker_order_id
                    state = "ORDER_ACCEPTED" if accepted else "ORDER_NOT_ACCEPTED"
                    reason = receipt.message
                    try:
                        store.record_order_event(
                            backend="CTRADER",
                            account_id=str(
                                getattr(gateway.account_snapshot(), "account_id", "UNKNOWN")
                            ),
                            signal_key=str(candidate["signal_id"]),
                            event_type=EVENT_TYPE,
                            broker_order_id=broker_order_id,
                            accepted=accepted,
                            code="V351_DEMO_EXECUTION",
                            message=reason,
                            payload={
                                "execution_scope": EXECUTION_SCOPE,
                                "direction": candidate["direction"],
                                "entry": candidate["entry"],
                                "entry_mode": candidate.get("entry_mode"),
                                "confirmation_age_seconds": candidate.get("confirmation_age_seconds"),
                                "confirmation_drift_atr": candidate.get("confirmation_drift_atr"),
                                "sl": candidate["stop_loss"],
                                "tp": candidate["take_profit"],
                                "rr": candidate["rr"],
                                "target_source": candidate["target_source"],
                                "lot": LOT,
                                "parent_zone_id": candidate["parent_zone_id"],
                                "destination_zone_id": candidate["destination_zone_id"],
                                "reclaim_at": candidate["reclaim_at"],
                                "evidence_ledger": _evidence_ledger(heartbeat, candidate),
                            },
                        )
                    except Exception:
                        pass
    except Exception as exc:
        error = f"{type(exc).__name__}:{exc}"
        state = "ERROR_FAIL_CLOSED"
        reason = error
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
            "state": state,
            "reason": reason,
            "git_sha": (
                os.getenv("RIZAN_RUNTIME_HEAD_SHA")
                or os.getenv("GITHUB_SHA")
                or "UNKNOWN"
            ),
            "execution_scope": EXECUTION_SCOPE,
            "live_execution_enabled": False,
            "lot": LOT,
            "min_rr": MIN_RR,
            "max_margin_usage_fraction": MAX_MARGIN_USAGE_FRACTION,
            "margin_usage_fraction": margin_usage,
            "candidate": candidate or {},
            "accepted": accepted,
            "broker_order_id": broker_order_id,
            "error": error,
        },
    )
    print(
        "XAU_V351_DEMO_EXECUTOR "
        f"state={state} accepted={int(accepted)} reason={reason} "
        "scope=DEMO_ONLY live=0"
    )
    return 0 if error is None else 2


if __name__ == "__main__":
    raise SystemExit(run())

from __future__ import annotations

import os
from dataclasses import replace
from datetime import UTC, datetime
from time import sleep
from typing import Any

from .execution.control_plane import ControlPlaneGate, ControlPlaneRefreshWorker
from .execution.demo_autotrade import SupabaseOrderAuditSink
from .execution.factory import build_broker_gateway
from .execution.models import ExecutionMode, OrderIntent, OrderSide, OrderType
from .execution.policy import load_execution_policy
from .execution.router import ExecutionRouter
from .storage.supabase_operational import SupabaseOperationalStore

SYMBOL = "XAUUSD"
WORKER_NAME = "ctrader_demo_xau_broker_canary_v272"
EVENT_TYPE = "DEMO_XAU_BROKER_CANARY"
EVENT_CODE = "XAU_RIZAN_BROKER_CANARY_V272"
SIGNAL_ID = "RZCANARY:V272:XAUUSD"
LOT = 0.01
ENABLED_ENV = "CTRADER_DEMO_BROKER_CANARY_ENABLED"


def _account_label() -> str:
    return (
        os.getenv("CTRADER_ACCOUNT_ID", "").strip()
        or os.getenv("CTRADER_TRADER_LOGIN", "").strip()
        or "UNKNOWN"
    )


def _record(
    store: SupabaseOperationalStore,
    *,
    accepted: bool | None,
    broker_order_id: str | None,
    code: str,
    message: str,
    payload: dict[str, Any] | None = None,
) -> None:
    store.record_order_event(
        backend="CTRADER",
        account_id=_account_label(),
        signal_key=SIGNAL_ID,
        broker_order_id=broker_order_id,
        event_type=EVENT_TYPE,
        accepted=accepted,
        code=code,
        message=message,
        payload={
            "environment": "DEMO",
            "diagnostic_only": True,
            "exclude_from_strategy_stats": True,
            "symbol": SYMBOL,
            "lot": LOT,
            **dict(payload or {}),
        },
    )


def _already_verified(store: SupabaseOperationalStore) -> bool:
    response = (
        store.client.table("broker_order_events")
        .select("accepted,code,event_type")
        .eq("signal_key", SIGNAL_ID)
        .eq("event_type", EVENT_TYPE)
        .eq("code", "CANARY_CANCELLED_CONFIRMED")
        .eq("accepted", True)
        .order("observed_at", desc=True)
        .limit(1)
        .execute()
    )
    return bool(response.data or [])


def _client_id(order: Any) -> str:
    return str(getattr(order, "clientOrderId", "") or "")


def _position_comment(position: Any) -> str:
    trade_data = getattr(position, "tradeData", None)
    return str(getattr(trade_data, "comment", "") or "")


def _pending_canaries(reconcile: Any) -> list[Any]:
    return [
        order
        for order in tuple(getattr(reconcile, "order", ()) or ())
        if _client_id(order) == SIGNAL_ID
    ]


def _canary_positions(reconcile: Any) -> list[Any]:
    return [
        position
        for position in tuple(getattr(reconcile, "position", ()) or ())
        if SIGNAL_ID in _position_comment(position)
    ]


def _cancel_order(session: Any, order_id: int) -> bool:
    response = session.cancel_order(int(order_id))
    return int(getattr(response, "executionType", -1)) == 5


def _cleanup_pending_canaries(session: Any) -> tuple[bool, list[str]]:
    actions: list[str] = []
    for attempt in range(1, 4):
        reconcile = session.reconcile()
        pending = _pending_canaries(reconcile)
        if not pending:
            return True, actions
        for order in pending:
            order_id = int(getattr(order, "orderId", 0) or 0)
            if order_id <= 0:
                actions.append("CANARY_PENDING_ORDER_ID_MISSING")
                continue
            try:
                cancelled = _cancel_order(session, order_id)
            except Exception as exc:
                actions.append(
                    f"CANARY_CANCEL_ERROR:{order_id}:{type(exc).__name__}:{exc}"
                )
                continue
            actions.append(
                f"CANARY_CANCEL_{'ACK' if cancelled else 'REJECTED'}:{order_id}"
            )
        sleep(0.25 * attempt)
    return not _pending_canaries(session.reconcile()), actions


def _canary_prices(*, bid: float, ask: float) -> tuple[float, float, float]:
    """Build a far-away SELL LIMIT that should never fill during the cancel test."""
    reference = max(float(bid), float(ask))
    gap = max(100.0, reference * 0.03)
    protection = max(20.0, reference * 0.005)
    entry = round(reference + gap, 2)
    stop = round(entry + protection, 2)
    target = round(entry - protection, 2)
    return entry, stop, target


def run() -> int:
    base_policy = load_execution_policy(None)
    if str(base_policy.ctrader.get("environment", "")).upper() != "DEMO":
        raise SystemExit("BROKER_CANARY_DEMO_ONLY")
    if not bool(base_policy.ctrader.get("require_demo", False)):
        raise SystemExit("BROKER_CANARY_REQUIRE_DEMO")

    store = SupabaseOperationalStore.from_env(execution_ready_score_floor=65.0)
    enabled = os.getenv(ENABLED_ENV, "0").strip() == "1"
    if not enabled:
        store.write_heartbeat(
            WORKER_NAME,
            healthy=True,
            lag_seconds=0.0,
            details={"enabled": False, "reason": "CANARY_DISABLED"},
        )
        return 0

    policy = replace(base_policy, mode=ExecutionMode.AUTO)
    gateway, session = build_broker_gateway(policy, (SYMBOL,), backend="CTRADER")
    gate = ControlPlaneGate(
        max_age_seconds=float(
            policy.live_safety.get("control_state_max_age_seconds", 5)
        )
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
    verified = False
    receipt_order_id: str | None = None
    try:
        control.refresh_once()
        control.start()

        cleanup_ok, cleanup_actions = _cleanup_pending_canaries(session)
        actions.extend(cleanup_actions)
        if not cleanup_ok:
            raise RuntimeError("CANARY_STALE_PENDING_CLEANUP_FAILED")

        reconcile = session.reconcile()
        if _canary_positions(reconcile):
            raise RuntimeError("CANARY_UNEXPECTED_POSITION_PRESENT")

        if _already_verified(store):
            verified = True
            actions.append("CANARY_ALREADY_VERIFIED")
            return_code = 0
        elif tuple(getattr(reconcile, "position", ()) or ()):
            actions.append("CANARY_DEFER_OPEN_POSITION_PRESENT")
            return_code = 0
        else:
            quote = gateway.market_quote(SYMBOL)
            entry, stop, target = _canary_prices(
                bid=float(quote.bid),
                ask=float(quote.ask),
            )
            intent = OrderIntent(
                signal_id=SIGNAL_ID,
                symbol=SYMBOL,
                side=OrderSide.SELL,
                order_type=OrderType.LIMIT,
                created_at=datetime.now(UTC),
                volume=LOT,
                entry_price=entry,
                stop_loss=stop,
                take_profit=target,
                risk_pct=0.10,
                comment="DEMO_DIAGNOSTIC:RIZAN_CANARY_V272",
            )
            control.refresh_once()
            receipt = router.execute(intent)
            receipt_order_id = receipt.broker_order_id
            if not receipt.accepted or not receipt_order_id:
                raise RuntimeError(
                    f"CANARY_BROKER_NOT_ACCEPTED:{receipt.message}"
                )
            actions.append(f"CANARY_BROKER_ACCEPTED:{receipt_order_id}")
            _record(
                store,
                accepted=True,
                broker_order_id=receipt_order_id,
                code="CANARY_ORDER_ACCEPTED",
                message=receipt.message,
                payload={
                    "entry": entry,
                    "sl": stop,
                    "tp": target,
                    "side": "SELL",
                },
            )

            cancelled = False
            cancel_errors: list[str] = []
            for attempt in range(1, 4):
                try:
                    cancelled = _cancel_order(session, int(receipt_order_id))
                except Exception as exc:
                    cancel_errors.append(
                        f"{type(exc).__name__}:{exc}"
                    )
                if cancelled:
                    break
                sleep(0.25 * attempt)

            cleanup_ok, cleanup_actions = _cleanup_pending_canaries(session)
            actions.extend(cleanup_actions)
            reconcile_after = session.reconcile()
            unexpected_position = bool(_canary_positions(reconcile_after))
            verified = bool(cancelled and cleanup_ok and not unexpected_position)
            if not verified:
                _record(
                    store,
                    accepted=False,
                    broker_order_id=receipt_order_id,
                    code="CANARY_CANCEL_VERIFY_FAILED",
                    message=";".join(cancel_errors) or "cancel not confirmed",
                    payload={
                        "cancelled": cancelled,
                        "cleanup_ok": cleanup_ok,
                        "unexpected_position": unexpected_position,
                    },
                )
                raise RuntimeError("CANARY_CANCEL_VERIFY_FAILED")

            _record(
                store,
                accepted=True,
                broker_order_id=receipt_order_id,
                code="CANARY_CANCELLED_CONFIRMED",
                message="broker accepted pending DEMO canary and cancellation was reconciled",
                payload={
                    "entry": entry,
                    "sl": stop,
                    "tp": target,
                    "side": "SELL",
                    "cancelled": True,
                    "pending_after_cancel": 0,
                    "position_after_cancel": 0,
                },
            )
            actions.append(f"CANARY_CANCELLED_CONFIRMED:{receipt_order_id}")
            return_code = 0
    except Exception as exc:
        error = f"{type(exc).__name__}:{exc}"
        return_code = 2
        _record(
            store,
            accepted=False,
            broker_order_id=receipt_order_id,
            code="CANARY_ERROR",
            message=error,
            payload={"actions": actions[-12:]},
        )
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
                "enabled": True,
                "environment": "DEMO",
                "diagnostic_only": True,
                "exclude_from_strategy_stats": True,
                "verified": verified,
                "signal_id": SIGNAL_ID,
                "lot": LOT,
                "order_type": "SELL_LIMIT_THEN_IMMEDIATE_CANCEL",
                "actions": actions[-20:],
                "error": error,
                "code_version": os.getenv("GITHUB_SHA", "LOCAL"),
                "observed_at": datetime.now(UTC).isoformat(),
            },
        )
    return return_code


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()

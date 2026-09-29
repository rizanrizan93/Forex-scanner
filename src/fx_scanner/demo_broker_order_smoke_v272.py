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
WORKER_NAME = "ctrader_demo_broker_route_smoke_v272"
EVENT_TYPE = "DEMO_BROKER_ROUTE_SMOKE_V272"
SIGNAL_KEY = "RIZAN_BROKER_ROUTE_SMOKE_V272"
ENABLE_ENV = "CTRADER_DEMO_BROKER_SMOKE_V272_ENABLED"
LOT = 0.01
ENTRY_DISCOUNT_FRACTION = 0.03
PROTECTION_FRACTION = 0.0025


def _already_passed(store: SupabaseOperationalStore) -> bool:
    response = (
        store.client.table("broker_order_events")
        .select("accepted,code")
        .eq("event_type", EVENT_TYPE)
        .eq("signal_key", SIGNAL_KEY)
        .eq("accepted", True)
        .eq("code", "SMOKE_CANCEL_VERIFIED")
        .order("observed_at", desc=True)
        .limit(1)
        .execute()
    )
    return bool(response.data)


def _orders(reconcile: Any) -> tuple[Any, ...]:
    return tuple(getattr(reconcile, "order", ()) or ())


def _positions(reconcile: Any) -> tuple[Any, ...]:
    return tuple(getattr(reconcile, "position", ()) or ())


def _order_id(order: Any) -> int:
    try:
        return int(getattr(order, "orderId", 0) or 0)
    except (TypeError, ValueError):
        return 0


def _is_smoke_order(order: Any) -> bool:
    client = str(getattr(order, "clientOrderId", "") or "")
    comment = str(getattr(order, "comment", "") or "")
    return SIGNAL_KEY in client or SIGNAL_KEY in comment


def _price_digits(session: Any) -> int:
    info = session.symbol_info(SYMBOL)
    try:
        digits = int(getattr(info, "digits", 2) or 2)
    except (TypeError, ValueError):
        digits = 2
    return min(5, max(0, digits))


def smoke_geometry(*, bid: float, digits: int) -> dict[str, float]:
    """Build an intentionally remote BUY LIMIT that is immediately cancelled."""
    if bid <= 0:
        raise ValueError("bid must be positive")
    entry = round(float(bid) * (1.0 - ENTRY_DISCOUNT_FRACTION), int(digits))
    stop = round(entry * (1.0 - PROTECTION_FRACTION), int(digits))
    target = round(entry * (1.0 + PROTECTION_FRACTION), int(digits))
    if not (0 < stop < entry < target < float(bid)):
        raise ValueError("unsafe smoke geometry")
    return {"entry": entry, "sl": stop, "tp": target}


def _record(
    store: SupabaseOperationalStore,
    *,
    account_id: str,
    accepted: bool,
    code: str,
    message: str,
    broker_order_id: str | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    store.record_order_event(
        backend="CTRADER",
        account_id=account_id,
        signal_key=SIGNAL_KEY,
        event_type=EVENT_TYPE,
        broker_order_id=broker_order_id,
        accepted=accepted,
        code=code,
        message=message,
        payload={
            "environment": "DEMO",
            "calibration_only": True,
            "strategy_statistics_influence": False,
            "live_execution_authority": False,
            **(payload or {}),
        },
    )


def run() -> int:
    store = SupabaseOperationalStore.from_env(execution_ready_score_floor=65.0)
    enabled = os.getenv(ENABLE_ENV, "0").strip() == "1"
    if not enabled:
        store.write_heartbeat(
            WORKER_NAME,
            healthy=True,
            lag_seconds=0.0,
            details={"enabled": False, "reason": "SMOKE_DISABLED"},
        )
        return 0

    if _already_passed(store):
        store.write_heartbeat(
            WORKER_NAME,
            healthy=True,
            lag_seconds=0.0,
            details={
                "enabled": True,
                "state": "ALREADY_VERIFIED",
                "event_type": EVENT_TYPE,
                "code_version": os.getenv("GITHUB_SHA", "LOCAL"),
            },
        )
        return 0

    base_policy = load_execution_policy()
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

    account_id = "UNKNOWN"
    details: dict[str, Any] = {
        "enabled": True,
        "environment": "DEMO",
        "symbol": SYMBOL,
        "lot": LOT,
        "state": "STARTED",
        "code_version": os.getenv("GITHUB_SHA", "LOCAL"),
    }
    error: str | None = None
    try:
        control.refresh_once()
        control.start()
        account = gateway.account_snapshot()
        account_id = str(account.account_id)
        if not bool(account.trade_allowed):
            details["state"] = "ACCOUNT_NOT_TRADE_ALLOWED"
            return 0

        reconcile = session.reconcile()
        # Clean up only our own prior smoke order before any retry.
        for order in _orders(reconcile):
            if _is_smoke_order(order) and _order_id(order):
                session.cancel_order(_order_id(order))
        if any(_is_smoke_order(order) for order in _orders(reconcile)):
            sleep(0.25)
            reconcile = session.reconcile()

        if _positions(reconcile):
            details["state"] = "SKIP_OPEN_POSITION_PRESENT"
            details["position_count"] = len(_positions(reconcile))
            return 0
        non_smoke_orders = [order for order in _orders(reconcile) if not _is_smoke_order(order)]
        if non_smoke_orders:
            details["state"] = "SKIP_EXISTING_PENDING_ORDER"
            details["pending_order_count"] = len(non_smoke_orders)
            return 0

        quote = gateway.market_quote(SYMBOL)
        digits = _price_digits(session)
        geometry = smoke_geometry(bid=float(quote.bid), digits=digits)
        details.update(
            {
                "quote_bid": float(quote.bid),
                "quote_ask": float(quote.ask),
                "entry": geometry["entry"],
                "sl": geometry["sl"],
                "tp": geometry["tp"],
                "entry_distance_fraction": ENTRY_DISCOUNT_FRACTION,
            }
        )

        intent = OrderIntent(
            signal_id=SIGNAL_KEY,
            symbol=SYMBOL,
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            created_at=datetime.now(tz=UTC),
            volume=LOT,
            entry_price=geometry["entry"],
            stop_loss=geometry["sl"],
            take_profit=geometry["tp"],
            risk_pct=1.0,
            comment="DEMO_ONLY:RIZAN_BROKER_ROUTE_SMOKE_V272",
        )
        control.refresh_once()
        receipt = router.execute(intent)
        details["submit_accepted"] = bool(receipt.accepted)
        details["broker_order_id"] = receipt.broker_order_id
        details["submit_message"] = receipt.message
        if not receipt.accepted or not receipt.broker_order_id:
            _record(
                store,
                account_id=account_id,
                accepted=False,
                code="SMOKE_SUBMIT_REJECTED",
                message=receipt.message or "broker did not accept smoke pending order",
                broker_order_id=receipt.broker_order_id,
                payload=details,
            )
            details["state"] = "SUBMIT_REJECTED"
            return 1

        order_id = int(receipt.broker_order_id)
        cancel_response = session.cancel_order(order_id)
        details["cancel_execution_type"] = int(
            getattr(cancel_response, "executionType", -1)
        )
        cancelled = False
        for _ in range(4):
            reconcile = session.reconcile()
            active_ids = {_order_id(order) for order in _orders(reconcile)}
            if order_id not in active_ids:
                cancelled = True
                break
            sleep(0.25)

        details["cancel_verified"] = cancelled
        details["post_cancel_position_count"] = len(_positions(reconcile))
        if not cancelled or _positions(reconcile):
            _record(
                store,
                account_id=account_id,
                accepted=False,
                code="SMOKE_CANCEL_NOT_VERIFIED",
                message="smoke pending order was accepted but clean cancellation was not verified",
                broker_order_id=str(order_id),
                payload=details,
            )
            details["state"] = "CANCEL_NOT_VERIFIED"
            return 1

        _record(
            store,
            account_id=account_id,
            accepted=True,
            code="SMOKE_CANCEL_VERIFIED",
            message="DEMO cTrader pending order accepted then cancelled and reconciled cleanly",
            broker_order_id=str(order_id),
            payload=details,
        )
        details["state"] = "SMOKE_CANCEL_VERIFIED"
        return 0
    except Exception as exc:
        error = f"{type(exc).__name__}:{exc}"
        details["state"] = "ERROR"
        details["error"] = error
        try:
            _record(
                store,
                account_id=account_id,
                accepted=False,
                code="SMOKE_EXCEPTION",
                message=error,
                payload=details,
            )
        except Exception:
            pass
        return 1
    finally:
        try:
            control.stop(timeout=2.0)
        except Exception:
            pass
        try:
            session.close()
        except Exception:
            pass
        try:
            store.write_heartbeat(
                WORKER_NAME,
                healthy=error is None and details.get("state") not in {
                    "SUBMIT_REJECTED",
                    "CANCEL_NOT_VERIFIED",
                    "ERROR",
                },
                lag_seconds=0.0,
                details=details,
            )
        except Exception:
            pass


def main() -> int:
    return run()


if __name__ == "__main__":
    raise SystemExit(main())

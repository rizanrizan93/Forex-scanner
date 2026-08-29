from datetime import datetime, timezone

from fx_scanner.execution.models import ExecutionMode, OrderIntent, OrderSide, OrderType
from fx_scanner.execution.policy import ExecutionPolicy
from fx_scanner.execution.router import ExecutionRouter
from fx_scanner.execution.service import RuntimeHandlers, TradingRuntimeService

UTC = timezone.utc


def _policy():
    return ExecutionPolicy(
        mode=ExecutionMode.SIMULATION,
        scheduler={
            "heavy_scan_seconds": 900,
            "fast_setup_seconds": 60,
            "execution_watch_seconds": 2,
            "position_monitor_seconds": 2,
        },
        order={
            "max_signal_age_seconds": 300,
            "require_order_check": True,
            "require_server_side_sl": True,
            "require_server_side_tp": True,
        },
        live_safety={
            "live_enable_env": "FX_LIVE_TRADING_ENABLED",
            "live_enable_value": "I_UNDERSTAND_LIVE_ORDERS",
            "account_allowlist_env": "FX_MT5_ACCOUNT_ALLOWLIST",
            "require_account_allowlist": True,
            "kill_switch_env": "FX_KILL_SWITCH",
            "kill_switch_safe_value": "0",
        },
        runtime={
            "max_lag_seconds": {"heavy_scan": 120, "fast_setup": 15, "execution_watch": 3, "position_monitor": 3},
            "execution_queue_maxsize": 10,
            "concurrent_workers": 4,
        },
    )


def test_runtime_service_four_cadences_and_execution_queue(monkeypatch):
    monkeypatch.setenv("FX_KILL_SWITCH", "0")
    calls = []
    handlers = RuntimeHandlers(
        heavy_scan=lambda: calls.append("heavy"),
        fast_setup=lambda: calls.append("fast"),
        execution_watch=lambda: calls.append("execution"),
        position_monitor=lambda: calls.append("position"),
    )
    router = ExecutionRouter(_policy())
    service = TradingRuntimeService(_policy(), router, handlers)
    service.tick(100.0)
    service.shutdown(wait=True)
    assert set(calls) == {"heavy", "fast", "execution", "position"}

    intent = OrderIntent(
        signal_id="QUEUE-1",
        symbol="EURUSD",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        created_at=datetime.now(tz=UTC),
        volume=0.05,
        entry_price=1.10,
        stop_loss=1.09,
        take_profit=1.12,
        risk_pct=0.25,
    )
    service.submit_order(intent)
    receipt = service.process_one_order()
    assert receipt.status == "OK"
    assert receipt.value.accepted
    assert receipt.value.mode == ExecutionMode.SIMULATION


def test_full_health_includes_execution_worker(monkeypatch):
    monkeypatch.setenv("FX_KILL_SWITCH", "0")
    handlers = RuntimeHandlers(lambda: None, lambda: None, lambda: None, lambda: None)
    service = TradingRuntimeService(_policy(), ExecutionRouter(_policy()), handlers)
    health = service.full_health()
    assert health["healthy"] is True
    assert health["execution_worker"]["stuck"] is False
    service.shutdown()

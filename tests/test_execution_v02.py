from datetime import datetime, timezone
from pathlib import Path

import pytest

from fx_scanner.execution.duplicate_guard import DuplicateOrderGuard
from fx_scanner.execution.kill_switch import KillSwitch
from fx_scanner.execution.models import ExecutionMode, OrderIntent, OrderSide, OrderType
from fx_scanner.execution.policy import ExecutionPolicy, load_execution_policy
from fx_scanner.execution.position_sizer import SymbolTradeSpec, size_position
from fx_scanner.execution.router import ExecutionBlocked, ExecutionRouter


UTC = timezone.utc


def intent(signal_id: str = "SIG-1") -> OrderIntent:
    return OrderIntent(
        signal_id=signal_id,
        symbol="EURUSD",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        created_at=datetime.now(tz=UTC),
        volume=0.10,
        entry_price=1.1000,
        stop_loss=1.0950,
        take_profit=1.1100,
        risk_pct=0.25,
    )


def policy(mode: ExecutionMode) -> ExecutionPolicy:
    return ExecutionPolicy(
        mode=mode,
        scheduler={
            "heavy_scan_seconds": 900,
            "fast_setup_seconds": 60,
            "execution_watch_seconds": 2,
            "position_monitor_seconds": 2,
        },
        order={
            "max_signal_age_seconds": 300,
            "require_broker_preflight": True,
            "require_server_side_sl": True,
            "default_deviation_points": 20,
            "magic_number": 1,
        },
        live_safety={
            "live_enable_env": "FX_LIVE_TRADING_ENABLED",
            "live_enable_value": "I_UNDERSTAND_LIVE_ORDERS",
            "account_allowlist_env": "FX_BROKER_ACCOUNT_ALLOWLIST",
            "require_account_allowlist": True,
            "kill_switch_env": "FX_KILL_SWITCH",
            "kill_switch_safe_value": "0",
        },
    )


def test_v02_config_defaults_to_disabled():
    p = load_execution_policy()
    assert p.mode == ExecutionMode.DISABLED
    assert p.scheduler["heavy_scan_seconds"] == 900
    assert p.scheduler["fast_setup_seconds"] == 15


def test_disabled_mode_cannot_execute(monkeypatch):
    monkeypatch.setenv("FX_KILL_SWITCH", "0")
    router = ExecutionRouter(policy(ExecutionMode.DISABLED), duplicate_guard=DuplicateOrderGuard())
    with pytest.raises(ExecutionBlocked, match="EXECUTION_DISABLED"):
        router.execute(intent())


def test_simulation_is_idempotent(monkeypatch):
    monkeypatch.setenv("FX_KILL_SWITCH", "0")
    guard = DuplicateOrderGuard()
    router = ExecutionRouter(policy(ExecutionMode.SIMULATION), duplicate_guard=guard)
    receipt = router.execute(intent())
    assert receipt.accepted
    assert receipt.mode == ExecutionMode.SIMULATION
    with pytest.raises(ExecutionBlocked, match="DUPLICATE_SIGNAL"):
        router.execute(intent())


def test_kill_switch_blocks_simulation(monkeypatch):
    monkeypatch.setenv("FX_KILL_SWITCH", "1")
    router = ExecutionRouter(policy(ExecutionMode.SIMULATION), duplicate_guard=DuplicateOrderGuard())
    with pytest.raises(ExecutionBlocked, match="KILL_SWITCH_ENGAGED"):
        router.execute(intent())


def test_confirm_mode_requires_confirmation(monkeypatch):
    monkeypatch.setenv("FX_KILL_SWITCH", "0")
    router = ExecutionRouter(policy(ExecutionMode.CONFIRM_TO_TRADE), duplicate_guard=DuplicateOrderGuard())
    with pytest.raises(ExecutionBlocked, match="USER_CONFIRMATION_REQUIRED"):
        router.execute(intent(), user_confirmed=False)


def test_position_sizer_uses_broker_tick_economics():
    spec = SymbolTradeSpec(
        tick_size=0.0001,
        tick_value_loss=10.0,
        volume_min=0.01,
        volume_max=100.0,
        volume_step=0.01,
    )
    vol = size_position(
        equity=10_000,
        risk_pct=0.25,
        entry_price=1.1000,
        stop_loss=1.0950,
        spec=spec,
    )
    assert vol == 0.05


def test_persistent_duplicate_guard(tmp_path: Path):
    path = tmp_path / "seen.json"
    g1 = DuplicateOrderGuard(path)
    g1.mark_executed("ABC")
    g2 = DuplicateOrderGuard(path)
    assert g2.is_duplicate("ABC")

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from fx_scanner.config import load_project_config
from fx_scanner.execution.broker_gateway import (
    BrokerAccountSnapshot,
    BrokerBackend,
    BrokerOrderResult,
    BrokerPreflight,
)
from fx_scanner.execution.demo_autotrade import CTraderDemoAutoExecutor
from fx_scanner.execution.models import ExecutionMode, OrderIntent, OrderSide, OrderType
from fx_scanner.execution.policy import ExecutionPolicy, load_execution_policy
from fx_scanner.execution.router import ExecutionBlocked, ExecutionRouter

UTC = timezone.utc


class Gate:
    def __init__(self):
        self.calls = 0

    def assert_orders_allowed(self, required_mode):
        assert required_mode == "AUTO"
        self.calls += 1


class Gateway:
    backend = BrokerBackend.CTRADER

    def __init__(self, *, positions=0, quote=1.1000):
        self.positions = positions
        self.quote = quote
        self.sent = 0

    def position_count(self):
        return self.positions

    def account_snapshot(self):
        return BrokerAccountSnapshot(
            self.backend, "9001001", 10000, 10000, 10000, True
        )

    def preflight(self, intent, order_config):
        return BrokerPreflight(self.backend, True, "OK", "ok", intent)

    def submit(self, preflight):
        self.sent += 1
        return BrokerOrderResult(
            self.backend, True, "3", "filled", "777", 0.01, self.quote
        )

    def market_quote(self, symbol):
        return SimpleNamespace(bid=self.quote - 0.0001, ask=self.quote)


def policy():
    return ExecutionPolicy(
        mode=ExecutionMode.AUTO,
        scheduler={
            "heavy_scan_seconds": 900,
            "fast_setup_seconds": 15,
            "execution_watch_seconds": 0.25,
            "position_monitor_seconds": 2,
        },
        order={
            "max_signal_age_seconds": 300,
            "require_broker_preflight": True,
            "require_server_side_sl": True,
            "require_server_side_tp": True,
        },
        live_safety={
            "live_enable_env": "FX_LIVE_TRADING_ENABLED",
            "live_enable_value": "I_UNDERSTAND_LIVE_ORDERS",
            "account_allowlist_env": "FX_BROKER_ACCOUNT_ALLOWLIST",
            "require_account_allowlist": True,
            "kill_switch_env": "FX_KILL_SWITCH",
            "kill_switch_safe_value": "0",
            "require_control_plane": True,
        },
        broker={"research": "CTRADER", "execution": "CTRADER"},
        ctrader={
            "role": "RESEARCH_AND_DEMO_EXECUTION",
            "environment": "DEMO",
            "require_demo": True,
        },
        demo_safety={
            "enable_env": "CTRADER_DEMO_AUTOTRADE_ENABLED",
            "enable_value": "I_UNDERSTAND_DEMO_ORDERS",
            "require_demo_account": True,
            "require_trade_scope": True,
            "require_atomic_signal_claim": True,
            "min_signal_coverage": 0.80,
            "max_order_lots": 0.01,
            "max_risk_pct": 0.25,
            "max_concurrent_positions": 1,
            "poll_seconds": 1.0,
        },
    )


def intent(volume=0.01):
    return OrderIntent(
        signal_id="demo-signal-1",
        symbol="EURUSD",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        created_at=datetime.now(tz=UTC),
        volume=volume,
        entry_price=1.1000,
        stop_loss=1.0950,
        take_profit=1.1100,
        risk_pct=0.25,
    )


def test_canonical_config_switches_only_demo_execution_backend():
    p = load_execution_policy()
    assert p.mode == ExecutionMode.DISABLED
    assert p.broker["research"] == "CTRADER"
    assert p.broker["execution"] == "CTRADER"
    assert not p.broker["dual_feed_single_execution"]
    assert p.ctrader["environment"] == "DEMO"
    assert p.ctrader["role"] == "RESEARCH_AND_DEMO_EXECUTION"
    assert p.demo_safety["max_order_lots"] == 0.01
    assert p.demo_safety["max_concurrent_positions"] == 1


def test_demo_auto_requires_explicit_opt_in(monkeypatch):
    monkeypatch.setenv("FX_KILL_SWITCH", "0")
    monkeypatch.delenv("CTRADER_DEMO_AUTOTRADE_ENABLED", raising=False)
    gateway = Gateway()
    router = ExecutionRouter(policy(), gateway=gateway, control_gate=Gate())
    with pytest.raises(ExecutionBlocked, match="DEMO_ENV_GATE_CLOSED"):
        router.execute(intent())
    assert gateway.sent == 0


def test_demo_auto_rejects_more_than_one_open_position(monkeypatch):
    monkeypatch.setenv("FX_KILL_SWITCH", "0")
    monkeypatch.setenv("CTRADER_DEMO_AUTOTRADE_ENABLED", "I_UNDERSTAND_DEMO_ORDERS")
    gateway = Gateway(positions=1)
    router = ExecutionRouter(policy(), gateway=gateway, control_gate=Gate())
    with pytest.raises(ExecutionBlocked, match="DEMO_MAX_CONCURRENT_POSITIONS"):
        router.execute(intent())
    assert gateway.sent == 0


def test_demo_auto_rejects_volume_above_one_centilot(monkeypatch):
    monkeypatch.setenv("FX_KILL_SWITCH", "0")
    monkeypatch.setenv("CTRADER_DEMO_AUTOTRADE_ENABLED", "I_UNDERSTAND_DEMO_ORDERS")
    gateway = Gateway()
    router = ExecutionRouter(policy(), gateway=gateway, control_gate=Gate())
    with pytest.raises(ExecutionBlocked, match="DEMO_MAX_ORDER_LOTS_EXCEEDED"):
        router.execute(intent(volume=0.02))
    assert gateway.sent == 0


def test_demo_auto_can_submit_with_all_gates(monkeypatch):
    monkeypatch.setenv("FX_KILL_SWITCH", "0")
    monkeypatch.setenv("CTRADER_DEMO_AUTOTRADE_ENABLED", "I_UNDERSTAND_DEMO_ORDERS")
    gateway = Gateway()
    gate = Gate()
    router = ExecutionRouter(policy(), gateway=gateway, control_gate=gate)
    receipt = router.execute(intent())
    assert receipt.accepted
    assert receipt.broker_order_id == "777"
    assert gateway.sent == 1
    assert gate.calls >= 2


class SignalStore:
    def __init__(self, row):
        self.row = row
        self.claimed = []

    def list_execution_ready_signals(self, *, limit=10):
        return (self.row,)

    def claim_signal_for_execution(self, signal_id):
        self.claimed.append(signal_id)
        return True


class Router:
    def __init__(self, control_gate=None):
        self.intents = []
        self.control_gate = control_gate or Gate()

    def execute(self, intent):
        self.intents.append(intent)
        return SimpleNamespace(accepted=True)


def test_signal_executor_claims_before_demo_execution():
    cfg = load_project_config()
    p = policy()
    now = datetime.now(tz=UTC)
    row = {
        "id": "00000000-0000-0000-0000-000000000001",
        "observed_at": now.isoformat(),
        "symbol": "EURUSD",
        "direction": "LONG",
        "setup_type": "LIQUIDITY_SWEEP_REVERSAL",
        "state": "EXECUTION_READY",
        "entry_low": 1.0998,
        "entry_high": 1.1002,
        "sl": 1.0950,
        "tp2": 1.1100,
        "rr2": 2.0,
        "active_guards": [],
        "data_coverage": 0.90,
        "expires_at": (now + timedelta(minutes=2)).isoformat(),
        "final_score": 95.0,
    }
    store = SignalStore(row)
    router = Router()
    gateway = Gateway(quote=1.1000)
    executor = CTraderDemoAutoExecutor(
        cfg=cfg, policy=p, gateway=gateway, router=router, store=store
    )
    report = executor.poll_once()
    assert report.scanned == 1
    assert report.eligible == 1
    assert report.claimed == 1
    assert report.executed == 1
    assert store.claimed == [row["id"]]
    assert len(router.intents) == 1
    assert router.intents[0].volume == 0.01


def test_signal_executor_does_not_claim_price_outside_entry_zone():
    cfg = load_project_config()
    p = policy()
    now = datetime.now(tz=UTC)
    row = {
        "id": "00000000-0000-0000-0000-000000000002",
        "observed_at": now.isoformat(),
        "symbol": "EURUSD",
        "direction": "LONG",
        "setup_type": "TREND_CONTINUATION",
        "state": "EXECUTION_READY",
        "entry_low": 1.0900,
        "entry_high": 1.0910,
        "sl": 1.0850,
        "tp2": 1.1000,
        "rr2": 2.0,
        "active_guards": [],
        "data_coverage": 0.95,
        "expires_at": (now + timedelta(minutes=2)).isoformat(),
        "final_score": 95.0,
    }
    store = SignalStore(row)
    executor = CTraderDemoAutoExecutor(
        cfg=cfg, policy=p, gateway=Gateway(quote=1.1000), router=Router(), store=store
    )
    report = executor.poll_once()
    assert report.eligible == 0
    assert report.claimed == 0
    assert report.executed == 0
    assert store.claimed == []



class BlockedGate:
    def assert_orders_allowed(self, required_mode):
        assert required_mode == "AUTO"
        raise RuntimeError("NEW_ORDERS_DISABLED")


def test_signal_executor_does_not_claim_when_control_plane_blocks():
    cfg = load_project_config()
    p = policy()
    now = datetime.now(tz=UTC)
    row = {
        "id": "00000000-0000-0000-0000-000000000099",
        "observed_at": now.isoformat(),
        "symbol": "EURUSD",
        "direction": "LONG",
        "setup_type": "TREND_CONTINUATION",
        "state": "EXECUTION_READY",
        "entry_low": 1.0998,
        "entry_high": 1.1002,
        "sl": 1.0950,
        "tp2": 1.1100,
        "rr2": 2.0,
        "active_guards": [],
        "data_coverage": 0.95,
        "expires_at": (now + timedelta(minutes=2)).isoformat(),
        "final_score": 95.0,
    }
    store = SignalStore(row)
    executor = CTraderDemoAutoExecutor(
        cfg=cfg,
        policy=p,
        gateway=Gateway(quote=1.1000),
        router=Router(control_gate=BlockedGate()),
        store=store,
    )

    report = executor.poll_once()

    assert report.scanned == 0
    assert report.claimed == 0
    assert report.executed == 0
    assert store.claimed == []
    assert report.skipped[0].startswith("CONTROL_PLANE_BLOCKED:")

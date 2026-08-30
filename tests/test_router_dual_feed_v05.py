from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from fx_scanner.execution.broker_gateway import BrokerAccountSnapshot, BrokerBackend, BrokerOrderResult, BrokerPreflight
from fx_scanner.execution.models import ExecutionMode, OrderIntent, OrderSide, OrderType
from fx_scanner.execution.policy import ExecutionPolicy
from fx_scanner.execution.router import ExecutionBlocked, ExecutionRouter

UTC = timezone.utc


def policy():
    return ExecutionPolicy(
        mode=ExecutionMode.AUTO,
        scheduler={
            "heavy_scan_seconds": 900,
            "fast_setup_seconds": 60,
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
            "require_revalidation": True,
        },
    )


def intent():
    return OrderIntent(
        signal_id="ROUTER-DF",
        symbol="EURUSD",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        created_at=datetime.now(tz=UTC),
        volume=0.01,
        entry_price=1.1000,
        stop_loss=1.0950,
        take_profit=1.1100,
        risk_pct=0.25,
    )


class Gateway:
    backend = BrokerBackend.MT5
    def __init__(self):
        self.seen = None
    def account_snapshot(self):
        return BrokerAccountSnapshot(self.backend, "777", 10000, 10000, 9000, True, "USC")
    def preflight(self, intent, config):
        self.seen = intent
        return BrokerPreflight(self.backend, True, "0", "ok", {"symbol": intent.broker_symbol})
    def submit(self, preflight):
        return BrokerOrderResult(self.backend, True, "10009", "done", "42", 0.48, 1.1002)


class Revalidator:
    def __init__(self, gateway):
        self.gateway = gateway
    def revalidate(self, original):
        from dataclasses import replace
        prepared = replace(original, broker_symbol="EURUSDc", volume=0.48, entry_price=1.1002)
        metrics = SimpleNamespace(
            research_bid=1.0999, research_ask=1.1001, execution_bid=1.1000,
            execution_ask=1.1002, research_age_seconds=.01, execution_age_seconds=.01,
            mid_divergence_pips=1.0, research_spread_pips=2.0,
            execution_spread_pips=2.0, spread_ratio=1.0,
            entry_drift_pips=2.0, rr=1.88, internal_latency_ms=.2,
        )
        # dataclasses.asdict in router requires a dataclass-like result.metrics.
        from fx_scanner.execution.reconciliation import RevalidationMetrics
        m = RevalidationMetrics(**metrics.__dict__)
        return SimpleNamespace(prepared_intent=prepared, account_snapshot=self.gateway.account_snapshot(), metrics=m)


def open_live(monkeypatch):
    monkeypatch.setenv("FX_KILL_SWITCH", "0")
    monkeypatch.setenv("FX_LIVE_TRADING_ENABLED", "I_UNDERSTAND_LIVE_ORDERS")
    monkeypatch.setenv("FX_BROKER_ACCOUNT_ALLOWLIST", "777")


def test_live_router_requires_revalidator(monkeypatch):
    open_live(monkeypatch)
    with pytest.raises(ExecutionBlocked, match="REVALIDATOR_NOT_CONFIGURED"):
        ExecutionRouter(policy(), gateway=Gateway()).execute(intent())


def test_router_submits_only_revalidated_hfm_intent(monkeypatch):
    open_live(monkeypatch)
    gateway = Gateway()
    router = ExecutionRouter(policy(), gateway=gateway, revalidator=Revalidator(gateway))
    receipt = router.execute(intent())
    assert receipt.accepted
    assert receipt.symbol == "EURUSD"
    assert gateway.seen.broker_symbol == "EURUSDc"
    assert gateway.seen.volume == pytest.approx(0.48)

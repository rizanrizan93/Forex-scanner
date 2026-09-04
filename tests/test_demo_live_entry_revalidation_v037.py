from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from fx_scanner.config import load_project_config
from fx_scanner.execution.demo_autotrade import CTraderDemoAutoExecutor
from fx_scanner.execution.policy import load_execution_policy

UTC = timezone.utc


class QuoteGateway:
    def __init__(self, *, bid: float, ask: float):
        self.bid = bid
        self.ask = ask

    def market_quote(self, symbol):
        assert symbol == "EURUSD"
        return SimpleNamespace(bid=self.bid, ask=self.ask)


def ready_row(*, direction="LONG"):
    now = datetime.now(tz=UTC)
    return {
        "id": "00000000-0000-0000-0000-000000000037",
        "observed_at": now.isoformat(),
        "symbol": "EURUSD",
        "direction": direction,
        "setup_type": "TREND_CONTINUATION",
        "state": "EXECUTION_READY",
        "entry_low": 1.1000,
        "entry_high": 1.1010,
        "sl": 1.0950,
        "tp2": 1.1300,
        "rr2": 4.0,
        "active_guards": [],
        "data_coverage": 0.95,
        "expires_at": (now + timedelta(minutes=2)).isoformat(),
        "final_score": 95.0,
    }


def make_executor(monkeypatch, *, ask: float):
    monkeypatch.setenv("CTRADER_DEMO_MAX_ENTRY_DRIFT_R", "0.50")
    return CTraderDemoAutoExecutor(
        cfg=load_project_config(),
        policy=load_execution_policy(),
        gateway=QuoteGateway(bid=ask - 0.0001, ask=ask),
        router=SimpleNamespace(control_gate=None),
        store=None,
    )


def test_ready_signal_can_execute_slightly_outside_original_entry_zone(monkeypatch):
    executor = make_executor(monkeypatch, ask=1.1020)
    intent, reason = executor._intent_diagnostic(ready_row(), now=datetime.now(tz=UTC))

    assert reason is None
    assert intent is not None
    assert intent.entry_price == pytest.approx(1.1020)


def test_ready_signal_still_blocks_excessive_live_entry_drift(monkeypatch):
    executor = make_executor(monkeypatch, ask=1.1051)
    intent, reason = executor._intent_diagnostic(ready_row(), now=datetime.now(tz=UTC))

    assert intent is None
    assert reason is not None
    assert reason.startswith("ENTRY_DRIFT_R_EXCEEDED_")


def test_live_quote_must_preserve_minimum_rr(monkeypatch):
    executor = make_executor(monkeypatch, ask=1.1180)
    intent, reason = executor._intent_diagnostic(ready_row(), now=datetime.now(tz=UTC))

    assert intent is None
    assert reason is not None
    assert reason.startswith("LIVE_RR_BELOW_MIN_")


def test_demo_entry_drift_contract_fails_closed(monkeypatch):
    monkeypatch.setenv("CTRADER_DEMO_MAX_ENTRY_DRIFT_R", "1.01")
    with pytest.raises(ValueError, match="CTRADER_DEMO_MAX_ENTRY_DRIFT_R_OUT_OF_RANGE"):
        CTraderDemoAutoExecutor(
            cfg=load_project_config(),
            policy=load_execution_policy(),
            gateway=QuoteGateway(bid=1.1, ask=1.1001),
            router=SimpleNamespace(control_gate=None),
            store=None,
        )

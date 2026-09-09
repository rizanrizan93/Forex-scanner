from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from fx_scanner.config import load_project_config
from fx_scanner.demo_fresh_ready_handoff import load_demo_project_config
from fx_scanner.execution.demo_autotrade import CTraderDemoAutoExecutor
from fx_scanner.execution.models import ExecutionMode
from fx_scanner.execution.policy import ExecutionPolicy

UTC = timezone.utc


class QuoteGateway:
    def market_quote(self, symbol):
        # BUY executable=1.1018 against SL=1.0950 / TP=1.1100 -> live RR ~=1.206.
        return SimpleNamespace(bid=1.1017, ask=1.1018)


class Router:
    control_gate = None


class Store:
    pass


def demo_policy():
    return ExecutionPolicy(
        mode=ExecutionMode.AUTO,
        scheduler={
            "heavy_scan_seconds": 900,
            "fast_setup_seconds": 15,
            "execution_watch_seconds": 0.25,
            "position_monitor_seconds": 2,
        },
        order={"max_signal_age_seconds": 300},
        live_safety={},
        demo_safety={
            "min_signal_coverage": 0.80,
            "max_order_lots": 0.10,
            "max_risk_pct": 5.0,
            "max_concurrent_positions": 10,
        },
    )


def execution_ready_row(now):
    return {
        "id": "00000000-0000-0000-0000-000000000075",
        "observed_at": now.isoformat(),
        "symbol": "EURUSD",
        "direction": "LONG",
        "setup_type": "HL_PULLBACK",
        "state": "EXECUTION_READY",
        "entry_low": 1.0998,
        "entry_high": 1.1002,
        "sl": 1.0950,
        "tp2": 1.1100,
        "rr2": 2.0,
        "active_guards": [],
        "data_coverage": 0.95,
        "final_score": 95.0,
    }


def test_demo_override_keeps_canonical_plan_contract_unchanged(monkeypatch):
    monkeypatch.setenv("CTRADER_DEMO_MIN_LIVE_RR", "1.0")
    canonical = load_project_config()
    demo = load_demo_project_config()
    assert canonical.strategy["trade_plan"]["minimum_tp2_rr"] >= 1.5
    assert demo.strategy["trade_plan"]["minimum_tp2_rr"] == 1.0


def test_demo_live_rr_between_1_and_1_5_is_admitted(monkeypatch):
    monkeypatch.setenv("CTRADER_DEMO_MIN_LIVE_RR", "1.0")
    cfg = load_demo_project_config()
    executor = CTraderDemoAutoExecutor(
        cfg=cfg,
        policy=demo_policy(),
        gateway=QuoteGateway(),
        router=Router(),
        store=Store(),
    )
    intent, reason = executor._intent_diagnostic(
        execution_ready_row(datetime.now(tz=UTC)),
        now=datetime.now(tz=UTC),
    )
    assert reason is None
    assert intent is not None
    assert intent.entry_price == pytest.approx(1.1018)


def test_demo_live_rr_floor_cannot_drop_below_one(monkeypatch):
    monkeypatch.setenv("CTRADER_DEMO_MIN_LIVE_RR", "0.99")
    with pytest.raises(RuntimeError, match="CTRADER_DEMO_MIN_LIVE_RR"):
        load_demo_project_config()

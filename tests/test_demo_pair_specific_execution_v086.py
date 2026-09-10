from pathlib import Path

from fx_scanner.demo_conviction_sizing import select_demo_conviction_sizing
from fx_scanner.demo_impulse_retest_v2 import EXECUTION_SYMBOLS, PAIR_STRATEGY_IDS


ROOT = Path(__file__).resolve().parents[1]


def test_pair_specific_execution_registry_contains_only_xau_and_eurusd():
    assert EXECUTION_SYMBOLS == frozenset({"XAUUSD", "EURUSD"})
    assert PAIR_STRATEGY_IDS["XAUUSD"] == "IMPULSE_RETEST_V2"
    assert PAIR_STRATEGY_IDS["EURUSD"] == "EURUSD_IMPULSE_RETEST_BASELINE_V1"


def test_eurusd_bootstrap_sizing_is_capped_below_xau_elite_plus():
    elite = {"symbol": "EURUSD", "final_score": 99, "data_coverage": 1.0, "rr2": 1.5}
    sizing = select_demo_conviction_sizing(elite, max_order_lots=0.50, max_risk_pct=5.0)
    assert sizing.lots == 0.10
    assert sizing.risk_budget_pct == 2.0

    xau = dict(elite, symbol="XAUUSD")
    xau_sizing = select_demo_conviction_sizing(xau, max_order_lots=0.50, max_risk_pct=5.0)
    assert xau_sizing.lots == 0.50
    assert xau_sizing.risk_budget_pct == 5.0


def test_active_workflows_use_pair_specific_wrappers_and_remain_demo_only():
    auto = (ROOT / ".github/workflows/ctrader-demo-auto-pipeline.yml").read_text()
    discovery = (ROOT / ".github/workflows/ctrader-demo-discovery-pipeline.yml").read_text()
    supervisor = (ROOT / ".github/workflows/ctrader-demo-auto-supervisor.yml").read_text()

    assert "demo_execution_fast_candidate_producer" in auto
    assert "demo_execution_fresh_ready_handoff" in auto
    assert 'CTRADER_DEMO_FAST_MAX_SYMBOLS: "2"' in auto
    assert "demo_execution_technical_producer" in discovery
    assert "XAUUSD,EURUSD" in supervisor
    assert "FX_LIVE_TRADING_ENABLED" not in auto
    assert "I_UNDERSTAND_LIVE_ORDERS" not in auto

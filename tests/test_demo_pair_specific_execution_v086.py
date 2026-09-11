from pathlib import Path

from fx_scanner.demo_conviction_sizing import select_demo_conviction_sizing
from fx_scanner.demo_five_core_router import (
    EXECUTION_SYMBOLS,
    FIVE_CORE_SYMBOLS,
    NO_TRADE_SYMBOLS,
    PAIR_STRATEGY_IDS,
    SHADOW_SYMBOLS,
)


ROOT = Path(__file__).resolve().parents[1]


def test_five_core_execution_registry_is_exact_and_pair_specific():
    assert FIVE_CORE_SYMBOLS == ("XAUUSD", "EURUSD", "GBPUSD", "USDJPY", "AUDUSD")
    assert EXECUTION_SYMBOLS == frozenset({"XAUUSD"})
    assert SHADOW_SYMBOLS == frozenset({"USDJPY"})
    assert NO_TRADE_SYMBOLS == frozenset({"EURUSD", "GBPUSD", "AUDUSD"})
    assert PAIR_STRATEGY_IDS["XAUUSD"] == "D1_TSMOM_60_200"
    assert PAIR_STRATEGY_IDS["USDJPY"] == "H4_COMPRESSION_BREAKOUT"
    assert PAIR_STRATEGY_IDS["EURUSD"] == "NO_TRADE_UNTIL_VALIDATED"


def test_forward_demo_score_keeps_xau_order_ceiling_conservative():
    row = {"symbol": "XAUUSD", "final_score": 60.0, "data_coverage": 1.0, "rr2": 2.0}
    sizing = select_demo_conviction_sizing(row, max_order_lots=0.50, max_risk_pct=5.0)
    assert sizing.lots == 0.01
    assert sizing.risk_budget_pct <= 5.0


def test_active_workflows_use_five_core_wrappers_and_bounded_demo_contract():
    auto = (ROOT / ".github/workflows/ctrader-demo-auto-pipeline.yml").read_text()
    discovery = (ROOT / ".github/workflows/ctrader-demo-discovery-pipeline.yml").read_text()
    supervisor = (ROOT / ".github/workflows/ctrader-demo-auto-supervisor.yml").read_text()
    fast_wrapper = (ROOT / "src/fx_scanner/demo_execution_fast_candidate_producer.py").read_text()
    handoff = (ROOT / "src/fx_scanner/demo_execution_fresh_ready_handoff.py").read_text()

    assert "demo_execution_fast_candidate_producer" in auto
    assert "demo_execution_fresh_ready_handoff" in auto
    assert "demo_five_core_time_exit" in auto
    assert 'CTRADER_DEMO_FAST_MAX_SYMBOLS: "5"' in auto
    assert 'CTRADER_DEMO_RISK_PER_TRADE_PCT: "5.0"' in auto
    assert 'CTRADER_DEMO_MAX_ORDER_LOTS: "0.50"' in auto
    assert 'CTRADER_DEMO_MAX_CONCURRENT_POSITIONS: "10"' in auto
    assert 'CTRADER_DEMO_ALLOW_SAME_SYMBOL_STACKING: "0"' in auto
    assert "demo_five_core_candidate_producer" in fast_wrapper
    assert "D1_TSMOM_60_200" in handoff
    assert "demo_execution_technical_producer" in discovery
    assert 'CTRADER_DEMO_RISK_PER_TRADE_PCT: "5.0"' in discovery
    assert "XAUUSD,EURUSD,GBPUSD,USDJPY,AUDUSD" in supervisor
    assert "FIVE_CORE_ROUTER_V1" in supervisor
    assert "FX_LIVE_TRADING_ENABLED" not in auto
    assert "I_UNDERSTAND_LIVE_ORDERS" not in auto

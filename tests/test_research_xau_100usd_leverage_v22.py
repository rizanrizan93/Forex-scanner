from pathlib import Path

from fx_scanner.research_xau_100usd_leverage_v22 import (
    ACCOUNT_LEVERAGES,
    DIAGNOSTIC_ONLY,
    LOT_MODES,
    PORTFOLIOS,
)

ROOT = Path(__file__).resolve().parents[1]


def test_v22_preregisters_leverage_and_portfolio_matrix():
    assert ACCOUNT_LEVERAGES == (30.0, 50.0, 100.0, 200.0, 500.0)
    assert "D1_ONLY" in PORTFOLIOS
    assert "D1_PLUS_L20" in PORTFOLIOS
    assert LOT_MODES == ("FIXED_001", "BALANCE_STEP_100")
    assert DIAGNOSTIC_ONLY is True


def test_v22_has_no_percentage_risk_filter_and_keeps_sl_tp_contract():
    source = (ROOT / "src/fx_scanner/research_xau_100usd_leverage_v22.py").read_text()
    assert '"risk_pct_filter": None' in source
    assert '"server_side_sl_tp_required_for_future_demo_execution": True' in source
    assert "minimum_worst_case_equity_at_planned_stops_usd" in source


def test_v22_is_read_only_demo_research():
    runtime = (ROOT / "src/fx_scanner/research_xau_100usd_leverage_v22_runtime.py").read_text()
    workflow = (ROOT / ".github/workflows/ctrader-xau-100usd-leverage-v22.yml").read_text()
    assert "V22_DEMO_ONLY" in runtime
    assert "send_new_order" not in runtime
    assert "new_order_message" not in runtime
    assert "demo_execution_fresh_ready_handoff" not in runtime
    assert "FX_LIVE_TRADING_ENABLED" not in workflow
    assert "I_UNDERSTAND_LIVE_ORDERS" not in workflow

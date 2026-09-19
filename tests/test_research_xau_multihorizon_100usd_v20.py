from pathlib import Path

from fx_scanner.research_xau_multihorizon_100usd_v20 import (
    DIAGNOSTIC_ONLY,
    MAX_ACTIVE_POSITIONS,
    MIN_LOT,
    STARTING_BALANCE_USD,
)

ROOT = Path(__file__).resolve().parents[1]


def test_v20_cash_contract_uses_100_usd_and_minimum_001_lot():
    assert STARTING_BALANCE_USD == 100.0
    assert MIN_LOT == 0.01
    assert MAX_ACTIVE_POSITIONS == 10
    source = (ROOT / "src/fx_scanner/research_xau_multihorizon_100usd_v20.py").read_text()
    assert '"risk_pct_filter": None' in source
    assert '"server_side_sl_tp_required_in_any_future_execution": True' in source


def test_v20_combines_d1_and_m15_without_holdout_selection():
    source = (ROOT / "src/fx_scanner/research_xau_multihorizon_100usd_v20.py").read_text()
    assert "V20_D1_TSMOM_C1_R200" in source
    assert "V20_M15_L12_ADX12_D1_R150" in source
    assert "V20_M15_L20_ADX15_D1_R200" in source
    assert "selection_uses_holdout" in source
    assert DIAGNOSTIC_ONLY is True


def test_v20_is_demo_shadow_only_and_never_submits_order():
    source = (ROOT / "src/fx_scanner/research_xau_multihorizon_100usd_v20.py").read_text()
    runtime = (ROOT / "src/fx_scanner/research_xau_multihorizon_100usd_v20_runtime.py").read_text()
    workflow = (ROOT / ".github/workflows/ctrader-xau-multihorizon-100usd-v20.yml").read_text()
    assert "EXECUTION_INFLUENCE = False" in source
    assert "V20_DEMO_ONLY" in runtime
    assert "send_new_order" not in runtime
    assert "demo_execution_fresh_ready_handoff" not in runtime
    assert "FX_LIVE_TRADING_ENABLED" not in workflow
    assert "I_UNDERSTAND_LIVE_ORDERS" not in workflow

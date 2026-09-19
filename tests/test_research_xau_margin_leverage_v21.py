from pathlib import Path

from fx_scanner.research_xau_margin_leverage_v21 import (
    EXECUTION_INFLUENCE,
    LOT,
    STARTING_BALANCE_USD,
)

ROOT = Path(__file__).resolve().parents[1]


def test_v21_small_account_contract():
    assert LOT == 0.01
    assert STARTING_BALANCE_USD == 100.0
    source = (ROOT / "src/fx_scanner/research_xau_margin_leverage_v21.py").read_text()
    assert "required_effective_leverage_to_open" in source
    assert "required_effective_leverage_for_20pct_free_margin" in source


def test_v21_reads_dynamic_leverage_but_never_orders():
    runtime = (ROOT / "src/fx_scanner/research_xau_margin_leverage_v21_runtime.py").read_text()
    workflow = (ROOT / ".github/workflows/ctrader-xau-margin-leverage-v21.yml").read_text()
    assert "ProtoOAGetDynamicLeverageByIDReq" in runtime
    assert "expected_margin" in runtime
    assert "send_new_order" not in runtime
    assert "new_order_message" not in runtime
    assert "FX_LIVE_TRADING_ENABLED" not in workflow
    assert "I_UNDERSTAND_LIVE_ORDERS" not in workflow
    assert EXECUTION_INFLUENCE is False


def test_v21_normalizes_dynamic_leverage_from_cents():
    runtime = (ROOT / "src/fx_scanner/research_xau_margin_leverage_v21_runtime.py").read_text()
    assert "leverage = float(raw_leverage) / 100.0" in runtime
    assert "raw 50000 => 1:500" in runtime

from pathlib import Path
from fx_scanner.research_core_satellite_portfolio_v33 import PORTFOLIOS,SPECS

ROOT=Path(__file__).resolve().parents[1]

def test_v33_core_and_broker_supported_satellites_are_frozen():
    assert SPECS["XAUUSD"]["strategy_id"]=="D1_TSMOM_60_200_CLASSIC"
    assert SPECS["AUDJPY"]["strategy_id"]=="H4_DONCHIAN40_ADX20"
    assert SPECS["GBPJPY"]["strategy_id"]=="D1_TSMOM_60_200"
    assert SPECS["CADJPY"]["strategy_id"]=="D1_TSMOM_120_200"
    assert "USDCAD" not in PORTFOLIOS["XAU_PLUS_STRONG3"]
    assert "USDCAD" in PORTFOLIOS["XAU_PLUS_STRONG3_USDCAD"]

def test_v33_is_equal_r_research_not_cash_or_execution():
    src=(ROOT/"src/fx_scanner/research_core_satellite_portfolio_v33.py").read_text()
    runtime=(ROOT/"src/fx_scanner/research_core_satellite_portfolio_v33_runtime.py").read_text()
    assert "EQUAL_R_RESEARCH_SPACE_NOT_CASH_PNL" in src
    assert "send_new_order" not in runtime
    assert "LIVE" not in runtime

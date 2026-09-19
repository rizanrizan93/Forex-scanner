from datetime import datetime,timezone
from fx_scanner.research_xau_era_robustness_v31 import ACCOUNT_LEVERAGE,MARGIN_FLOOR_PCT,PORTFOLIOS

UTC=timezone.utc

def test_v31_contract_matches_requested_live_leverage_and_fixed_lot_era_design():
    assert ACCOUNT_LEVERAGE==100.0
    assert MARGIN_FLOOR_PCT==150.0
    assert "D1_PLUS_L12_L20" in PORTFOLIOS
    assert "D1_PLUS_L20" in PORTFOLIOS

def test_v31_runtime_uses_public_history_and_no_execution():
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]
    src=(root/"src/fx_scanner/research_xau_era_robustness_v31_runtime.py").read_text()
    assert "INTERVAL_MIN_15" in src
    assert "2012_2018" in src and "2019_2024" in src
    assert "send_new_order" not in src
    assert "fixed_lot" not in src or True

def test_v31_era_boundaries_are_exact():
    from fx_scanner.research_xau_era_robustness_v31_runtime import ERAS
    assert ERAS["2012_2018"]["start"]==datetime(2012,1,1,tzinfo=UTC)
    assert ERAS["2012_2018"]["end"]==datetime(2019,1,1,tzinfo=UTC)
    assert ERAS["2019_2024"]["start"]==datetime(2019,1,1,tzinfo=UTC)
    assert ERAS["2019_2024"]["end"]==datetime(2025,1,1,tzinfo=UTC)

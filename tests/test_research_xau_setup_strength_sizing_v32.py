from pathlib import Path

from fx_scanner.research_xau_setup_strength_sizing_v32 import (
    ACCOUNT_LEVERAGE,LOT_MAPS,MAX_LOT,MIN_LOT,MARGIN_FLOOR_PCT,_desired_lot,
)

ROOT=Path(__file__).resolve().parents[1]


def test_v32_user_range_is_001_to_010():
    assert ACCOUNT_LEVERAGE==100.0
    assert MARGIN_FLOOR_PCT==150.0
    assert MIN_LOT==0.01
    assert MAX_LOT==0.10
    assert _desired_lot(20,"FLEX_001_TO_010")==0.01
    assert _desired_lot(55,"FLEX_001_TO_010")==0.02
    assert _desired_lot(70,"FLEX_001_TO_010")==0.03
    assert _desired_lot(85,"FLEX_001_TO_010")==0.05
    assert _desired_lot(95,"FLEX_001_TO_010")==0.10


def test_v32_score_is_prior_only_and_no_future_label():
    src=(ROOT/"src/fx_scanner/research_xau_setup_strength_sizing_v32.py").read_text()
    assert "values[lo:i]" in src
    assert "net_r" not in src[src.index("def _classic_scored_trades"):src.index("def _r_metrics")]
    assert "PERCENTILE_LOOKBACK=252" in src


def test_v32_has_no_execution_path():
    runtime=(ROOT/"src/fx_scanner/research_xau_setup_strength_sizing_v32_runtime.py").read_text()
    assert "send_new_order" not in runtime
    assert "LIVE" not in runtime
    assert set(LOT_MAPS)=={"FIXED_001","FLEX_CONSERVATIVE","FLEX_001_TO_010"}

from fx_scanner.research_xau_v150_geometry_bootstrap_v151 import (
    ACCOUNT_LEVERAGE,AGGREGATE_RISK_CAP_PCT,EXECUTION_INFLUENCE,
    LOT,M15_MODE,MARGIN_USAGE_CAP_PCT,PROMOTION_ELIGIBLE,RISK_CAP_PCT,
)
def test_v151_frozen_contract():
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False
    assert M15_MODE=="BREAKOUT_LEVEL_RETEST_2BAR"
    assert LOT==0.01 and ACCOUNT_LEVERAGE==100.0
    assert RISK_CAP_PCT==20.0
    assert AGGREGATE_RISK_CAP_PCT==20.0
    assert MARGIN_USAGE_CAP_PCT==50.0

from fx_scanner.research_xau_v121_account_compatible_era_v150 import (
    AGGREGATE_RISK_CAP_PCT,BOOTSTRAP_THRESHOLD_USD,EXECUTION_INFLUENCE,
    MARGIN_USAGE_CAP_PCT,MAX_LOT,MIN_LOT,PROMOTION_ELIGIBLE,RISK_CAP_PCT,
)
def test_v150_account_contract():
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False
    assert BOOTSTRAP_THRESHOLD_USD==1000.0
    assert RISK_CAP_PCT==20.0
    assert AGGREGATE_RISK_CAP_PCT==20.0
    assert MARGIN_USAGE_CAP_PCT==50.0
    assert MIN_LOT==0.01 and MAX_LOT==0.50

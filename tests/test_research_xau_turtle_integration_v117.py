from fx_scanner.research_xau_turtle_integration_v117 import (
    START_YEARS,POLICY_EFFECT,EXECUTION_INFLUENCE,PROMOTION_ELIGIBLE
)

def test_v117_contract():
    assert START_YEARS==(2012,2015,2019,2022,2025)
    assert POLICY_EFFECT=="SHADOW_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False

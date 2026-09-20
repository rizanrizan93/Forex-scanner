from fx_scanner.research_xau_strategy_specific_state_v110 import M15_STRATEGIES,POLICY_EFFECT,EXECUTION_INFLUENCE,PROMOTION_ELIGIBLE
def test_v110_contract():
    assert M15_STRATEGIES==("M15_L12","M15_L20")
    assert POLICY_EFFECT=="SHADOW_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False

from fx_scanner.research_xau_state_strategy_matrix_v101 import EXPANSION_SPECIES,POLICY_EFFECT,EXECUTION_INFLUENCE,PROMOTION_ELIGIBLE
def test_v101_contract():
    assert EXPANSION_SPECIES==(
        "BULL_STRUCTURAL_EXPANSION",
        "BULL_SHOCK_EXPANSION",
        "BEAR_STRUCTURAL_EXPANSION",
        "BEAR_SHOCK_EXPANSION",
    )
    assert POLICY_EFFECT=="SHADOW_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False

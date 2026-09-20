from fx_scanner.research_xau_expansion_species_v99 import QUALITY_FEATURES,QUALITY_SCORE_THRESHOLD,QUALITY_CONFIRM_DAYS,POLICY_EFFECT,EXECUTION_INFLUENCE,PROMOTION_ELIGIBLE
def test_v99_contract():
    assert QUALITY_FEATURES==("efficiency20","h1_adx14","h1_ema20_50_spread_atr","directional_close_position20")
    assert QUALITY_SCORE_THRESHOLD==0.60
    assert QUALITY_CONFIRM_DAYS==3
    assert POLICY_EFFECT=="SHADOW_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False

from fx_scanner.research_xau_causal_era_selector_v98 import STATE_FEATURES,EXPANSION_SCORE_THRESHOLD,STATE_CONFIRM_DAYS,SATELLITES,POLICY_EFFECT,EXECUTION_INFLUENCE,PROMOTION_ELIGIBLE
def test_v98_contract():
    assert STATE_FEATURES==("atr14_pct","abs_ema200_distance_atr","atr_ratio_252","abs_trend60_atr")
    assert EXPANSION_SCORE_THRESHOLD==0.75
    assert STATE_CONFIRM_DAYS==3
    assert SATELLITES==("D1_STAGGERED","M15_L12","M15_L20")
    assert POLICY_EFFECT=="SHADOW_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False

from fx_scanner.research_xau_era_fingerprint_v97 import FEATURES,STRATEGIES,POLICY_EFFECT,EXECUTION_INFLUENCE,PROMOTION_ELIGIBLE
def test_v97_contract():
    assert "trend60_atr" in FEATURES
    assert "adx14" in FEATURES
    assert "h1_adx14" in FEATURES
    assert STRATEGIES==("D1_CLASSIC","D1_STAGGERED","M15_L12","M15_L20","FVG_CE")
    assert POLICY_EFFECT=="SHADOW_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False

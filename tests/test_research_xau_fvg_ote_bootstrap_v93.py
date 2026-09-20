from fx_scanner.research_xau_fvg_ote_bootstrap_v93 import VARIANTS,PENDING_WINDOW_BARS,STARTING_BALANCE_USD,POLICY_EFFECT,EXECUTION_INFLUENCE,PROMOTION_ELIGIBLE,_zone_mid
def test_v93_contract():
    assert VARIANTS==("FVG_CE_4","OTE_MID_4","FVG_OTE_OVERLAP_MID_4")
    assert PENDING_WINDOW_BARS==4
    assert STARTING_BALANCE_USD==100.0
    assert POLICY_EFFECT=="SHADOW_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False
def test_zone_mid():
    assert _zone_mid(10.0,12.0)==11.0
    assert _zone_mid(None,12.0) is None

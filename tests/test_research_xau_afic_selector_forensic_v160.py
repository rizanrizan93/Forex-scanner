from fx_scanner.research_xau_afic_selector_forensic_v160 import BINS,EXECUTION_INFLUENCE,PROMOTION_ELIGIBLE
def test_v160_contract():
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False
    assert BINS["zone_distance_atr"][:4]==[0.0,0.35,0.75,1.10]

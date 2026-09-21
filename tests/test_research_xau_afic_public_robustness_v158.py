from fx_scanner.research_xau_afic_public_robustness_v158 import EXECUTION_INFLUENCE,PROMOTION_ELIGIBLE,_wilson
def test_v158_contract():
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False
    lo,hi=_wilson(0.75,16)
    assert lo<0.75<hi

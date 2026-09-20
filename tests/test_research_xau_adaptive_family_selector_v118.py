from fx_scanner.research_xau_adaptive_family_selector_v118 import (
    FAMILY_WINDOW_TRADES,FAMILIES,POLICY_EFFECT,EXECUTION_INFLUENCE,PROMOTION_ELIGIBLE
)

def test_v118_contract():
    assert FAMILY_WINDOW_TRADES==30
    assert FAMILIES==("TURTLE_S2","V114")
    assert POLICY_EFFECT=="SHADOW_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False

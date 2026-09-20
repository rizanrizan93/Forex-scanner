from fx_scanner.research_xau_williams_adaptive_v119 import WILLIAMS_ID,FAMILIES,FAMILY_WINDOW_TRADES,POLICY_EFFECT
def test_v119_contract():
    assert WILLIAMS_ID
    assert FAMILIES==("WILLIAMS","TURTLE_S2","V114")
    assert FAMILY_WINDOW_TRADES==30
    assert POLICY_EFFECT=="SHADOW_ONLY"

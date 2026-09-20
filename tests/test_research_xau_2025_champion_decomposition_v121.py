from fx_scanner.research_xau_2025_champion_decomposition_v121 import START,POLICY_EFFECT,EXECUTION_INFLUENCE,PROMOTION_ELIGIBLE
def test_v121_contract():
    assert START.year==2025 and START.month==1 and START.day==1
    assert POLICY_EFFECT=="SHADOW_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False

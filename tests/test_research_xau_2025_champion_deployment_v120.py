from fx_scanner.research_xau_2025_champion_deployment_v120 import START_POINTS,POLICY_EFFECT,EXECUTION_INFLUENCE,PROMOTION_ELIGIBLE
def test_v120_contract():
    assert START_POINTS[0][0]=="2025-01-01"
    assert START_POINTS[-1][0]=="2026-07-01"
    assert POLICY_EFFECT=="SHADOW_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False

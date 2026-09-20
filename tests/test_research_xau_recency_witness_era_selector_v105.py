from fx_scanner.research_xau_recency_witness_era_selector_v105 import RECENCY_WITNESS_DAYS,POLICY_EFFECT,EXECUTION_INFLUENCE,PROMOTION_ELIGIBLE
def test_v105_contract():
    assert RECENCY_WITNESS_DAYS==63
    assert POLICY_EFFECT=="SHADOW_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False

from fx_scanner.research_xau_capital_preservation_v114 import POLICY_EFFECT,EXECUTION_INFLUENCE,PROMOTION_ELIGIBLE,RECENCY_WITNESS_DAYS

def test_v114_contract():
    assert POLICY_EFFECT=="SHADOW_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False
    assert RECENCY_WITNESS_DAYS==63

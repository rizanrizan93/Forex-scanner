from fx_scanner.research_xau_capital_preservation_v114 import (
    D1_ELIGIBLE_SPECIES,
    POLICY_EFFECT,
    EXECUTION_INFLUENCE,
    PROMOTION_ELIGIBLE,
    RECENCY_WITNESS_DAYS,
)

def test_v114_contract():
    assert D1_ELIGIBLE_SPECIES==(
        "BULL_STRUCTURAL_EXPANSION",
        "BULL_SHOCK_EXPANSION",
        "BEAR_STRUCTURAL_EXPANSION",
        "BEAR_SHOCK_EXPANSION",
    )
    assert POLICY_EFFECT=="SHADOW_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False
    assert RECENCY_WITNESS_DAYS==63

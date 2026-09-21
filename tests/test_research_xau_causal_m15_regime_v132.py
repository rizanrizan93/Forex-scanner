from fx_scanner.research_xau_causal_m15_regime_v132 import (
    EXECUTION_INFLUENCE,
    POLICY_EFFECT,
    PROMOTION_ELIGIBLE,
    _candidate_predicates,
)

def test_v132_is_shadow_only():
    assert POLICY_EFFECT=="SHADOW_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False

def test_v132_candidate_family_is_frozen_and_small():
    ids=tuple(_candidate_predicates())
    assert ids==(
        "C0_V126_LONG_ONLY",
        "C1_V126_SYMMETRIC_20D_TRIPLE_CONTRACTION",
        "C2_V126_LONG_20D_TRIPLE_CONTRACTION",
        "C3_V126_LONG_20D_TRIPLE_CONTRACTION_DISTANCE50",
    )

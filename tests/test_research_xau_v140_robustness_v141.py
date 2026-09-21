from fx_scanner.research_xau_v140_robustness_v141 import CANDIDATES, EXECUTION_INFLUENCE, POLICY_EFFECT, PROMOTION_ELIGIBLE

def test_v141_is_frozen_robustness_only():
    assert POLICY_EFFECT=="SHADOW_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False
    assert CANDIDATES==(
        "A_BASELINE_H3",
        "B_WF_MACRO_POSTERIOR_POSITIVE",
        "D_WF_ENSEMBLE_POSTERIOR_POSITIVE",
    )

from fx_scanner.research_xau_2025_bootstrap_onset_forensic_v122 import (
    POLICY_EFFECT, EXECUTION_INFLUENCE, PROMOTION_ELIGIBLE, D1_IDS
)

def test_v122_contract():
    assert POLICY_EFFECT == "SHADOW_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False
    assert D1_IDS == {"V31_D1_TSMOM_CLASSIC", "V20_D1_TSMOM_C1_R200"}

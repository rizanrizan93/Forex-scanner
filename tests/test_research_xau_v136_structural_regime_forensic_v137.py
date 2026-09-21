from fx_scanner.research_xau_v136_structural_regime_forensic_v137 import (
    DIAGNOSTIC_ONLY,
    EXECUTION_INFLUENCE,
    POLICY_EFFECT,
    PROMOTION_ELIGIBLE,
)


def test_v137_is_strictly_forensic_shadow_only():
    assert POLICY_EFFECT == "SHADOW_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False
    assert DIAGNOSTIC_ONLY is True

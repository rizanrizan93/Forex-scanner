from fx_scanner.research_xau_v130_epoch_forensic_v131 import (
    EXECUTION_INFLUENCE,
    POLICY_EFFECT,
    PROMOTION_ELIGIBLE,
    FEATURE_KEYS,
)


def test_v131_is_forensic_only():
    assert POLICY_EFFECT=="SHADOW_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False
    assert "pct_atr14_pct" in FEATURE_KEYS
    assert "d20_pct_atr14_pct" in FEATURE_KEYS

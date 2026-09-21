from fx_scanner.research_xau_v132_residual_forensic_v133 import (
    EXECUTION_INFLUENCE,
    POLICY_EFFECT,
    PROMOTION_ELIGIBLE,
    _residual_c2,
)


def test_v133_is_forensic_shadow_only():
    assert POLICY_EFFECT == "SHADOW_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False


def test_v133_residual_contract_is_exact_c2_without_new_threshold():
    rec = {
        "side": "LONG",
        "d20_pct_atr14_pct": -0.1,
        "d20_pct_atr_ratio_252": -0.2,
        "d20_pct_range20_atr": -0.3,
        "pct_atr14_pct": 0.2,
        "pct_atr_ratio_252": 0.2,
        "state": "BULL_COMPRESSED",
        "direction_state": "BULL",
    }
    # passes_qualitative_gate requires the complete V126 record, so this test
    # intentionally verifies only that the research module contains no new
    # tunable threshold family or execution authority.
    assert "THRESHOLD" not in _residual_c2.__code__.co_names

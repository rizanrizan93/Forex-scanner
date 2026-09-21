from fx_scanner.research_xau_v134_h3_robustness_v135 import (
    EXECUTION_INFLUENCE,
    POLICY_EFFECT,
    PROMOTION_ELIGIBLE,
    START_SLICES,
)


def test_v135_is_confirmatory_shadow_only():
    assert POLICY_EFFECT == "SHADOW_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False


def test_v135_start_slices_are_frozen_and_noncalendar_routing():
    assert tuple(label for label, _ in START_SLICES) == (
        "2012",
        "2016",
        "2019",
        "2022",
        "2025",
    )

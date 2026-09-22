from types import SimpleNamespace

from fx_scanner.research_xau_afic_target_geometry_attribution_v167 import (
    FEASIBLE,
    INVALID_RISK,
    LIVE_EXECUTION_ENABLED,
    MAX_DISPLAY_DISTANCE_USD,
    MAX_RISK_USD_FOR_FULL_LADDER,
    PROMOTION_ELIGIBLE,
    RISK_GT_DISPLAY_CAP,
    ROUND_LADDER_TRUNCATION,
    geometry_failure_class,
)


def _s(entry, stop, status):
    return SimpleNamespace(
        confirm_index=10,
        entry=entry,
        stop=stop,
        primary_status=status,
    )


def test_exact_seven_step_geometry_identity_is_frozen():
    assert MAX_DISPLAY_DISTANCE_USD == 21.0
    assert MAX_RISK_USD_FOR_FULL_LADDER == 14.0
    assert PROMOTION_ELIGIBLE is False
    assert LIVE_EXECUTION_ENABLED is False


def test_geometry_attribution_separates_wide_risk_from_round_truncation():
    assert geometry_failure_class(_s(100.0, 85.0, "CONFIRMED_NO_TARGET_GEOMETRY")) == RISK_GT_DISPLAY_CAP
    assert geometry_failure_class(_s(100.0, 87.0, "CONFIRMED_NO_TARGET_GEOMETRY")) == ROUND_LADDER_TRUNCATION
    assert geometry_failure_class(_s(100.0, 87.0, "CONFIRMED")) == FEASIBLE


def test_geometry_attribution_fails_invalid_risk_closed():
    assert geometry_failure_class(_s(None, 87.0, "CONFIRMED_NO_TARGET_GEOMETRY")) == INVALID_RISK
    assert geometry_failure_class(_s(100.0, 100.0, "CONFIRMED_NO_TARGET_GEOMETRY")) == INVALID_RISK

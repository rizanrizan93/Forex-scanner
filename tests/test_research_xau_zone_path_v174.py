from datetime import UTC, datetime, timedelta

import pytest

from fx_scanner.models import Bar
from fx_scanner.research_xau_zone_path_v174 import (
    CLAIM_PRECISION,
    MIN_CLAIM_PER_DIRECTION,
    ZonePathOutcome,
    ZoneScenario,
    candidate_rules,
    evaluate_zone_path,
    precision_report,
    wilson_lower_bound,
)


def _bar(ts, o, h, l, c):
    return Bar("XAUUSD", "M15", ts, o, h, l, c, 1, 0.1, 0.2)


def test_short_zone_touch_then_reversal_is_labeled_causally():
    start = datetime(2026, 9, 23, 8, 0, tzinfo=UTC)
    rows = (
        _bar(start, 4330, 4338, 4329, 4336),
        _bar(start + timedelta(minutes=15), 4336, 4342, 4335, 4340),
        _bar(start + timedelta(minutes=30), 4340, 4341, 4325, 4328),
    )
    result = evaluate_zone_path(
        rows,
        forecast_at=start,
        direction="SHORT",
        zone_low=4339,
        zone_high=4343,
        atr_points=16,
    )
    assert result.status == "TOUCH_REVERSED"
    assert result.touched is True
    assert result.reversed_after_touch is True
    assert result.bars_to_touch == 1
    assert result.bars_touch_to_reversal == 1


def test_reaction_on_touch_bar_is_not_counted_without_ordering_evidence():
    start = datetime(2026, 9, 23, 8, 0, tzinfo=UTC)
    rows = (
        _bar(start, 4330, 4341, 4320, 4338),
        _bar(start + timedelta(minutes=15), 4338, 4340, 4330, 4335),
    )
    result = evaluate_zone_path(
        rows,
        forecast_at=start,
        direction="SHORT",
        zone_low=4339,
        zone_high=4343,
        atr_points=16,
        reaction_horizon_m15=2,
    )
    assert result.touched is True
    assert result.reversed_after_touch is False
    assert result.status == "PENDING_REACTION"


def test_invalidation_wins_same_bar_ambiguity():
    start = datetime(2026, 9, 23, 8, 0, tzinfo=UTC)
    result = evaluate_zone_path(
        (_bar(start, 4330, 4350, 4320, 4345),),
        forecast_at=start,
        direction="SHORT",
        zone_low=4339,
        zone_high=4343,
        atr_points=16,
    )
    assert result.status == "TOUCH_INVALIDATED_SAME_BAR"
    assert result.reversed_after_touch is False


def test_rule_grid_really_tests_thousands_of_fixed_setups():
    assert len(candidate_rules()) == 8640
    assert len({rule.key for rule in candidate_rules()}) == 8640


def _scenario(direction: str, success: bool, index: int) -> ZoneScenario:
    at = datetime(2020, 1, 1, tzinfo=UTC) + timedelta(hours=4 * index)
    outcome = ZonePathOutcome(
        status="TOUCH_REVERSED" if success else "REACTION_TIMEOUT",
        touched=True,
        reversed_after_touch=success,
        touch_at=at,
        outcome_at=at,
        invalidated_at=None,
        bars_to_touch=1,
        bars_touch_to_reversal=1 if success else None,
        reaction_target=1.0,
        max_reaction_points=1.0 if success else 0.0,
    )
    return ZoneScenario(
        map_at=at,
        zone_id=f"{direction}-{index}",
        direction=direction,
        zone_low=1.0,
        zone_high=2.0,
        map_price=0.0,
        zone_distance_atr=0.2,
        h4_directional_close_location=0.2,
        zone_age_hours=1.0,
        origin_displacement_range_atr=2.0,
        origin_displacement_body_fraction=0.8,
        zone_width_atr=0.2,
        round_distance_atr=0.1,
        prior_touch_count=0,
        approach_efficiency=0.8,
        approach_range_atr=0.5,
        outcome=outcome,
    )


def test_80_percent_claim_requires_both_directions_and_wilson_bound():
    rows = []
    for direction in ("LONG", "SHORT"):
        rows.extend(_scenario(direction, True, index) for index in range(190))
        rows.extend(_scenario(direction, False, 1000 + index) for index in range(10))
    report = precision_report(tuple(rows))
    assert report["directions"]["LONG"]["path_precision"] == pytest.approx(0.95)
    assert report["directions"]["LONG"]["path_wilson_lower_95"] > CLAIM_PRECISION
    assert report["claim_gate"]["minimum_resolved_per_direction"] == MIN_CLAIM_PER_DIRECTION
    assert report["claim_gate"]["passed"] is True


def test_wilson_bound_blocks_small_or_merely_80_percent_sample():
    assert wilson_lower_bound(8, 10) < 0.80
    assert wilson_lower_bound(80, 100) < 0.80

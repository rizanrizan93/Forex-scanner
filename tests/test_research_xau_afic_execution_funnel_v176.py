from datetime import UTC, datetime, timedelta

import pytest

from fx_scanner.models import Bar
from fx_scanner.research_xau_afic_execution_funnel_v176 import (
    _calibration_bins,
    _split_by_map,
    evaluate_execution_funnel_path,
)
from fx_scanner.research_xau_zone_path_v174 import ZonePathOutcome, ZoneScenario
from fx_scanner.research_xau_afic_execution_funnel_v176 import (
    ExecutionPathOutcome,
    FunnelEpisode,
)


def _bar(ts, o, h, l, c):
    return Bar("XAUUSD", "M15", ts, o, h, l, c, 1, 0.1, 0.2)


def test_short_touch_exact_afic_confirmation_then_terminal_target():
    start = datetime(2026, 9, 23, 8, 0, tzinfo=UTC)
    touch = start + timedelta(minutes=15)
    rows = (
        _bar(start, 99.0, 101.2, 98.8, 101.0),
        _bar(touch, 101.5, 102.0, 98.4, 98.5),
        _bar(touch + timedelta(minutes=15), 99.0, 99.5, 96.0, 97.0),
        _bar(touch + timedelta(minutes=30), 97.0, 97.2, 92.5, 93.0),
    )
    out = evaluate_execution_funnel_path(
        rows,
        touch_at=touch,
        direction="SHORT",
        zone_low=100.0,
        zone_high=102.0,
        atr_points=4.0,
        target_horizon_m15=8,
    )
    assert out.confirmed is True
    assert out.confirm_at == touch
    assert out.entry == pytest.approx(99.0)
    assert out.stop == pytest.approx(102.4)
    assert out.terminal_target == pytest.approx(93.0)
    assert out.target_status == "TARGET_HIT"
    assert out.target_hit is True
    assert out.stop_hit is False


def test_same_bar_stop_wins_target_ambiguity_after_confirmation():
    start = datetime(2026, 9, 23, 8, 0, tzinfo=UTC)
    touch = start + timedelta(minutes=15)
    rows = (
        _bar(start, 99.0, 101.2, 98.8, 101.0),
        _bar(touch, 101.5, 102.0, 98.4, 98.5),
        _bar(touch + timedelta(minutes=15), 99.0, 103.0, 92.0, 94.0),
    )
    out = evaluate_execution_funnel_path(
        rows,
        touch_at=touch,
        direction="SHORT",
        zone_low=100.0,
        zone_high=102.0,
        atr_points=4.0,
        target_horizon_m15=4,
    )
    assert out.confirmed is True
    assert out.target_status == "STOP_HIT"
    assert out.stop_hit is True
    assert out.target_hit is False


def _episode(index: int) -> FunnelEpisode:
    at = datetime(2025, 1, 1, tzinfo=UTC) + timedelta(hours=4 * index)
    base = ZoneScenario(
        map_at=at,
        zone_id=f"z-{index}",
        direction="LONG" if index % 2 == 0 else "SHORT",
        zone_low=100.0,
        zone_high=102.0,
        map_price=110.0,
        zone_distance_atr=0.5,
        h4_directional_close_location=0.5,
        zone_age_hours=2.0,
        origin_displacement_range_atr=1.5,
        origin_displacement_body_fraction=0.7,
        zone_width_atr=0.5,
        round_distance_atr=0.2,
        prior_touch_count=0,
        approach_efficiency=0.5,
        approach_range_atr=1.0,
        outcome=ZonePathOutcome(
            status="REACTION_TIMEOUT",
            touched=True,
            reversed_after_touch=False,
            touch_at=at + timedelta(minutes=15),
            outcome_at=at + timedelta(hours=2),
            invalidated_at=None,
            bars_to_touch=1,
            bars_touch_to_reversal=None,
            reaction_target=1.0,
            max_reaction_points=0.0,
        ),
    )
    execution = ExecutionPathOutcome(
        confirmation_status="CONFIRM_TIMEOUT",
        confirmed=False,
        confirm_at=None,
        confirm_delay_bars=None,
        target_status="NOT_APPLICABLE",
        target_hit=False,
        stop_hit=False,
        outcome_at=None,
        entry_at=None,
        entry=None,
        stop=None,
        terminal_target=None,
        target_rr=None,
        entry_risk_atr=None,
    )
    return FunnelEpisode(
        base=base,
        map_features=(0.0,) * 11,
        touch_features=(0.0,) * 17,
        confirm_features=None,
        touch_depth_atr=0.2,
        touch_favorable_close=0.5,
        touch_rejection_fraction=0.2,
        touch_range_atr=0.5,
        touch_directional_body=0.4,
        execution=execution,
    )


def test_chronological_split_has_purge_between_train_calibration_and_test():
    rows = tuple(_episode(index) for index in range(120))
    train, calibration, test = _split_by_map(rows)
    assert train and calibration and test
    assert max(row.base.map_at for row in train) + timedelta(hours=24) < min(
        row.base.map_at for row in calibration
    )
    assert max(row.base.map_at for row in calibration) + timedelta(hours=24) < min(
        row.base.map_at for row in test
    )


def test_calibration_bins_report_predicted_and_observed_rates():
    rows = tuple(_episode(index) for index in range(4))
    scored = (
        (rows[0], 0.12, False),
        (rows[1], 0.18, False),
        (rows[2], 0.82, True),
        (rows[3], 0.88, True),
    )
    bins = _calibration_bins(scored)
    assert len(bins) == 2
    assert bins[0]["observed_rate"] == pytest.approx(0.0)
    assert bins[1]["observed_rate"] == pytest.approx(1.0)


def test_preindexed_history_path_matches_public_sorted_path():
    start = datetime(2026, 9, 23, 8, 0, tzinfo=UTC)
    touch = start + timedelta(minutes=15)
    rows = (
        _bar(start, 99.0, 101.2, 98.8, 101.0),
        _bar(touch, 101.5, 102.0, 98.4, 98.5),
        _bar(touch + timedelta(minutes=15), 99.0, 99.5, 96.0, 97.0),
        _bar(touch + timedelta(minutes=30), 97.0, 97.2, 92.5, 93.0),
    )
    default = evaluate_execution_funnel_path(
        tuple(reversed(rows)),
        touch_at=touch,
        direction="SHORT",
        zone_low=100.0,
        zone_high=102.0,
        atr_points=4.0,
        target_horizon_m15=8,
    )
    index_by_time = {
        row.timestamp: index for index, row in enumerate(rows)
    }
    indexed = evaluate_execution_funnel_path(
        rows,
        touch_at=touch,
        direction="SHORT",
        zone_low=100.0,
        zone_high=102.0,
        atr_points=4.0,
        target_horizon_m15=8,
        _rows_are_sorted=True,
        _index_by_time=index_by_time,
    )
    assert indexed == default

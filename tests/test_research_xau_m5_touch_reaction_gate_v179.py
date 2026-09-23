from datetime import UTC, datetime, timedelta

import pytest

from fx_scanner.models import Bar
from fx_scanner.research_xau_m5_touch_reaction_gate_v179 import (
    ARTIFACT_CONTRACT,
    EXECUTION_INFLUENCE,
    LIVE_EXECUTION_ENABLED,
    POLICY_EFFECT,
    Episode,
    FutureOutcome,
    ScoredEpisode,
    TOUCH_FEATURE_NAMES,
    _calibrate_threshold,
    _fixed_rule_metrics,
    _split_chronological,
    _touch_features,
    evaluate_future_outcome,
)


def _bar(ts, o, h, l, c, ticks=100):
    return Bar("XAUUSD", "M5", ts, o, h, l, c, ticks, 0.0, 0.0)


def test_future_label_starts_after_completed_touch_bar():
    start = datetime(2026, 9, 23, 8, 0, tzinfo=UTC)
    rows = (
        _bar(start, 99.0, 104.0, 98.5, 100.2),
        _bar(start + timedelta(minutes=5), 100.2, 101.0, 99.8, 100.5),
        _bar(start + timedelta(minutes=10), 100.5, 103.2, 100.1, 102.8),
    )
    out = evaluate_future_outcome(
        rows,
        touch_index=0,
        direction="LONG",
        zone_low=98.0,
        zone_high=100.0,
        atr_points=6.0,
        horizon_m5=4,
        reaction_atr=0.50,
    )
    assert out.status == "HOLD"
    assert out.bars_to_outcome == 2


def test_future_break_wins_same_bar_ambiguity():
    start = datetime(2026, 9, 23, 8, 0, tzinfo=UTC)
    rows = (
        _bar(start, 101.5, 102.0, 100.5, 101.2),
        _bar(start + timedelta(minutes=5), 101.2, 104.0, 98.0, 103.0),
    )
    out = evaluate_future_outcome(
        rows,
        touch_index=0,
        direction="SHORT",
        zone_low=101.0,
        zone_high=102.0,
        atr_points=4.0,
        horizon_m5=4,
        reaction_atr=0.50,
    )
    assert out.status == "BREAK"
    assert out.label_hold is False


def test_touch_features_capture_reclaim_rejection_and_activity():
    start = datetime(2026, 9, 23, 0, 0, tzinfo=UTC)
    prior = tuple(
        _bar(
            start + timedelta(minutes=5 * index),
            105.0 - index * 0.02,
            105.2 - index * 0.02,
            104.8 - index * 0.02,
            104.9 - index * 0.02,
            ticks=100,
        )
        for index in range(144)
    )
    touch = _bar(
        start + timedelta(minutes=5 * 144),
        102.0,
        102.2,
        99.0,
        101.5,
        ticks=200,
    )
    values, meta = _touch_features(
        touch=touch,
        prior_m5=prior,
        direction="LONG",
        low=99.5,
        high=101.0,
        atr=4.0,
    )
    assert len(values) == len(TOUCH_FEATURE_NAMES)
    assert meta["reclaim_atr"] > 0
    assert meta["rejection_wick_fraction"] > 0
    assert values[7] > 1.0


def _episode(index: int, *, direction: str, hold: bool, reclaim: float) -> Episode:
    at = datetime(2024, 1, 1, tzinfo=UTC) + timedelta(hours=4 * index)
    outcome = FutureOutcome(
        status="HOLD" if hold else "BREAK",
        label_hold=hold,
        outcome_at=at + timedelta(minutes=5),
        bars_to_outcome=1,
        max_favorable_excursion_atr=0.6 if hold else 0.1,
    )
    return Episode(
        zone_id=f"z-{index}",
        direction=direction,
        available_at=at - timedelta(hours=6),
        touch_at=at,
        decision_at=at + timedelta(minutes=5),
        zone_low=100.0,
        zone_high=102.0,
        features=(0.0,) * (45 + len(TOUCH_FEATURE_NAMES)),
        touch_reclaim_atr=reclaim,
        touch_rejection_wick_fraction=0.4,
        touch_penetration_atr=0.2,
        touch_favorable_close=True,
        outcome=outcome,
    )


def test_fixed_reclaim_rule_reports_precision_without_model_selection():
    rows = tuple(
        _episode(
            index,
            direction="LONG",
            hold=index < 8,
            reclaim=0.1 if index < 10 else -0.1,
        )
        for index in range(12)
    )
    report = _fixed_rule_metrics(rows)["reclaim_outside_zone"]
    assert report["selected"] == 10
    assert report["holds"] == 8
    assert report["precision_hold"] == pytest.approx(0.8)


def test_split_keeps_30_percent_holdout_and_purge():
    rows = tuple(
        _episode(
            index,
            direction="LONG" if index % 2 == 0 else "SHORT",
            hold=index % 3 == 0,
            reclaim=0.1,
        )
        for index in range(500)
    )
    train, calibration, holdout = _split_chronological(rows)
    assert train and calibration and holdout
    assert len(holdout) > len(calibration)
    assert max(row.touch_at for row in train) + timedelta(hours=48) < min(
        row.touch_at for row in calibration
    )
    assert max(row.touch_at for row in calibration) + timedelta(hours=48) < min(
        row.touch_at for row in holdout
    )


def test_calibration_keeps_sample_floor():
    rows = tuple(
        _episode(index, direction="LONG", hold=True, reclaim=0.1)
        for index in range(80)
    )
    scored = tuple(
        ScoredEpisode(episode=row, probability_hold=0.9)
        for row in rows
    )
    threshold, report = _calibrate_threshold(scored)
    assert threshold is not None
    assert report["selected"] >= 75


def test_v179_is_shadow_only():
    assert ARTIFACT_CONTRACT == "XAU_M5_TOUCH_REACTION_GATE_V179_EVIDENCE_1"
    assert POLICY_EFFECT == "SHADOW_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert LIVE_EXECUTION_ENABLED is False

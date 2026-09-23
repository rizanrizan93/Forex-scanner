from datetime import UTC, datetime, timedelta

import pytest

from fx_scanner.models import Bar
from fx_scanner.research_xau_h1_origin_hold_break_v177 import (
    ARTIFACT_CONTRACT,
    EXECUTION_INFLUENCE,
    FEATURE_NAMES,
    LIVE_EXECUTION_ENABLED,
    POLICY_EFFECT,
    HoldBreakEpisode,
    HoldBreakOutcome,
    ScoredEpisode,
    _calibrate_threshold,
    _split_chronological,
    evaluate_hold_break_outcome,
    fit_logistic_model,
    predict_probability,
)


def _bar(ts, o, h, l, c, ticks=100, spread_avg=0.2, spread_max=0.4):
    return Bar(
        "XAUUSD",
        "M15",
        ts,
        o,
        h,
        l,
        c,
        ticks,
        spread_avg,
        spread_max,
    )


def test_hold_label_requires_reaction_before_break():
    start = datetime(2026, 9, 23, 8, 0, tzinfo=UTC)
    rows = (
        _bar(start, 99.0, 100.5, 98.8, 99.8),
        _bar(start + timedelta(minutes=15), 99.8, 101.0, 99.5, 100.5),
        _bar(start + timedelta(minutes=30), 100.5, 103.2, 100.1, 102.8),
    )
    out = evaluate_hold_break_outcome(
        rows,
        touch_index=0,
        direction="LONG",
        zone_low=98.0,
        zone_high=100.0,
        atr_points=6.0,
        horizon_m15=4,
        reaction_atr=0.50,
    )
    assert out.status == "HOLD"
    assert out.label_hold is True
    assert out.bars_to_outcome == 2


def test_break_wins_same_bar_ambiguity():
    start = datetime(2026, 9, 23, 8, 0, tzinfo=UTC)
    rows = (
        _bar(start, 103.0, 103.2, 101.0, 101.5),
        _bar(start + timedelta(minutes=15), 101.5, 104.0, 98.0, 103.0),
    )
    out = evaluate_hold_break_outcome(
        rows,
        touch_index=0,
        direction="SHORT",
        zone_low=101.0,
        zone_high=102.0,
        atr_points=4.0,
        horizon_m15=4,
        reaction_atr=0.50,
    )
    assert out.status == "BREAK"
    assert out.label_hold is False
    assert out.bars_to_outcome == 1


def _episode(index: int, *, direction: str, hold: bool, signal: float) -> HoldBreakEpisode:
    touch_at = datetime(2024, 1, 1, tzinfo=UTC) + timedelta(hours=4 * index)
    features = [0.0] * len(FEATURE_NAMES)
    features[0] = signal
    outcome = HoldBreakOutcome(
        status="HOLD" if hold else "BREAK",
        label_hold=hold,
        touch_at=touch_at,
        outcome_at=touch_at + timedelta(minutes=15),
        bars_to_outcome=1,
        max_favorable_excursion_atr=0.6 if hold else 0.1,
    )
    return HoldBreakEpisode(
        zone_id=f"zone-{index}",
        direction=direction,
        available_at=touch_at - timedelta(hours=6),
        touch_at=touch_at,
        decision_at=touch_at,
        zone_low=100.0,
        zone_high=102.0,
        features=tuple(features),
        outcome=outcome,
    )


def test_direction_specific_logistic_model_learns_hold_signal():
    rows = tuple(
        _episode(
            index,
            direction="LONG",
            hold=index >= 50,
            signal=1.0 if index >= 50 else -1.0,
        )
        for index in range(100)
    )
    model = fit_logistic_model(rows)
    positive = list(rows[-1].features)
    negative = list(rows[0].features)
    assert predict_probability(model, positive) > 0.70
    assert predict_probability(model, negative) < 0.30


def test_chronological_split_purges_boundaries():
    rows = tuple(
        _episode(
            index,
            direction="LONG" if index % 2 == 0 else "SHORT",
            hold=index % 3 == 0,
            signal=1.0 if index % 3 == 0 else -1.0,
        )
        for index in range(400)
    )
    train, calibration, holdout = _split_chronological(rows)
    assert train and calibration and holdout
    assert max(row.touch_at for row in train) + timedelta(hours=48) < min(
        row.touch_at for row in calibration
    )
    assert max(row.touch_at for row in calibration) + timedelta(hours=48) < min(
        row.touch_at for row in holdout
    )


def test_threshold_calibration_enforces_sample_floor():
    rows = tuple(
        _episode(
            index,
            direction="LONG",
            hold=True,
            signal=1.0,
        )
        for index in range(80)
    )
    too_small = tuple(
        ScoredEpisode(episode=row, probability_hold=0.9)
        for row in rows[:74]
    )
    threshold, report = _calibrate_threshold(too_small)
    assert threshold is None
    assert report["selection_reason"] == "NO_THRESHOLD_MEETS_SAMPLE_FLOOR"

    enough = tuple(
        ScoredEpisode(episode=row, probability_hold=0.9)
        for row in rows
    )
    threshold, report = _calibrate_threshold(enough)
    assert threshold is not None
    assert report["selected"] >= 75


def test_v177_is_strictly_shadow_only():
    assert ARTIFACT_CONTRACT == "XAU_H1_ORIGIN_HOLD_BREAK_V177_EVIDENCE_1"
    assert POLICY_EFFECT == "SHADOW_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert LIVE_EXECUTION_ENABLED is False

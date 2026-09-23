from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from fx_scanner.models import Bar
from fx_scanner.research_xau_h1_origin_hold_break_m5_v178 import (
    ARTIFACT_CONTRACT,
    EXECUTION_INFLUENCE,
    FEATURE_NAMES,
    LIVE_EXECUTION_ENABLED,
    POLICY_EFFECT,
    Episode,
    Outcome,
    ScoredEpisode,
    _calibrate_threshold,
    _split_chronological,
    evaluate_outcome,
    fit_logistic_model,
    predict_probability,
)


def _bar(ts, o, h, l, c, ticks=100):
    return Bar("XAUUSD", "M5", ts, o, h, l, c, ticks, 0.0, 0.0)


def test_m5_hold_requires_reaction_before_invalidation():
    start = datetime(2026, 9, 23, 8, 0, tzinfo=UTC)
    rows = (
        _bar(start, 99.0, 100.4, 98.8, 99.8),
        _bar(start + timedelta(minutes=5), 99.8, 101.0, 99.6, 100.5),
        _bar(start + timedelta(minutes=10), 100.5, 103.1, 100.1, 102.8),
    )
    out = evaluate_outcome(
        rows,
        touch_index=0,
        direction="LONG",
        zone_low=98.0,
        zone_high=100.0,
        atr_points=6.0,
        horizon_m5=5,
        reaction_atr=0.50,
    )
    assert out.status == "HOLD"
    assert out.label_hold is True
    assert out.bars_to_outcome == 2


def test_m5_break_wins_same_bar_ambiguity():
    start = datetime(2026, 9, 23, 8, 0, tzinfo=UTC)
    rows = (
        _bar(start, 103.0, 103.1, 101.0, 101.5),
        _bar(start + timedelta(minutes=5), 101.5, 104.0, 98.0, 103.0),
    )
    out = evaluate_outcome(
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


def _episode(index: int, *, direction: str, hold: bool, signal: float) -> Episode:
    touch_at = datetime(2024, 1, 1, tzinfo=UTC) + timedelta(hours=4 * index)
    features = [0.0] * len(FEATURE_NAMES)
    features[0] = signal
    outcome = Outcome(
        status="HOLD" if hold else "BREAK",
        label_hold=hold,
        touch_at=touch_at,
        outcome_at=touch_at + timedelta(minutes=5),
        bars_to_outcome=1,
        max_favorable_excursion_atr=0.6 if hold else 0.1,
    )
    return Episode(
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


def test_directional_logistic_model_learns_signal():
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
    assert predict_probability(model, rows[-1].features) > 0.70
    assert predict_probability(model, rows[0].features) < 0.30


def test_model_fails_closed_on_nonfinite_matrix():
    rows = list(
        _episode(
            index,
            direction="LONG",
            hold=index >= 50,
            signal=1.0 if index >= 50 else -1.0,
        )
        for index in range(100)
    )
    bad = list(rows[0].features)
    bad[2] = np.nan
    rows[0] = Episode(
        zone_id=rows[0].zone_id,
        direction=rows[0].direction,
        available_at=rows[0].available_at,
        touch_at=rows[0].touch_at,
        decision_at=rows[0].decision_at,
        zone_low=rows[0].zone_low,
        zone_high=rows[0].zone_high,
        features=tuple(bad),
        outcome=rows[0].outcome,
    )
    with pytest.raises(ValueError, match="V178_FEATURE_MATRIX_INVALID"):
        fit_logistic_model(tuple(rows))


def test_split_preserves_large_untouched_holdout_and_purge():
    rows = tuple(
        _episode(
            index,
            direction="LONG" if index % 2 == 0 else "SHORT",
            hold=index % 3 == 0,
            signal=1.0 if index % 3 == 0 else -1.0,
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
        _episode(
            index,
            direction="LONG",
            hold=True,
            signal=1.0,
        )
        for index in range(80)
    )
    scored = tuple(
        ScoredEpisode(episode=row, probability_hold=0.9)
        for row in rows
    )
    threshold, report = _calibrate_threshold(scored)
    assert threshold is not None
    assert report["selected"] >= 75


def test_v178_is_shadow_only_and_has_no_spread_features():
    assert ARTIFACT_CONTRACT == "XAU_H1_ORIGIN_HOLD_BREAK_M5_V178_EVIDENCE_1"
    assert POLICY_EFFECT == "SHADOW_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert LIVE_EXECUTION_ENABLED is False
    assert all("spread" not in name for name in FEATURE_NAMES)

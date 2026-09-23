from datetime import UTC, datetime, timedelta

from fx_scanner.models import Bar
from fx_scanner.research_xau_competing_zone_v175 import (
    EXECUTION_INFLUENCE,
    FEATURE_NAMES,
    LIVE_EXECUTION_ENABLED,
    POLICY_EFFECT,
    CandidateEpisode,
    MultiPathOutcome,
    ScoredEpisode,
    _reaction_key,
    _top_per_map_direction,
    evaluate_multi_zone_path,
    fit_logistic_model,
    predict_probability,
)


def _bar(ts, o, h, l, c):
    return Bar("XAUUSD", "M15", ts, o, h, l, c, 1, 0.1, 0.2)


def test_long_touch_then_half_atr_reaction_is_labeled_causally():
    start = datetime(2026, 9, 23, 8, 0, tzinfo=UTC)
    rows = (
        _bar(start, 4330, 4332, 4328, 4331),
        _bar(start + timedelta(minutes=15), 4331, 4332, 4320, 4324),
        _bar(start + timedelta(minutes=30), 4324, 4336, 4323, 4334),
    )
    result = evaluate_multi_zone_path(
        rows,
        forecast_at=start,
        direction="LONG",
        zone_low=4320,
        zone_high=4325,
        atr_points=16,
    )
    assert result.status == "TOUCH_REVERSED"
    assert result.bars_to_touch == 1
    assert result.primary_success is True
    assert result.reactions[_reaction_key(0.50, 16)] is True
    assert result.reactions[_reaction_key(0.75, 8)] is False


def test_invalidation_wins_same_bar_ambiguity():
    start = datetime(2026, 9, 23, 8, 0, tzinfo=UTC)
    result = evaluate_multi_zone_path(
        (_bar(start, 4330, 4350, 4320, 4345),),
        forecast_at=start,
        direction="SHORT",
        zone_low=4339,
        zone_high=4343,
        atr_points=16,
    )
    assert result.status == "TOUCH_INVALIDATED_SAME_BAR"
    assert result.primary_success is False


def _episode(index: int, *, touched: bool, reacted: bool) -> CandidateEpisode:
    at = datetime(2020, 1, 1, tzinfo=UTC) + timedelta(hours=4 * index)
    reactions = {
        _reaction_key(level, horizon): reacted
        for level in (0.25, 0.50, 0.75)
        for horizon in (8, 16, 32)
    }
    outcome = MultiPathOutcome(
        status="TOUCH_REVERSED" if reacted else "REACTION_TIMEOUT",
        touched=touched,
        touch_at=at if touched else None,
        invalidated_at=None,
        bars_to_touch=1 if touched else None,
        reactions=reactions,
        primary_success=reacted,
    )
    signal = 1.0 if reacted else -1.0
    features = (signal,) + (0.0,) * (len(FEATURE_NAMES) - 1)
    return CandidateEpisode(
        map_at=at,
        candidate_id=str(index),
        source="ROUND_NUMBER",
        direction="LONG",
        zone_low=1.0,
        zone_high=2.0,
        map_price=3.0,
        features=features,
        outcome=outcome,
    )


def test_reaction_model_is_fitted_only_on_touched_rows_and_learns_signal():
    rows = tuple(
        [_episode(index, touched=True, reacted=index >= 40) for index in range(80)]
        + [_episode(100 + index, touched=False, reacted=False) for index in range(20)]
    )
    model = fit_logistic_model(rows, target="reaction")
    assert model.rows == 80
    assert predict_probability(model, (1.0,) + (0.0,) * (len(FEATURE_NAMES) - 1)) > 0.80
    assert predict_probability(model, (-1.0,) + (0.0,) * (len(FEATURE_NAMES) - 1)) < 0.20


def test_top_ranker_keeps_one_candidate_for_each_map_and_direction():
    base = _episode(1, touched=True, reacted=True)
    rows = (
        ScoredEpisode(base, 0.9, 0.5, 0.45),
        ScoredEpisode(
            CandidateEpisode(
                map_at=base.map_at,
                candidate_id="better-long",
                source=base.source,
                direction="LONG",
                zone_low=base.zone_low,
                zone_high=base.zone_high,
                map_price=base.map_price,
                features=base.features,
                outcome=base.outcome,
            ),
            0.8,
            0.8,
            0.64,
        ),
        ScoredEpisode(
            CandidateEpisode(
                map_at=base.map_at,
                candidate_id="short",
                source=base.source,
                direction="SHORT",
                zone_low=base.zone_low,
                zone_high=base.zone_high,
                map_price=base.map_price,
                features=base.features,
                outcome=base.outcome,
            ),
            0.7,
            0.7,
            0.49,
        ),
    )
    selected = _top_per_map_direction(rows)
    assert {row.episode.candidate_id for row in selected} == {"better-long", "short"}


def test_v175_is_shadow_only_and_cannot_execute():
    assert POLICY_EFFECT == "SHADOW_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert LIVE_EXECUTION_ENABLED is False

from datetime import UTC, datetime, timedelta

from fx_scanner.models import Bar
from fx_scanner.research_xau_htf_strategic_regime_v180 import (
    ARTIFACT_CONTRACT,
    EXECUTION_INFLUENCE,
    LIVE_EXECUTION_ENABLED,
    POLICY_EFFECT,
    RegimePoint,
    _direction_from_score,
    _stability,
)


def _point(index: int, strategic: str, baseline: str) -> RegimePoint:
    return RegimePoint(
        map_at=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(hours=4 * index),
        close=100.0 + index,
        raw_score=0.5 if strategic == "LONG" else -0.5 if strategic == "SHORT" else 0.0,
        raw_direction=strategic,
        strategic_bias=strategic,
        baseline_h4_direction=baseline,
        switch_pending_direction=None,
        switch_pending_count=0,
        neutral_pending_count=0,
        components={},
    )


def test_raw_direction_threshold_has_neutral_band():
    assert _direction_from_score(0.50) == "LONG"
    assert _direction_from_score(-0.50) == "SHORT"
    assert _direction_from_score(0.0) == "NEUTRAL"


def test_sticky_regime_is_more_stable_than_flipping_h4_baseline():
    points = tuple(
        _point(
            index,
            "SHORT" if index < 10 else "LONG",
            "LONG" if index % 2 == 0 else "SHORT",
        )
        for index in range(20)
    )
    report = _stability(points, test_start=0)
    assert report["strategic_flips"] == 1
    assert report["baseline_h4_flips"] == 19
    assert report["median_regime_duration_hours"] == 40.0


def test_v180_is_strictly_shadow_only():
    assert ARTIFACT_CONTRACT == "XAU_HTF_STRATEGIC_REGIME_V180_EVIDENCE_1"
    assert POLICY_EFFECT == "SHADOW_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert LIVE_EXECUTION_ENABLED is False

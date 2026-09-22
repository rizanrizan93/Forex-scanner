from datetime import datetime, timedelta, timezone

from fx_scanner.models import Bar
from fx_scanner.research_xau_analog_path_forecast_v168 import (
    EXECUTION_INFLUENCE,
    FIRST_HIT_CLASSES,
    LIVE_EXECUTION_ENABLED,
    PATH_CLASSES,
    PROMOTION_ELIGIBLE,
    _entropy_confidence,
    _path_outcome,
    _probabilities,
)

UTC = timezone.utc


def _bar(index: int, *, o: float, h: float, l: float, c: float) -> Bar:
    return Bar(
        symbol="XAUUSD",
        timeframe="M15",
        timestamp=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(minutes=15 * index),
        open=o,
        high=h,
        low=l,
        close=c,
        tick_count=1,
        spread_avg=0.1,
        spread_max=0.1,
    )


def test_v168_is_forecast_only():
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False
    assert LIVE_EXECUTION_ENABLED is False


def test_path_outcome_detects_up_then_down_sequence():
    rows = [_bar(0, o=100, h=100.2, l=99.8, c=100)]
    for i in range(1, 33):
        if i == 3:
            rows.append(_bar(i, o=100.2, h=101.2, l=100.0, c=101.0))
        elif i == 10:
            rows.append(_bar(i, o=100.0, h=100.2, l=98.8, c=99.0))
        else:
            rows.append(_bar(i, o=100.0, h=100.4, l=99.6, c=100.0))
    outcome = _path_outcome(rows, 0, 1.0)
    assert outcome is not None
    assert outcome["first_hit"] == "UP"
    assert outcome["path"] == "UP_THEN_DOWN"


def test_path_outcome_detects_range_when_neither_one_atr_touched():
    rows = [_bar(0, o=100, h=100.1, l=99.9, c=100)]
    rows.extend(
        _bar(i, o=100, h=100.6, l=99.4, c=100)
        for i in range(1, 33)
    )
    outcome = _path_outcome(rows, 0, 1.0)
    assert outcome is not None
    assert outcome["first_hit"] == "NEITHER"
    assert outcome["path"] == "RANGE"


def test_probability_and_entropy_contract():
    probs = _probabilities(["UP", "UP", "DOWN", "NEITHER"], FIRST_HIT_CLASSES)
    assert probs["UP"] == 0.5
    assert abs(sum(probs.values()) - 1.0) < 1e-12
    path_probs = _probabilities(["RANGE"] * 10, PATH_CLASSES)
    assert path_probs["RANGE"] == 1.0
    assert _entropy_confidence(path_probs) == 1.0

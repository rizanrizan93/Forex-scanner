from datetime import datetime, timedelta, timezone

from fx_scanner.models import Bar
from fx_scanner.research_xau_afic_vol_normalized_path_v169 import (
    EXECUTION_INFLUENCE,
    LIVE_EXECUTION_ENABLED,
    PRIMARY_BARRIER_ATR,
    PROMOTION_ELIGIBLE,
    _barrier_outcome,
)

UTC = timezone.utc


def _bar(i, o, h, l, c):
    return Bar(
        symbol="XAUUSD",
        timeframe="M15",
        timestamp=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(minutes=15 * i),
        open=float(o),
        high=float(h),
        low=float(l),
        close=float(c),
        tick_count=1,
        spread_avg=0.1,
        spread_max=0.1,
    )


def test_v169_is_forecast_only():
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False
    assert LIVE_EXECUTION_ENABLED is False
    assert PRIMARY_BARRIER_ATR == 1.0


def test_long_favorable_first():
    rows = [_bar(0, 100, 100.1, 99.9, 100)]
    for i in range(1, 33):
        if i == 3:
            rows.append(_bar(i, 100.2, 101.2, 100.0, 101.0))
        elif i == 10:
            rows.append(_bar(i, 100.0, 100.2, 98.8, 99.0))
        else:
            rows.append(_bar(i, 100, 100.4, 99.6, 100))
    x = _barrier_outcome(
        rows, anchor_index=0, direction="LONG", atr=1.0, barrier_atr=1.0
    )
    assert x is not None
    assert x["first"] == "FAVORABLE"
    assert x["favorable_bar"] == 3
    assert x["adverse_bar"] == 10


def test_short_favorable_first():
    rows = [_bar(0, 100, 100.1, 99.9, 100)]
    for i in range(1, 33):
        if i == 2:
            rows.append(_bar(i, 99.8, 100.0, 98.8, 99.0))
        else:
            rows.append(_bar(i, 100, 100.4, 99.6, 100))
    x = _barrier_outcome(
        rows, anchor_index=0, direction="SHORT", atr=1.0, barrier_atr=1.0
    )
    assert x is not None
    assert x["first"] == "FAVORABLE"
    assert x["favorable_bar"] == 2


def test_same_bar_double_hit_is_ambiguous_not_forced():
    rows = [_bar(0, 100, 100.1, 99.9, 100)]
    rows.append(_bar(1, 100, 101.2, 98.8, 100))
    rows.extend(_bar(i, 100, 100.4, 99.6, 100) for i in range(2, 33))
    x = _barrier_outcome(
        rows, anchor_index=0, direction="LONG", atr=1.0, barrier_atr=1.0
    )
    assert x is not None
    assert x["first"] == "AMBIGUOUS"

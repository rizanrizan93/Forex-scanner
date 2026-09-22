from datetime import datetime, timedelta, timezone

from fx_scanner.models import Bar
from fx_scanner.research_xau_expected_move_envelope_v170 import (
    EXECUTION_INFLUENCE,
    LIVE_EXECUTION_ENABLED,
    LOOKBACK_MATCHES,
    PROMOTION_ELIGIBLE,
    _forecast_from_matches,
    _move_outcome,
    MoveOutcome,
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


def test_v170_is_envelope_only():
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False
    assert LIVE_EXECUTION_ENABLED is False
    assert LOOKBACK_MATCHES == 60


def test_move_outcome_measures_asymmetric_excursions():
    rows = [_bar(0, 100, 100.1, 99.9, 100)]
    for i in range(1, 34):
        if i == 4:
            rows.append(_bar(i, 100, 102.0, 99.5, 101.0))
        elif i == 16:
            rows.append(_bar(i, 100, 101.0, 97.0, 98.0))
        else:
            rows.append(_bar(i, 100, 100.5, 99.5, 100))
    x = _move_outcome(rows, 0)
    assert x is not None
    assert x.up_points["1h"] == 2.0
    assert x.down_points["4h"] == 3.0


def test_forecast_requires_full_60_matches():
    sample = MoveOutcome(
        index=0,
        slot=0,
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        price=100.0,
        up_points={"1h": 1.0, "4h": 2.0, "8h": 3.0},
        down_points={"1h": 1.5, "4h": 2.5, "8h": 3.5},
        abs_close_points={"1h": 0.5, "4h": 1.0, "8h": 1.5},
    )
    assert _forecast_from_matches([sample] * 59, price=100.0) is None
    out = _forecast_from_matches([sample] * 60, price=100.0)
    assert out is not None
    assert out["horizons"]["8h"]["levels"]["up_q75"] == 103.0
    assert out["horizons"]["8h"]["levels"]["down_q75"] == 96.5

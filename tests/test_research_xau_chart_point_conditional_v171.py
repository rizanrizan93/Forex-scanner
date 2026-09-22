from datetime import datetime, timedelta, timezone

from fx_scanner.models import Bar
from fx_scanner.research_xau_chart_point_conditional_v171 import (
    EXECUTION_INFLUENCE,
    LIVE_EXECUTION_ENABLED,
    MOMENTUM_LOOKBACK,
    PROMOTION_ELIGIBLE,
    REACTION_ATR,
    _find_clean_reaction,
    _is_extreme_momentum,
)

UTC = timezone.utc


def _bar(i, o, h, l, c):
    return Bar(
        symbol="XAUUSD",
        timeframe="D1",
        timestamp=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=i),
        open=float(o),
        high=float(h),
        low=float(l),
        close=float(c),
        tick_count=1,
        spread_avg=0.1,
        spread_max=0.1,
    )


def test_v171_is_diagnostic_only():
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False
    assert LIVE_EXECUTION_ENABLED is False
    assert MOMENTUM_LOOKBACK == 20
    assert REACTION_ATR == 0.5


def test_extreme_momentum_low_uses_prior_20_readings():
    roc = [None, None] + [float(i) for i in range(20)] + [-1.0]
    assert _is_extreme_momentum(roc, len(roc) - 1, "LOW")


def test_clean_half_atr_reaction_low():
    rows = [
        _bar(0, 100, 101, 99, 100),
        _bar(1, 100, 100.2, 99.2, 99.5),
        _bar(2, 99.5, 100.6, 99.1, 100.2),
    ]
    # Anchor low=99, reaction threshold=100 when ATR=2.
    # Day 1 never breaks 99; day 2 reaches 100.
    assert _find_clean_reaction(
        rows,
        anchor_index=0,
        side="LOW",
        atr=2.0,
    ) == 2


def test_pre_reaction_extreme_break_invalidates_case():
    rows = [
        _bar(0, 100, 101, 99, 100),
        _bar(1, 100, 100.3, 98.9, 99.4),
        _bar(2, 99.4, 100.5, 99.1, 100.1),
    ]
    assert _find_clean_reaction(
        rows,
        anchor_index=0,
        side="LOW",
        atr=2.0,
    ) is None

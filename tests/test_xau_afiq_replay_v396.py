from datetime import datetime, timedelta, timezone

import pytest

from fx_scanner.models import Bar
from fx_scanner.xau_afiq_replay_v396 import (
    build_liquidity_fractals,
    resolve_trade,
)

UTC = timezone.utc


def _bar(i: int, o: float, h: float, l: float, c: float) -> Bar:
    return Bar(
        symbol="XAUUSD",
        timeframe="H1",
        timestamp=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(hours=i),
        open=o,
        high=h,
        low=l,
        close=c,
        tick_count=1,
        spread_avg=0.0,
        spread_max=0.0,
    )


def _candidate(**overrides):
    row = {
        "zone_id": "z1",
        "direction": "LONG",
        "timeframe": "H4",
        "low": 95.0,
        "high": 101.0,
        "structural_invalidation": 90.0,
        "validation_level": 108.0,
        "targets": [120.0],
        "score": 10.0,
    }
    row.update(overrides)
    return row


def test_v396_wick_beyond_floor_is_tolerated_until_two_acceptance_closes() -> None:
    bars = (
        _bar(0, 100, 101, 99, 100),  # signal bar
        _bar(1, 100, 109, 89, 95),   # wick through 90, but close above
        _bar(2, 95, 121, 94, 115),   # target subsequently trades
    )
    trade = resolve_trade(bars, signal_index=0, candidate=_candidate())
    assert trade is not None
    assert trade.exit_reason == "TARGET"
    assert trade.r_multiple == pytest.approx(2.0)
    assert trade.confirmed_after_entry is True
    assert trade.mae_r > 1.0


def test_v396_two_closes_beyond_floor_exit_next_open() -> None:
    bars = (
        _bar(0, 100, 101, 99, 100),
        _bar(1, 100, 101, 88, 89),
        _bar(2, 89, 90, 87, 88),
        _bar(3, 87, 88, 85, 86),
    )
    trade = resolve_trade(bars, signal_index=0, candidate=_candidate(targets=[130.0]))
    assert trade is not None
    assert trade.exit_reason == "STRUCTURAL_ACCEPTANCE_INVALIDATION"
    assert trade.exit_index == 3
    assert trade.exit_price == 87.0
    assert trade.r_multiple == pytest.approx(-1.3)


def test_v396_next_open_rr_guard_rejects_degraded_fill() -> None:
    bars = (
        _bar(0, 100, 101, 99, 100),
        _bar(1, 112, 114, 111, 113),
        _bar(2, 113, 121, 112, 120),
    )
    assert resolve_trade(bars, signal_index=0, candidate=_candidate()) is None


def test_v396_liquidity_fractal_is_not_available_before_right_bars_close() -> None:
    bars = (
        _bar(0, 10, 11, 9, 10),
        _bar(1, 10, 12, 9.5, 11),
        _bar(2, 11, 15, 10, 14),
        _bar(3, 14, 14.5, 11, 12),
        _bar(4, 12, 13, 10.5, 11),
    )
    pivots = build_liquidity_fractals(bars)
    high = next(row for row in pivots if row["side"] == "BUY_SIDE" and row["price"] == 15.0)
    assert high["pivot_index"] == 2
    assert high["available_index"] == 4


def test_v396_short_trade_is_symmetric() -> None:
    bars = (
        _bar(0, 100, 101, 99, 100),
        _bar(1, 100, 101, 96, 97),
        _bar(2, 97, 98, 78, 80),
    )
    candidate = _candidate(
        direction="SHORT",
        low=99.0,
        high=105.0,
        structural_invalidation=110.0,
        validation_level=92.0,
        targets=[80.0],
    )
    trade = resolve_trade(bars, signal_index=0, candidate=candidate)
    assert trade is not None
    assert trade.exit_reason == "TARGET"
    assert trade.r_multiple == pytest.approx(2.0)
    assert trade.confirmed_after_entry is True

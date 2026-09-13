from datetime import date, datetime, timedelta, timezone

import pytest

from fx_scanner.models import Bar
from fx_scanner.research_m15_asia_london_v2 import (
    AsiaLondonCandidate,
    FROZEN_CANDIDATES,
    pip_size,
    replay_candidate,
    reprice_cost,
    split_by_calendar,
    summarize,
)

UTC = timezone.utc


def _bar(
    ts: datetime,
    *,
    symbol: str = "USDJPY",
    open_: float = 150.0,
    high: float = 150.02,
    low: float = 149.98,
    close: float = 150.0,
) -> Bar:
    return Bar(
        symbol=symbol,
        timeframe="M15",
        timestamp=ts,
        open=open_,
        high=high,
        low=low,
        close=close,
        tick_count=10,
        spread_avg=0.0,
        spread_max=0.0,
    )


def _long_day(day: date, *, symbol: str = "USDJPY", same_bar_stop_and_target: bool = False):
    start = datetime(day.year, day.month, day.day, tzinfo=UTC)
    rows = []
    # Complete 00:00-05:45 Asian range: 149.90-150.10.
    for index in range(24):
        rows.append(
            _bar(
                start + timedelta(minutes=15 * index),
                symbol=symbol,
                open_=150.00,
                high=150.10 if index == 4 else 150.05,
                low=149.90 if index == 8 else 149.95,
                close=150.00,
            )
        )
    # Fill 06:00-06:45, then first breakout close at 07:00.
    for minute in (360, 375, 390, 405):
        rows.append(_bar(start + timedelta(minutes=minute), symbol=symbol))
    rows.append(
        _bar(
            start + timedelta(hours=7),
            symbol=symbol,
            open_=150.08,
            high=150.15,
            low=150.05,
            close=150.12,
        )
    )
    # Entry is next M15 open at 150.12. Opposite-range stop=149.90, risk=.22,
    # target for 1.5R=150.45.
    if same_bar_stop_and_target:
        rows.append(
            _bar(
                start + timedelta(hours=7, minutes=15),
                symbol=symbol,
                open_=150.12,
                high=150.50,
                low=149.85,
                close=150.20,
            )
        )
    else:
        rows.append(
            _bar(
                start + timedelta(hours=7, minutes=15),
                symbol=symbol,
                open_=150.12,
                high=150.20,
                low=150.08,
                close=150.15,
            )
        )
        rows.append(
            _bar(
                start + timedelta(hours=7, minutes=30),
                symbol=symbol,
                open_=150.15,
                high=150.46,
                low=150.14,
                close=150.45,
            )
        )
    return tuple(rows)


def test_frozen_registry_is_small_and_named_v2() -> None:
    assert [row.name for row in FROZEN_CANDIDATES] == [
        "AL_RANGE_1P5R_V2",
        "AL_MIDPOINT_2R_V2",
    ]


def test_pip_size_handles_jpy_and_non_jpy() -> None:
    assert pip_size("USDJPY") == pytest.approx(0.01)
    assert pip_size("AUDUSD") == pytest.approx(0.0001)


def test_range_candidate_enters_next_bar_and_hits_target() -> None:
    candidate = FROZEN_CANDIDATES[0]
    trades = replay_candidate(
        _long_day(date(2026, 1, 5)),
        candidate=candidate,
        round_trip_cost_pips=1.2,
    )
    assert len(trades) == 1
    trade = trades[0]
    assert trade.direction == "LONG"
    assert trade.decision_time.hour == 7 and trade.decision_time.minute == 0
    assert trade.entry_time.hour == 7 and trade.entry_time.minute == 15
    assert trade.entry_price == pytest.approx(150.12)
    assert trade.stop_loss == pytest.approx(149.90)
    assert trade.take_profit == pytest.approx(150.45)
    assert trade.gross_result_r == pytest.approx(1.5)
    assert trade.net_result_r < trade.gross_result_r
    assert trade.exit_reason == "TARGET"


def test_same_bar_ambiguity_is_stop_first() -> None:
    trades = replay_candidate(
        _long_day(date(2026, 1, 6), same_bar_stop_and_target=True),
        candidate=FROZEN_CANDIDATES[0],
        round_trip_cost_pips=0.0,
    )
    assert len(trades) == 1
    assert trades[0].gross_result_r == pytest.approx(-1.0)
    assert trades[0].exit_reason == "STOP"


def test_missing_asia_bar_fails_closed_for_that_day() -> None:
    rows = list(_long_day(date(2026, 1, 7)))
    del rows[5]
    trades = replay_candidate(
        rows,
        candidate=FROZEN_CANDIDATES[0],
        round_trip_cost_pips=1.2,
    )
    assert trades == ()


def test_cost_repricing_keeps_geometry_and_gross_result() -> None:
    base = replay_candidate(
        _long_day(date(2026, 1, 8)),
        candidate=FROZEN_CANDIDATES[0],
        round_trip_cost_pips=0.0,
    )
    stressed = reprice_cost(base, round_trip_cost_pips=1.5)
    assert len(stressed) == 1
    assert stressed[0].entry_price == base[0].entry_price
    assert stressed[0].stop_loss == base[0].stop_loss
    assert stressed[0].take_profit == base[0].take_profit
    assert stressed[0].gross_result_r == base[0].gross_result_r
    assert stressed[0].net_result_r < base[0].net_result_r


def test_calendar_split_is_explicit() -> None:
    candidate = FROZEN_CANDIDATES[0]
    trades = []
    for day in (date(2024, 6, 3), date(2025, 6, 3), date(2026, 6, 3)):
        trades.extend(replay_candidate(_long_day(day), candidate=candidate, round_trip_cost_pips=0))
    split = split_by_calendar(
        trades,
        train_end=date(2024, 12, 31),
        validation_end=date(2025, 12, 31),
        oos_end=date(2026, 8, 31),
    )
    assert len(split["train"]) == 1
    assert len(split["validation"]) == 1
    assert len(split["oos"]) == 1


def test_summary_uses_net_r_and_drawdown() -> None:
    candidate = AsiaLondonCandidate("TEST", "OPPOSITE_RANGE", 1.5)
    winners = replay_candidate(
        _long_day(date(2026, 2, 2)),
        candidate=candidate,
        round_trip_cost_pips=0,
    )
    assert summarize(winners).average_net_r == pytest.approx(1.5)


def test_invalid_calendar_order_fails_closed() -> None:
    with pytest.raises(ValueError):
        split_by_calendar(
            (),
            train_end=date(2025, 12, 31),
            validation_end=date(2025, 12, 31),
            oos_end=date(2026, 8, 31),
        )

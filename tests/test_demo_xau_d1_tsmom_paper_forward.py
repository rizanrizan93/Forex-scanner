from datetime import UTC, datetime, timedelta

from fx_scanner.demo_xau_d1_tsmom_paper_forward import (
    FORWARD_EPOCH,
    PAPER_CONTRACT,
    PAPER_SETUP_TYPE,
    evaluate_paper_exit,
)
from fx_scanner.models import Bar


def _bar(day: int, *, high: float, low: float, close: float) -> Bar:
    stamp = datetime(2026, 9, 14, tzinfo=UTC) + timedelta(days=day)
    return Bar(
        symbol="XAUUSD",
        timeframe="D1",
        timestamp=stamp,
        open=2000.0,
        high=high,
        low=low,
        close=close,
        tick_count=1,
        spread_avg=0.0,
        spread_max=0.0,
    )


def test_paper_contract_is_forward_only_and_namespaced():
    assert PAPER_CONTRACT == "XAU_D1_TSMOM_PAPER_FORWARD_V1"
    assert PAPER_SETUP_TYPE == "D1_TSMOM_60_200_PAPER_V1"
    assert FORWARD_EPOCH == datetime(2026, 9, 13, tzinfo=UTC)


def test_same_bar_stop_and_target_is_stop_first():
    bars = (_bar(0, high=2045.0, low=1975.0, close=2020.0),)
    outcome = evaluate_paper_exit(
        bars,
        direction="LONG",
        entry_time=bars[0].timestamp,
        entry_price=2000.0,
        stop=1980.0,
        target=2040.0,
    )
    assert outcome is not None
    assert outcome.reason == "STOP"
    assert outcome.exit_price == 1980.0
    assert outcome.gross_r == -1.0
    assert outcome.net_r < outcome.gross_r


def test_long_target_is_two_r_before_stress_cost():
    bars = (_bar(0, high=2041.0, low=1995.0, close=2030.0),)
    outcome = evaluate_paper_exit(
        bars,
        direction="LONG",
        entry_time=bars[0].timestamp,
        entry_price=2000.0,
        stop=1980.0,
        target=2040.0,
    )
    assert outcome is not None
    assert outcome.reason == "TARGET"
    assert outcome.gross_r == 2.0
    assert outcome.net_r == 2.0 - 0.35 / 20.0


def test_short_target_uses_same_geometry():
    bars = (_bar(0, high=2005.0, low=1955.0, close=1970.0),)
    outcome = evaluate_paper_exit(
        bars,
        direction="SHORT",
        entry_time=bars[0].timestamp,
        entry_price=2000.0,
        stop=2020.0,
        target=1960.0,
    )
    assert outcome is not None
    assert outcome.reason == "TARGET"
    assert outcome.gross_r == 2.0


def test_time_exit_requires_next_bar_to_prove_max_hold_closed():
    first_30 = tuple(
        _bar(i, high=2010.0, low=1990.0, close=2001.0 + i * 0.1)
        for i in range(30)
    )
    pending = evaluate_paper_exit(
        first_30,
        direction="LONG",
        entry_time=first_30[0].timestamp,
        entry_price=2000.0,
        stop=1980.0,
        target=2040.0,
    )
    assert pending is None

    with_next = first_30 + (_bar(30, high=2011.0, low=1991.0, close=2004.0),)
    outcome = evaluate_paper_exit(
        with_next,
        direction="LONG",
        entry_time=with_next[0].timestamp,
        entry_price=2000.0,
        stop=1980.0,
        target=2040.0,
    )
    assert outcome is not None
    assert outcome.reason == "TIME_MAX30"
    assert outcome.exit_time == with_next[30].timestamp


def test_pre_entry_bars_are_ignored():
    pre = _bar(0, high=2100.0, low=1900.0, close=2000.0)
    entry = _bar(1, high=2010.0, low=1990.0, close=2005.0)
    outcome = evaluate_paper_exit(
        (pre, entry),
        direction="LONG",
        entry_time=entry.timestamp,
        entry_price=2000.0,
        stop=1980.0,
        target=2040.0,
    )
    assert outcome is None

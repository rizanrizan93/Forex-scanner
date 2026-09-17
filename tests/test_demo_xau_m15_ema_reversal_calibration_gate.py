from datetime import datetime, timedelta, timezone

from fx_scanner.demo_xau_m15_ema_reversal_candidate_producer import (
    STRUCTURE_GATE_CONTRACT,
    _mss_failed_retest_confirmed,
)
from fx_scanner.models import Bar

UTC = timezone.utc


def _bar(index: int, *, open_: float, high: float, low: float, close: float) -> Bar:
    return Bar(
        symbol="XAUUSD",
        timeframe="M15",
        timestamp=datetime(2026, 9, 17, tzinfo=UTC) + timedelta(minutes=15 * index),
        open=open_,
        high=high,
        low=low,
        close=close,
        tick_count=200 + index,
        spread_avg=0.25,
        spread_max=0.40,
    )


def test_short_requires_structure_break_then_failed_retest():
    rows = [
        _bar(i, open_=102.0 + i * 0.1, high=103.0 + i * 0.1, low=100.0 + i * 0.1, close=102.5 + i * 0.1)
        for i in range(6)
    ]
    rows.append(_bar(6, open_=101.0, high=101.2, low=98.7, close=99.0))
    rows.append(_bar(7, open_=100.1, high=100.2, low=99.2, close=99.5))
    as_of = rows[-1].timestamp + timedelta(minutes=15)

    assert STRUCTURE_GATE_CONTRACT == "M15_MSS_BREAK_FAILED_RETEST_V1"
    assert _mss_failed_retest_confirmed(
        tuple(rows), direction="SHORT", atr=2.0, as_of=as_of
    ) is True


def test_short_single_rejection_without_mss_fails_closed():
    rows = [
        _bar(i, open_=102.0 + i * 0.1, high=103.0 + i * 0.1, low=100.0 + i * 0.1, close=102.5 + i * 0.1)
        for i in range(6)
    ]
    rows.append(_bar(6, open_=101.3, high=101.6, low=100.1, close=100.4))
    rows.append(_bar(7, open_=101.0, high=101.2, low=99.4, close=99.7))
    as_of = rows[-1].timestamp + timedelta(minutes=15)

    assert _mss_failed_retest_confirmed(
        tuple(rows), direction="SHORT", atr=2.0, as_of=as_of
    ) is False


def test_long_requires_structure_break_then_successful_retest():
    rows = [
        _bar(i, open_=108.0 - i * 0.1, high=110.0 - i * 0.1, low=107.0 - i * 0.1, close=107.5 - i * 0.1)
        for i in range(6)
    ]
    rows.append(_bar(6, open_=109.0, high=111.0, low=108.8, close=110.5))
    rows.append(_bar(7, open_=109.9, high=110.8, low=109.8, close=110.3))
    as_of = rows[-1].timestamp + timedelta(minutes=15)

    assert _mss_failed_retest_confirmed(
        tuple(rows), direction="LONG", atr=2.0, as_of=as_of
    ) is True


def test_invalid_direction_or_atr_fails_closed():
    rows = tuple(
        _bar(i, open_=100.0, high=101.0, low=99.0, close=100.0)
        for i in range(8)
    )
    as_of = rows[-1].timestamp + timedelta(minutes=15)

    assert _mss_failed_retest_confirmed(rows, direction=None, atr=2.0, as_of=as_of) is False
    assert _mss_failed_retest_confirmed(rows, direction="SHORT", atr=0.0, as_of=as_of) is False

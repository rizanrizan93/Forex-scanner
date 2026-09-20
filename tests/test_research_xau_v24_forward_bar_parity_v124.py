from datetime import datetime, timedelta, timezone

from fx_scanner.models import Bar
from fx_scanner.research_xau_v24_forward_bar_parity_v124 import (
    _aggregate_d1,
    _aggregate_h1,
    compare_d1,
    compare_h1,
)

UTC = timezone.utc


def _bar(ts, o, h, l, c, tf="M15"):
    return Bar(
        symbol="XAUUSD",
        timeframe=tf,
        timestamp=ts,
        open=o,
        high=h,
        low=l,
        close=c,
        tick_count=10,
        spread_avg=0.0,
        spread_max=0.0,
    )


def test_h1_aggregation_matches_four_quarter_hours_exactly():
    start = datetime(2026, 9, 21, 0, 0, tzinfo=UTC)
    m15 = (
        _bar(start, 10, 12, 9, 11),
        _bar(start + timedelta(minutes=15), 11, 13, 10, 12),
        _bar(start + timedelta(minutes=30), 12, 14, 11, 13),
        _bar(start + timedelta(minutes=45), 13, 15, 12, 14),
    )
    out = _aggregate_h1(m15)
    assert len(out) == 1
    assert out[0].timestamp == start
    assert (out[0].open, out[0].high, out[0].low, out[0].close) == (10, 15, 9, 14)

    native = (_bar(start, 10, 15, 9, 14, tf="H1"),)
    report = compare_h1(m15, native)
    assert report["overlap_rows"] == 1
    assert report["diffs"]["max"] == {"open": 0, "high": 0, "low": 0, "close": 0}


def test_d1_aggregation_uses_utc_calendar_date_like_v20_research():
    day = datetime(2026, 9, 21, 0, 0, tzinfo=UTC)
    m15 = (
        _bar(day, 100, 102, 99, 101),
        _bar(day + timedelta(hours=12), 101, 105, 100, 104),
        _bar(day + timedelta(hours=23, minutes=45), 104, 106, 103, 105),
    )
    out = _aggregate_d1(m15)
    row = out[day.date()]
    assert (row.open, row.high, row.low, row.close) == (100, 106, 99, 105)


def test_d1_parity_reports_date_shift_candidates_without_choosing_for_execution():
    day = datetime(2026, 9, 21, 0, 0, tzinfo=UTC)
    m15 = (
        _bar(day, 100, 102, 99, 101),
        _bar(day + timedelta(hours=23, minutes=45), 101, 103, 100, 102),
    )
    broker = (
        _bar(day + timedelta(days=1), 100, 103, 99, 102, tf="D1"),
    )
    report = compare_d1(m15, broker)
    assert report["alignments"]["0"]["overlap_rows"] == 0
    assert report["alignments"]["1"]["overlap_rows"] == 1
    assert report["alignments"]["1"]["diffs"]["max"] == {
        "open": 0,
        "high": 0,
        "low": 0,
        "close": 0,
    }

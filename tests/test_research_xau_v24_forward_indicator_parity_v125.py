from datetime import date, datetime, timedelta, timezone

import pytest

from fx_scanner.demo_xau_v24_utc_d1_context import DailyOhlc
from fx_scanner.models import Bar
from fx_scanner.research_xau_v24_forward_indicator_parity_v125 import (
    _compare_h1_bias,
    _compare_indicator_tail,
    _d1_tail_warmup_comparison,
)

UTC = timezone.utc


def _bar(index: int, *, timeframe: str = "H1") -> Bar:
    minutes = 60 if timeframe == "H1" else 15
    stamp = datetime(2025, 1, 1, tzinfo=UTC) + timedelta(minutes=minutes * index)
    base = 2000.0 + 0.20 * index + 3.0 * ((index % 11) - 5) / 5.0
    close = base + (1.0 if index % 3 else -0.5)
    return Bar(
        symbol="XAUUSD",
        timeframe=timeframe,
        timestamp=stamp,
        open=base,
        high=max(base, close) + 2.0,
        low=min(base, close) - 2.0,
        close=close,
        tick_count=100,
        spread_avg=0.1,
        spread_max=0.2,
    )


def test_indicator_tail_is_exact_when_short_and_long_history_are_same():
    rows = tuple(_bar(i) for i in range(320))
    report = _compare_indicator_tail(
        rows,
        short_count=len(rows),
        tail_count=80,
        fields=("ema20", "ema50", "atr", "plus_di", "minus_di", "adx"),
    )
    for field in report["fields"].values():
        assert field["paired"] > 0
        assert field["max_abs"] == pytest.approx(0.0, abs=1e-12)


def test_h1_bias_alignment_is_exact_when_history_is_same():
    rows = tuple(_bar(i) for i in range(320))
    report = _compare_h1_bias(
        rows,
        short_count=len(rows),
        tail_count=100,
        adx_min=12.0,
    )
    assert report["paired"] == 100
    assert report["mismatches"] == 0
    assert report["mismatch_fraction"] == 0.0


def _daily(count: int = 1200) -> tuple[DailyOhlc, ...]:
    start = date(2023, 1, 1)
    out = []
    for i in range(count):
        base = 1800.0 + 1.25 * i
        out.append(
            DailyOhlc(
                day=start + timedelta(days=i),
                open=base,
                high=base + 12.0,
                low=base - 10.0,
                close=base + 5.0,
            )
        )
    return tuple(out)


def test_rolling_d1_warmup_parity_keeps_direction_on_smooth_secular_trend():
    report = _d1_tail_warmup_comparison(_daily(), target_count=60)
    assert report["targets_compared"] == 60
    assert report["direction_mismatches"] == 0
    assert report["direction_mismatch_fraction"] == 0.0
    assert report["ema200_abs_diff"]["max_abs"] is not None
    assert report["atr14_abs_diff"]["max_abs"] is not None

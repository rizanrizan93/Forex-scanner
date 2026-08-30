from datetime import datetime, timedelta, timezone

import pytest

from fx_scanner.config import load_project_config
from fx_scanner.liquidity import (
    LiquidityKind,
    build_liquidity_map,
    dealing_range,
    equal_levels,
    previous_day_levels,
    previous_session_levels,
    previous_week_levels,
    scan_fvgs,
    scan_order_blocks,
)
from fx_scanner.models import Bar

UTC = timezone.utc


def bar(tf, i, o, h, l, c, *, start=None, step=None, symbol="EURUSD", ticks=100):
    start = start or datetime(2026, 8, 1, tzinfo=UTC)
    if step is None:
        step = {
            "D1": timedelta(days=1),
            "H1": timedelta(hours=1),
            "M15": timedelta(minutes=15),
            "M5": timedelta(minutes=5),
        }[tf]
    return Bar(
        symbol=symbol,
        timeframe=tf,
        timestamp=start + step * i,
        open=o,
        high=h,
        low=l,
        close=c,
        tick_count=ticks,
        spread_avg=0.0001,
        spread_max=0.0002,
    )


def test_previous_day_excludes_current_day_candle():
    bars = [
        bar("D1", 0, 1.10, 1.12, 1.09, 1.11, start=datetime(2026, 8, 28, tzinfo=UTC)),
        bar("D1", 2, 1.11, 1.50, 1.00, 1.20, start=datetime(2026, 8, 28, tzinfo=UTC)),
    ]
    levels = previous_day_levels(
        bars,
        as_of=datetime(2026, 8, 30, 12, tzinfo=UTC),
    )
    by_kind = {x.kind: x.price for x in levels}
    assert by_kind[LiquidityKind.PDH] == pytest.approx(1.12)
    assert by_kind[LiquidityKind.PDL] == pytest.approx(1.09)


def test_previous_week_uses_last_completed_iso_week():
    start = datetime(2026, 8, 17, tzinfo=UTC)
    bars = []
    for i in range(12):
        base = 1.10 + i * 0.001
        bars.append(bar("D1", i, base, base + 0.01, base - 0.01, base + 0.002, start=start))
    levels = previous_week_levels(
        bars,
        as_of=datetime(2026, 8, 30, 12, tzinfo=UTC),
    )
    by_kind = {x.kind: x.price for x in levels}
    previous_week_bars = bars[:7]
    assert by_kind[LiquidityKind.PWH] == max(x.high for x in previous_week_bars)
    assert by_kind[LiquidityKind.PWL] == min(x.low for x in previous_week_bars)


def test_equal_highs_are_clustered_with_atr_tolerance():
    bars = []
    for i in range(24):
        base = 1.1000 + (i % 4) * 0.0002
        high = base + 0.0006
        low = base - 0.0005
        close = base + 0.0001
        bars.append(bar("H1", i, base, high, low, close))
    # Force two isolated highs near the same liquidity level.
    bars[6] = bar("H1", 6, 1.1000, 1.1050, 1.0995, 1.1005)
    bars[14] = bar("H1", 14, 1.1002, 1.10505, 1.0997, 1.1006)
    levels = equal_levels(
        bars,
        atr_period=14,
        pivot_lookback=1,
        tolerance_atr=0.15,
        minimum_touches=2,
        scan_bars=24,
    )
    eqh = [x for x in levels if x.kind == LiquidityKind.EQUAL_HIGH]
    assert eqh
    assert max(x.touches for x in eqh) >= 2
    assert any(abs(x.price - 1.105025) < 0.0002 for x in eqh)


def test_dealing_range_classifies_discount_and_premium():
    bars = []
    for i in range(20):
        base = 1.10
        bars.append(bar("H1", i, base, 1.1020, 1.0980, base))
    bars[5] = bar("H1", 5, 1.10, 1.1200, 1.0990, 1.1050)
    bars[10] = bar("H1", 10, 1.10, 1.1010, 1.0800, 1.0950)
    bars[15] = bar("H1", 15, 1.10, 1.1150, 1.0900, 1.1050)
    dr = dealing_range(bars, current_price=1.095, pivot_lookback=1, equilibrium_band=0.05)
    assert dr is not None
    assert dr.zone == "DISCOUNT"
    assert dr.low < dr.equilibrium < dr.high


def test_previous_session_levels_capture_completed_london_session():
    cfg = load_project_config()
    start = datetime(2026, 8, 29, 6, 0, tzinfo=UTC)
    bars = []
    for i in range(40):
        base = 1.10 + i * 0.0001
        bars.append(
            bar(
                "M15",
                i,
                base,
                base + 0.0005,
                base - 0.0004,
                base + 0.0001,
                start=start,
            )
        )
    levels = previous_session_levels(
        bars,
        as_of=datetime(2026, 8, 30, 10, 0, tzinfo=UTC),
        session_config=cfg.sessions,
    )
    kinds = {x.kind for x in levels}
    assert LiquidityKind.LONDON_HIGH in kinds
    assert LiquidityKind.LONDON_LOW in kinds


def test_fvg_scan_tracks_open_partial_and_filled_state():
    bars = []
    for i in range(18):
        base = 1.1000
        bars.append(bar("M5", i, base, 1.1006, 1.0994, 1.1001))
    bars[12] = bar("M5", 12, 1.1000, 1.1010, 1.0995, 1.1005)
    bars[13] = bar("M5", 13, 1.1012, 1.1020, 1.1010, 1.1018)
    bars[14] = bar("M5", 14, 1.1020, 1.1028, 1.1016, 1.1024)
    bars[15] = bar("M5", 15, 1.1022, 1.1025, 1.1013, 1.1018)
    gaps = scan_fvgs(bars, atr_period=14, minimum_atr=0.10, scan_bars=18)
    bullish = [x for x in gaps if x.direction == "BULLISH" and x.origin_at == bars[14].timestamp]
    assert bullish
    assert bullish[0].status in {"PARTIAL", "FILLED"}
    assert bullish[0].fill_fraction > 0


def test_order_block_requires_displacement_and_structure_break():
    bars = []
    for i in range(20):
        base = 1.1000 + (i % 3) * 0.0001
        bars.append(bar("M5", i, base, base + 0.0005, base - 0.0005, base + 0.0001))
    bars[15] = bar("M5", 15, 1.1005, 1.1008, 1.0997, 1.0999)
    bars[16] = bar("M5", 16, 1.1000, 1.1050, 1.0999, 1.1047, ticks=220)
    bars[17] = bar("M5", 17, 1.1045, 1.1052, 1.1038, 1.1048)
    blocks = scan_order_blocks(
        bars,
        atr_period=14,
        search_bars=20,
        origin_lookback=5,
    )
    bullish = [x for x in blocks if x.direction == "BULLISH"]
    assert bullish
    assert bullish[-1].caused_break
    assert bullish[-1].origin_at == bars[15].timestamp


def test_build_liquidity_map_contains_external_and_internal_levels():
    cfg = load_project_config()
    d1 = [
        bar("D1", i, 1.10, 1.11 + i * 0.001, 1.09 - i * 0.0002, 1.10)
        for i in range(25)
    ]
    h1 = [
        bar("H1", i, 1.10, 1.101 + (i % 5) * 0.0005, 1.099 - (i % 4) * 0.0004, 1.10)
        for i in range(50)
    ]
    m5 = [
        bar("M5", i, 1.10, 1.1008, 1.0992, 1.1001)
        for i in range(70)
    ]
    result = build_liquidity_map(
        d1_bars=d1,
        h1_bars=h1,
        intraday_bars=m5,
        as_of=datetime(2026, 8, 30, 12, tzinfo=UTC),
        current_price=1.10,
        session_config=cfg.sessions,
        pivot_lookback=1,
        atr_period=14,
    )
    kinds = {x.kind for x in result.levels}
    assert LiquidityKind.PDH in kinds
    assert LiquidityKind.PDL in kinds

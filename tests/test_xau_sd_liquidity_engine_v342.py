from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from fx_scanner.xau_sd_liquidity_engine_v342 import (
    HISTORICAL_DEPTH_PRIOR,
    detect_zones,
    evaluate_sd_liquidity,
)


def _bars(tf: str, start: datetime, count: int, step: timedelta, base: float = 2000.0):
    out = []
    for i in range(count):
        px = base + (i % 3 - 1) * 0.5
        out.append(
            SimpleNamespace(
                timestamp=start + i * step,
                open=px,
                high=px + 2.0,
                low=px - 2.0,
                close=px + 0.2,
            )
        )
    return out


def _with_bull_departure(tf: str, step: timedelta):
    start = datetime(2026, 1, 1, tzinfo=UTC)
    bars = _bars(tf, start, 24, step)
    # Compact base.
    bars.append(
        SimpleNamespace(
            timestamp=start + 24 * step,
            open=2000.0,
            high=2001.0,
            low=1999.0,
            close=2000.2,
        )
    )
    # Strong departure and local BOS.
    bars.append(
        SimpleNamespace(
            timestamp=start + 25 * step,
            open=2000.2,
            high=2014.0,
            low=1999.8,
            close=2013.0,
        )
    )
    # Post-publication bars stay above the demand zone.
    for i in range(26, 36):
        px = 2012.0 + (i - 26) * 0.3
        bars.append(
            SimpleNamespace(
                timestamp=start + i * step,
                open=px,
                high=px + 1.2,
                low=px - 1.0,
                close=px + 0.3,
            )
        )
    return bars


def test_v342_detects_causal_h1_demand_zone():
    bars = _with_bull_departure("H1", timedelta(hours=1))
    as_of = bars[-1].timestamp + timedelta(hours=1)
    zones = detect_zones(bars, timeframe="H1", as_of=as_of)
    assert zones
    zone = zones[-1]
    assert zone.direction == "LONG"
    assert zone.available_at == bars[25].timestamp
    assert zone.low < zone.high
    assert zone.structural_bos is True


def test_v342_evaluation_is_isolated_and_non_executable():
    h1 = _with_bull_departure("H1", timedelta(hours=1))
    h4 = _with_bull_departure("H4", timedelta(hours=4))
    m15 = _bars("M15", datetime(2026, 1, 1, tzinfo=UTC), 120, timedelta(minutes=15), 2012.0)
    m5 = _bars("M5", datetime(2026, 1, 1, tzinfo=UTC), 240, timedelta(minutes=5), 2012.0)
    as_of = max(h1[-1].timestamp, h4[-1].timestamp) + timedelta(hours=4)
    result = evaluate_sd_liquidity(
        bars_h1=h1,
        bars_h4=h4,
        bars_m15=m15,
        bars_m5=m5,
        as_of=as_of,
        price_now=2012.0,
    )
    assert result["execution_authority"] is False
    assert result["execution_influence"] is False
    assert result["historical_depth_prior"]["episodes_all_timeframes"] == 68094
    assert HISTORICAL_DEPTH_PRIOR["years"][0] == 2012
    assert HISTORICAL_DEPTH_PRIOR["years"][-1] == 2026

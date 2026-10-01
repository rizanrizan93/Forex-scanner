from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from fx_scanner.xau_sd_liquidity_engine_v342 import (
    HISTORICAL_DEPTH_PRIOR,
    _classify_hierarchy,
    _roadblocks,
    _select_parent_and_refinement,
    _structural_destination,
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
    assert zone.available_at == bars[25].timestamp + timedelta(hours=1)
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



def _zone_row(
    zone_id: str,
    timeframe: str,
    direction: str,
    low: float,
    high: float,
    *,
    atr: float = 10.0,
    score: float = 80.0,
    price: float = 100.0,
):
    distance = 0.0 if low <= price <= high else min(abs(price - low), abs(price - high))
    return {
        "zone_id": zone_id,
        "timeframe": timeframe,
        "direction": direction,
        "low": low,
        "high": high,
        "atr": atr,
        "score": score,
        "distance_points": distance,
        "lifecycle": {"freshness": "FRESH"},
    }


def test_v347_h4_parent_cannot_be_overridden_by_closer_h1_opposing_zone():
    price = 100.0
    zones = [
        _zone_row("h4-demand", "H4", "LONG", 95.0, 101.0, price=price, score=78.0),
        _zone_row("h1-supply", "H1", "SHORT", 99.8, 100.8, price=price, score=95.0),
        _zone_row("h4-supply", "H4", "SHORT", 120.0, 125.0, price=price, score=82.0),
    ]
    classified = _classify_hierarchy(zones, price_now=price)
    parent, refinement, selection = _select_parent_and_refinement(
        classified, price_now=price
    )
    assert parent["zone_id"] == "h4-demand"
    assert parent["timeframe"] == "H4"
    assert refinement == {}
    assert selection == "H4_PARENT"


def test_v347_nested_same_direction_h1_becomes_refinement():
    price = 100.0
    zones = [
        _zone_row("h4-demand", "H4", "LONG", 95.0, 105.0, price=price),
        _zone_row("h1-demand", "H1", "LONG", 98.0, 102.0, price=price, score=88.0),
        _zone_row("h4-supply", "H4", "SHORT", 120.0, 125.0, price=price),
    ]
    classified = _classify_hierarchy(zones, price_now=price)
    child = next(z for z in classified if z["zone_id"] == "h1-demand")
    assert child["hierarchy_role"] == "H1_REFINEMENT"
    parent, refinement, selection = _select_parent_and_refinement(
        classified, price_now=price
    )
    assert parent["zone_id"] == "h4-demand"
    assert refinement["zone_id"] == "h1-demand"
    assert selection == "H4_PARENT"


def test_v347_roadblock_only_exists_before_opposing_h4_destination():
    price = 100.0
    zones = [
        _zone_row("h4-demand", "H4", "LONG", 95.0, 101.0, price=price),
        _zone_row("h1-supply-near", "H1", "SHORT", 108.0, 110.0, price=price),
        _zone_row("h1-supply-after", "H1", "SHORT", 130.0, 132.0, price=price),
        _zone_row("h4-supply", "H4", "SHORT", 120.0, 125.0, price=price),
    ]
    classified = _classify_hierarchy(zones, price_now=price)
    destination = _structural_destination(
        direction="LONG",
        start_price=price,
        active_zones=classified,
    )
    roadblocks = _roadblocks(
        direction="LONG",
        start_price=price,
        active_zones=classified,
        destination=destination,
        parent_zone_id="h4-demand",
    )
    assert destination["zone_id"] == "h4-supply"
    assert [r["zone_id"] for r in roadblocks] == ["h1-supply-near"]
    assert roadblocks[0]["type"] == "SUPPLY"

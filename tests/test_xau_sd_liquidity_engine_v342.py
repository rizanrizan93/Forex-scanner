from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from fx_scanner.xau_sd_liquidity_engine_v342 import (
    HISTORICAL_DEPTH_PRIOR,
    _classify_hierarchy,
    _conditional_failure_path,
    _h2_frame_from_h1,
    _micro_confirmation,
    _prepared_entry_band,
    _roadblocks,
    _select_parent_and_refinement,
    _structural_destination,
    _structural_path,
    _structural_room_gate,
    _zone_condition,
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


def test_v354_prepared_entry_band_is_available_before_micro_confirmation():
    demand = _zone_row(
        "h4-demand",
        "H4",
        "LONG",
        4144.56,
        4175.17,
        price=4171.8,
    )
    prepared = _prepared_entry_band(demand)
    assert prepared["state"] == "PREPARE_FORECAST"
    assert prepared["execution_authority"] is False
    assert 4144.56 < prepared["entry_low"] < prepared["entry_high"] < 4175.17
    assert prepared["entry_low"] < prepared["entry_reference"] < prepared["entry_high"]


def test_v352_evaluation_is_isolated_and_demo_execution_authorized():
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
    assert result["execution_authority"] is True
    assert result["execution_influence"] is True
    assert result["execution_scope"] == "DEMO_ONLY"
    assert result["live_execution_enabled"] is False
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



def test_v348_blocks_compressed_htf_corridor_before_entry():
    parent = _zone_row(
        "h4-supply",
        "H4",
        "SHORT",
        4176.54,
        4219.29,
        atr=32.177857142857,
        price=4182.21,
    )
    destination = {
        "price": 4175.17,
        "low": 4144.56,
        "high": 4175.17,
        "zone_id": "h4-demand",
    }
    result = _structural_room_gate(
        parent_zone=parent,
        direction="SHORT",
        path_start=4182.21,
        destination=destination,
        entry=None,
        invalidation=None,
    )
    assert result["state"] == "COMPRESSED_HTF_CORRIDOR"
    assert result["blocked"] is True
    assert result["distance_parent_atr"] < 0.50


def test_v348_allows_room_when_destination_is_far_enough():
    parent = _zone_row(
        "h4-supply",
        "H4",
        "SHORT",
        4176.0,
        4220.0,
        atr=30.0,
        price=4180.0,
    )
    result = _structural_room_gate(
        parent_zone=parent,
        direction="SHORT",
        path_start=4180.0,
        destination={"price": 4140.0},
        entry=None,
        invalidation=None,
    )
    assert result["state"] == "STRUCTURAL_ROOM_OK"
    assert result["blocked"] is False
    assert result["distance_parent_atr"] > 0.50



def test_v349_builds_causal_h2_from_completed_h1_pairs():
    start = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    bars = []
    for i in range(6):
        bars.append(
            SimpleNamespace(
                timestamp=start + timedelta(hours=i),
                open=100.0 + i,
                high=101.0 + i,
                low=99.0 + i,
                close=100.5 + i,
            )
        )
    frame = _h2_frame_from_h1(
        bars,
        as_of=start + timedelta(hours=6),
    )
    assert len(frame) == 3
    assert float(frame.iloc[0]["open"]) == 100.0
    assert float(frame.iloc[0]["close"]) == 101.5
    assert float(frame.iloc[0]["high"]) == 102.0
    assert float(frame.iloc[0]["low"]) == 99.0


def test_v349_zone_condition_decays_after_repeated_deep_touches():
    zone = _zone_row("degraded", "H4", "LONG", 95.0, 105.0)
    zone["lifecycle"] = {
        "freshness": "DEEPLY_MITIGATED",
        "touch_count": 2,
        "mitigation_depth": 1.0,
    }
    assert _zone_condition(zone) == "NEAR_EXHAUSTED"

    fresh = _zone_row("fresh", "H1", "LONG", 90.0, 94.0)
    fresh["lifecycle"] = {
        "freshness": "FRESH",
        "touch_count": 0,
        "mitigation_depth": 0.0,
    }
    assert _zone_condition(fresh) == "FRESH"


def test_v349_structural_path_is_single_direction_and_maps_deeper_zone_then_sr():
    h4_demand = _zone_row(
        "h4-demand",
        "H4",
        "LONG",
        4144.56,
        4175.17,
        atr=35.56,
        price=4182.0,
    )
    h4_demand["lifecycle"] = {
        "freshness": "DEEPLY_MITIGATED",
        "touch_count": 2,
        "mitigation_depth": 1.0,
    }
    h4_demand["condition"] = _zone_condition(h4_demand)

    h1_demand = _zone_row(
        "h1-demand",
        "H1",
        "LONG",
        4124.76,
        4134.17,
        atr=15.26,
        price=4182.0,
    )
    h1_demand["lifecycle"] = {
        "freshness": "FRESH",
        "touch_count": 0,
        "mitigation_depth": 0.0,
    }
    h1_demand["condition"] = _zone_condition(h1_demand)

    result = _structural_path(
        direction="SHORT",
        start_price=4182.0,
        active_zones=[h4_demand, h1_demand],
        support_resistance=[
            {
                "kind": "SUPPORT",
                "price": 4117.2,
                "strength": 2.0,
                "sources": ["H2_SWING_LOW", "PRIOR_DAY_LOW"],
            }
        ],
        liquidity=[
            {
                "price": 4117.0,
                "sources": ["H1_SWING_LOW"],
            }
        ],
        parent_atr=32.0,
    )
    assert result["direction"] == "SHORT"
    assert result["state"] == "PATH_AVAILABLE"
    checkpoints = result["checkpoints"]
    assert checkpoints[0]["zone_id"] == "h4-demand"
    assert checkpoints[0]["condition"] == "NEAR_EXHAUSTED"
    assert checkpoints[1]["zone_id"] == "h1-demand"
    assert checkpoints[1]["condition"] == "FRESH"
    assert checkpoints[2]["type"] == "SUPPORT_RESISTANCE"
    assert checkpoints[2]["price"] == 4117.2



def test_v350_failure_path_maps_deeper_demand_and_h2_cluster_only_after_parent_break():
    parent = _zone_row(
        "main-h4-demand",
        "H4",
        "LONG",
        4144.56,
        4175.17,
        atr=35.567,
        price=4147.0,
    )
    parent["lifecycle"] = {
        "freshness": "DEEPLY_MITIGATED",
        "touch_count": 2,
        "mitigation_depth": 1.0,
    }
    parent["condition"] = _zone_condition(parent)

    h1_demand = _zone_row(
        "fresh-h1-demand",
        "H1",
        "LONG",
        4124.76,
        4134.17,
        atr=15.26,
        price=4147.0,
    )
    h1_demand["lifecycle"] = {
        "freshness": "FRESH",
        "touch_count": 0,
        "mitigation_depth": 0.0,
    }
    h1_demand["condition"] = _zone_condition(h1_demand)

    lower_h4 = _zone_row(
        "lower-h4-demand",
        "H4",
        "LONG",
        4065.54,
        4085.82,
        atr=29.64,
        price=4147.0,
    )
    lower_h4["lifecycle"] = {
        "freshness": "FRESH",
        "touch_count": 0,
        "mitigation_depth": 0.0,
    }
    lower_h4["condition"] = _zone_condition(lower_h4)

    result = _conditional_failure_path(
        parent_zone=parent,
        direction="LONG",
        active_zones=[parent, h1_demand, lower_h4],
        support_resistance=[
            {"kind": "FLIP", "price": 4120.99, "strength": 2.0, "sources": ["H2_SWING_HIGH", "H2_SWING_LOW"]},
            {"kind": "FLIP", "price": 4116.436, "strength": 5.0, "sources": ["H2_SWING_HIGH", "H2_SWING_LOW"]},
            {"kind": "FLIP", "price": 4113.07, "strength": 2.0, "sources": ["H2_SWING_HIGH", "H2_SWING_LOW"]},
        ],
        liquidity=[],
        parent_atr=35.567,
    )
    assert result["state"] == "CONDITIONAL_ONLY"
    assert result["failure_direction"] == "SHORT"
    assert result["trigger"] < 4144.56
    checkpoints = result["checkpoints"]
    assert checkpoints[0]["zone_id"] == "fresh-h1-demand"
    assert checkpoints[1]["type"] == "SUPPORT_RESISTANCE"
    assert checkpoints[1]["low"] <= 4113.07
    assert checkpoints[1]["high"] >= 4120.99
    assert checkpoints[-1]["zone_id"] == "lower-h4-demand"


def test_v364_degraded_near_zone_cannot_override_fresh_main_reversal_zone():
    price = 100.0
    degraded_near = _zone_row(
        "h4-degraded-supply",
        "H4",
        "SHORT",
        99.0,
        101.0,
        price=price,
        score=92.0,
    )
    degraded_near.update(
        {
            "structural_bos": True,
            "departure_range_atr": 1.8,
            "departure_body_fraction": 0.70,
            "base_range_atr": 0.70,
            "lifecycle": {
                "freshness": "DEEPLY_MITIGATED",
                "touch_count": 3,
                "mitigation_depth": 0.90,
            },
        }
    )
    degraded_near["condition"] = _zone_condition(degraded_near)

    fresh_main = _zone_row(
        "h4-fresh-demand",
        "H4",
        "LONG",
        94.0,
        97.0,
        price=price,
        score=84.0,
    )
    fresh_main.update(
        {
            "structural_bos": True,
            "departure_range_atr": 1.4,
            "departure_body_fraction": 0.62,
            "base_range_atr": 0.72,
            "lifecycle": {
                "freshness": "FRESH",
                "touch_count": 0,
                "mitigation_depth": 0.0,
            },
        }
    )
    fresh_main["condition"] = _zone_condition(fresh_main)

    classified = _classify_hierarchy(
        [degraded_near, fresh_main],
        price_now=price,
    )
    parent, _, selection = _select_parent_and_refinement(
        classified,
        price_now=price,
    )
    assert parent["zone_id"] == "h4-fresh-demand"
    assert parent["main_reversal_eligible"] is True
    assert selection == "H4_PARENT"


def test_v364_local_mss_ignores_old_news_spike_and_confirms_reclaim_break():
    start = datetime(2026, 10, 2, 10, 0, tzinfo=UTC)
    bars = []
    for i in range(24):
        px = 102.0
        high = 110.0 if i == 20 else 102.6
        bars.append(
            SimpleNamespace(
                timestamp=start + timedelta(minutes=5 * i),
                open=px,
                high=high,
                low=101.4,
                close=102.1,
            )
        )
    bars.extend(
        [
            SimpleNamespace(
                timestamp=start + timedelta(minutes=5 * 24),
                open=101.0,
                high=99.0,
                low=97.4,
                close=98.4,
            ),
            SimpleNamespace(
                timestamp=start + timedelta(minutes=5 * 25),
                open=98.5,
                high=100.4,
                low=98.0,
                close=100.2,
            ),
            SimpleNamespace(
                timestamp=start + timedelta(minutes=5 * 26),
                open=100.2,
                high=101.0,
                low=100.0,
                close=100.8,
            ),
        ]
    )
    zone = {
        "timeframe": "H1",
        "direction": "LONG",
        "low": 98.0,
        "high": 100.0,
        "proximal": 99.0,
        "distal": 98.0,
        "atr": 2.0,
    }
    result = _micro_confirmation(
        zone,
        bars_m5=bars,
        bars_m15=[],
        price_now=100.8,
        as_of=bars[-1].timestamp + timedelta(minutes=5),
    )
    assert result["early_confirmed"] is True
    assert result["confirmed"] is True
    assert result["stage"] == "REVERSAL_CONFIRMED"
    assert result["mss_definition"] == "LOCAL_RECLAIM_EXTREME_BREAK"
    assert result["mss_level"] < 105.0


def test_v364_sweep_reclaim_can_arm_early_demo_before_full_local_mss():
    start = datetime(2026, 10, 2, 10, 0, tzinfo=UTC)
    bars = _bars("M5", start, 24, timedelta(minutes=5), 102.0)
    bars.extend(
        [
            SimpleNamespace(
                timestamp=start + timedelta(minutes=5 * 24),
                open=100.5,
                high=99.0,
                low=97.4,
                close=98.4,
            ),
            SimpleNamespace(
                timestamp=start + timedelta(minutes=5 * 25),
                open=98.5,
                high=100.4,
                low=98.0,
                close=100.1,
            ),
        ]
    )
    zone = {
        "timeframe": "H1",
        "direction": "LONG",
        "low": 98.0,
        "high": 100.0,
        "proximal": 99.0,
        "distal": 98.0,
        "atr": 2.0,
    }
    result = _micro_confirmation(
        zone,
        bars_m5=bars,
        bars_m15=[],
        price_now=100.1,
        as_of=bars[-1].timestamp + timedelta(minutes=5),
    )
    assert result["early_confirmed"] is True
    assert result["confirmed"] is False
    assert result["stage"] == "EARLY_REVERSAL_CONFIRMED"
    assert result["entry_low"] is not None
    assert result["invalidation"] is not None

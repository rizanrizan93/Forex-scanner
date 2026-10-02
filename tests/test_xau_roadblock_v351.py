from __future__ import annotations

from fx_scanner.xau_sd_liquidity_engine_v342 import (
    _classify_hierarchy,
    _roadblock_room_gate,
    _roadblocks,
    _structural_destination,
)


def _zone(zone_id, timeframe, direction, low, high, *, atr=10.0, score=80.0, price=100.0):
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


def test_v351_near_roadblock_reduces_usable_room():
    price = 100.0
    zones = [
        _zone("h4-demand", "H4", "LONG", 95.0, 101.0, atr=10.0, price=price),
        _zone("h1-supply", "H1", "SHORT", 103.0, 105.0, atr=5.0, price=price),
        _zone("h4-supply", "H4", "SHORT", 120.0, 125.0, atr=10.0, price=price),
    ]
    active = _classify_hierarchy(zones, price_now=price)
    destination = _structural_destination(
        direction="LONG",
        start_price=price,
        active_zones=active,
    )
    roadblocks = _roadblocks(
        direction="LONG",
        start_price=price,
        active_zones=active,
        destination=destination,
        parent_zone_id="h4-demand",
        parent_atr=10.0,
        entry=100.0,
        invalidation=95.0,
    )
    assert roadblocks[0]["zone_id"] == "h1-supply"
    assert roadblocks[0]["distance_parent_atr"] == 0.3
    assert roadblocks[0]["planned_rr_to_roadblock"] == 0.6
    assert roadblocks[0]["reduces_room"] is True
    assert roadblocks[0]["status"] == "BLOCKS_ENTRY_ROOM"
    gate = _roadblock_room_gate(roadblocks)
    assert gate["blocked"] is True
    assert gate["state"] == "ROADBLOCK_ROOM_TOO_SMALL"


def test_v351_no_roadblock_is_explicit():
    gate = _roadblock_room_gate([])
    assert gate["blocked"] is False
    assert gate["state"] == "NO_ROADBLOCK_BEFORE_DESTINATION"

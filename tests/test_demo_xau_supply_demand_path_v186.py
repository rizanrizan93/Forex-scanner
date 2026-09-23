from fx_scanner.demo_xau_supply_demand_atlas_v182 import (
    _build_path_map,
    _true_nearest_zone,
)


def _zone(
    zone_id,
    direction,
    low,
    high,
    *,
    distance,
    score=60.0,
    timeframe="H1",
):
    return {
        "zone_id": zone_id,
        "timeframe": timeframe,
        "zone_class": "IMBALANCE",
        "pattern": "RBR" if direction == "LONG" else "RBD",
        "direction": direction,
        "low": float(low),
        "high": float(high),
        "proximal": float(high if direction == "LONG" else low),
        "distal": float(low if direction == "LONG" else high),
        "status": "ACTIVE_WATCH_PREPARE_ONLY",
        "age_bucket": "H1_0_24H",
        "distance_points": float(distance),
        "distance_atr": float(distance) / 20.0,
        "research_score": float(score),
        "htf_nesting_count": 2,
        "strategic_alignment": "NETRAL",
        "session_context": "NY_OPEN_2030_2229_WIB",
        "correct_side": True,
        "lifecycle": {"active": True, "freshness": "FRESH"},
        "approach": {"state": "APPROACHING"},
        "liquidity": {"confluence_count": 1},
        "nested_in": [],
    }


def test_nearest_supply_is_geometric_not_best_ranked():
    zones = (
        _zone("near", "SHORT", 4342, 4347, distance=40, score=55),
        _zone("far-high-score", "SHORT", 4593, 4627, distance=300, score=95),
    )
    nearest = _true_nearest_zone(zones, direction="SHORT")
    assert nearest["zone_id"] == "near"


def test_demand_to_supply_path_selects_closest_opposing_supply():
    zones = (
        _zone("d1", "LONG", 4274, 4301, distance=0, score=68),
        _zone("s1", "SHORT", 4342, 4347, distance=42, score=60),
        _zone("s2", "SHORT", 4385, 4398, distance=85, score=80),
    )
    levels = (
        {"source": "H1_SWING_HIGH", "price": 4331.0},
        {"source": "SESSION_NEW_YORK_HIGH", "price": 4336.0},
    )
    path_map = _build_path_map(
        payloads=zones,
        levels=levels,
        last_price=4284.0,
    )
    path = path_map["demand_to_supply"]
    assert path["source_zone"]["zone_id"] == "d1"
    assert path["primary_opposing_zone"]["zone_id"] == "s1"
    assert path["reaction_direction"] == "LONG"
    assert path["state"] == "SOURCE_ZONE_ENTERED_WAIT_REACTION_CONFIRMATION"
    prices = [row["price"] for row in path["internal_targets"]]
    assert 4331.0 in prices


def test_supply_to_demand_path_is_symmetric():
    zones = (
        _zone("d1", "LONG", 4274, 4301, distance=42),
        _zone("d2", "LONG", 4235, 4257, distance=80),
        _zone("s1", "SHORT", 4342, 4347, distance=0),
    )
    levels = (
        {"source": "H1_SWING_LOW", "price": 4320.0},
        {"source": "SESSION_LONDON_LOW", "price": 4310.0},
    )
    path_map = _build_path_map(
        payloads=zones,
        levels=levels,
        last_price=4344.0,
    )
    path = path_map["supply_to_demand"]
    assert path["source_zone"]["zone_id"] == "s1"
    assert path["primary_opposing_zone"]["zone_id"] == "d1"
    assert path["reaction_direction"] == "SHORT"
    assert path["state"] == "SOURCE_ZONE_ENTERED_WAIT_REACTION_CONFIRMATION"


def test_path_engine_never_has_execution_authority():
    zones = (
        _zone("d1", "LONG", 4274, 4301, distance=0),
        _zone("s1", "SHORT", 4342, 4347, distance=40),
    )
    path_map = _build_path_map(payloads=zones, levels=(), last_price=4284)
    assert path_map["execution_authority"] is False
    assert path_map["execution_influence"] is False
    assert path_map["active_path"]["execution_authority"] is False

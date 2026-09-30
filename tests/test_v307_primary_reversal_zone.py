from fx_scanner.demo_xau_supply_demand_atlas_v182 import (
    _build_path_map,
    _primary_reversal_zone,
)


def _zone(
    zone_id: str,
    direction: str,
    low: float,
    high: float,
    *,
    distance_atr: float,
    mitigation: float,
    freshness: str,
    nesting: int,
    structural: bool,
    research_score: float,
):
    return {
        "zone_id": zone_id,
        "timeframe": "H1",
        "zone_class": "STRUCTURAL" if structural else "IMBALANCE",
        "pattern": "STRUCTURAL_DEMAND" if direction == "LONG" else "STRUCTURAL_SUPPLY",
        "direction": direction,
        "low": low,
        "high": high,
        "proximal": high if direction == "LONG" else low,
        "distal": low if direction == "LONG" else high,
        "status": "IN_ZONE_PREPARE_ONLY" if distance_atr == 0 else "ACTIVE_WATCH_PREPARE_ONLY",
        "distance_points": 0.0 if distance_atr == 0 else distance_atr * 10.0,
        "distance_atr": distance_atr,
        "atr_points": 10.0,
        "research_score": research_score,
        "htf_nesting_count": nesting,
        "strategic_alignment": "BERLAWANAN",
        "session_context": "NY_OPEN_2030_2229_WIB",
        "correct_side": True,
        "structural_bos": structural,
        "lifecycle": {
            "active": True,
            "freshness": freshness,
            "touch_count": 1,
            "mitigation_depth": mitigation,
        },
        "approach": {"state": "APPROACHING"},
        "liquidity": {},
        "nested_in": [f"H4:{zone_id}:parent"] * nesting,
    }


def test_v307_deeply_mitigated_nearest_demand_cannot_outrank_healthier_reversal_zone():
    nearest_consumed = _zone(
        "near-consumed",
        "LONG",
        4181.0,
        4191.0,
        distance_atr=0.0,
        mitigation=0.95,
        freshness="DEEPLY_MITIGATED",
        nesting=1,
        structural=True,
        research_score=72.0,
    )
    healthier_deeper = _zone(
        "healthy-primary",
        "LONG",
        4166.0,
        4182.0,
        distance_atr=0.2,
        mitigation=0.35,
        freshness="PARTIALLY_MITIGATED",
        nesting=2,
        structural=True,
        research_score=66.0,
    )

    selected = _primary_reversal_zone(
        (nearest_consumed, healthier_deeper),
        direction="LONG",
    )

    assert selected is not None
    assert selected["zone_id"] == "healthy-primary"
    assert selected["zone_role"] == "PRIMARY_REVERSAL_ZONE"
    assert selected["selection_policy"] == "V309_REACHABLE_PRIMARY_REVERSAL_AUTHORITY"


def test_v307_short_bias_keeps_short_path_until_confirmed_handoff():
    demand = _zone(
        "primary-demand",
        "LONG",
        4166.0,
        4182.0,
        distance_atr=0.0,
        mitigation=0.35,
        freshness="PARTIALLY_MITIGATED",
        nesting=2,
        structural=True,
        research_score=66.0,
    )
    supply = _zone(
        "primary-supply",
        "SHORT",
        4258.0,
        4267.0,
        distance_atr=7.0,
        mitigation=0.0,
        freshness="FRESH",
        nesting=2,
        structural=True,
        research_score=84.0,
    )
    result = _build_path_map(
        payloads=(demand, supply),
        levels=(),
        last_price=4177.0,
        strategic_bias="SHORT",
    )

    assert result["primary_reversal_demand"]["zone_id"] == "primary-demand"
    assert result["primary_reversal_supply"]["zone_id"] == "primary-supply"
    assert result["nearest_demand"]["zone_id"] == "primary-demand"
    assert result["display_policy"] == "PRIMARY_REVERSAL_ZONE_ONLY"
    assert result["active_path"]["reaction_direction"] == "SHORT"
    assert result["active_path"]["primary_opposing_zone"]["zone_id"] == "primary-demand"



def test_v309_remote_high_nesting_supply_cannot_beat_reachable_fresh_supply():
    reachable = _zone(
        "reachable-supply",
        "SHORT",
        4257.0,
        4266.0,
        distance_atr=5.0,
        mitigation=0.0,
        freshness="FRESH",
        nesting=2,
        structural=True,
        research_score=84.0,
    )
    remote = _zone(
        "remote-supply",
        "SHORT",
        4408.0,
        4431.0,
        distance_atr=13.6,
        mitigation=0.0,
        freshness="FRESH",
        nesting=3,
        structural=True,
        research_score=70.0,
    )

    selected = _primary_reversal_zone(
        (reachable, remote),
        direction="SHORT",
    )

    assert selected is not None
    assert selected["zone_id"] == "reachable-supply"
    assert selected["selection_policy"] == "V309_REACHABLE_PRIMARY_REVERSAL_AUTHORITY"
    assert selected["nearest_healthy_distance_atr"] == 5.0
    assert selected["forward_relevance_ceiling_atr"] == 8.0

from fx_scanner.xau_rizan_style_path_engine_v303 import (
    CONTRACT,
    build_rizan_style_path_engine,
)


def _zone(zone_id: str, direction: str, low: float, high: float, timeframe: str = "H1"):
    return {
        "zone_id": zone_id,
        "direction": direction,
        "low": low,
        "high": high,
        "timeframe": timeframe,
        "status": "ACTIVE_WATCH_PREPARE_ONLY",
        "lifecycle": {"active": True, "touch_count": 0},
    }


def _atlas(price: float = 4188.0):
    demand = _zone("d1", "LONG", 4124.0, 4139.0)
    supply1 = _zone("s1", "SHORT", 4200.0, 4212.0)
    supply2 = _zone("s2", "SHORT", 4262.0, 4273.0, "H4")
    long_path = {
        "state": "SOURCE_ZONE_WATCH",
        "reaction_direction": "LONG",
        "source_zone": demand,
        "primary_opposing_zone": supply1,
        "terminal_target_zone": supply1,
        "destination_stack": [supply1, supply2],
        "checkpoint_targets": [
            {"source": "ROUND_NUMBER", "price": 4160.0},
            {"source": "ROUND_NUMBER", "price": 4190.0},
        ],
        "internal_targets": [{"source": "H1_SWING_HIGH", "price": 4196.0}],
        "reaction_target": {"source": "H1_SWING_HIGH", "price": 4196.0},
    }
    short_path = {
        "state": "SOURCE_ZONE_WATCH",
        "reaction_direction": "SHORT",
        "source_zone": supply1,
        "primary_opposing_zone": demand,
        "terminal_target_zone": demand,
        "destination_stack": [demand],
        "checkpoint_targets": [{"source": "ROUND_NUMBER", "price": 4180.0}],
        "internal_targets": [{"source": "H1_SWING_LOW", "price": 4166.0}],
        "reaction_target": {"source": "H1_SWING_LOW", "price": 4166.0},
    }
    return {
        "last_closed_m15_price": price,
        "path_map": {
            "active_path": long_path,
            "demand_to_supply": long_path,
            "supply_to_demand": short_path,
        },
        "m5_path_projection": {
            "current_leg": {
                "direction": "LONG",
                "source_zone": demand,
                "micro_refinement": {"state": "M5_REFINEMENT_CONFIRMED_SHADOW"},
            },
            "next_leg": {
                "direction": "SHORT",
                "source_zone": supply1,
                "parent_matches_current_terminal": True,
                "micro_refinement": {"state": "WAIT_RECLAIM"},
            },
        },
    }


def test_v303_builds_branching_forecast_and_key_levels() -> None:
    result = build_rizan_style_path_engine(
        atlas_evaluation=_atlas(),
        price_now=4188.0,
    )
    assert result["contract"] == CONTRACT
    assert result["name"] == "RIZAN STYLE PATH ENGINE"
    assert result["state"] == "APPROACH_DECISION_ZONE"
    assert result["active_direction"] == "LONG"
    assert result["next_decision_zone"]["zone_id"] == "s1"
    assert result["key_levels"]["rejection_reclaim_key"] == 4200.0
    assert result["key_levels"]["break_acceptance_key"] == 4212.0
    assert result["rejection_branch"]["direction"] == "SHORT"
    assert result["rejection_branch"]["source_matches_decision_zone"] is True
    assert result["acceptance_branch"]["direction"] == "LONG"
    assert result["execution_authority"] is False
    assert result["execution_influence"] is False


def test_v303_inside_zone_becomes_active_decision_state() -> None:
    result = build_rizan_style_path_engine(
        atlas_evaluation=_atlas(price=4206.0),
        price_now=4206.0,
    )
    assert result["state"] == "DECISION_ZONE_ACTIVE"
    assert result["decision_zone_relation"] == "INSIDE"
    assert result["branch_preference"] == "WAIT_DECISION"


def test_v303_break_acceptance_advances_to_next_destination() -> None:
    result = build_rizan_style_path_engine(
        atlas_evaluation=_atlas(price=4214.0),
        price_now=4214.0,
    )
    assert result["state"] == "DECISION_ZONE_ACCEPTED_BREAK"
    assert result["branch_preference"] == "ACCEPTANCE_BRANCH"
    assert result["acceptance_branch"]["armed"] is True
    assert result["acceptance_branch"]["next_destination_zone"]["zone_id"] == "s2"


def test_v303_m5_confirmation_arms_rejection_branch() -> None:
    atlas = _atlas(price=4197.0)
    atlas["m5_path_projection"]["next_leg"]["micro_refinement"] = {
        "state": "M5_REFINEMENT_CONFIRMED_SHADOW"
    }
    result = build_rizan_style_path_engine(
        atlas_evaluation=atlas,
        price_now=4197.0,
    )
    assert result["state"] == "DECISION_ZONE_REJECTION_CONFIRMED"
    assert result["branch_preference"] == "REJECTION_BRANCH"
    assert result["rejection_branch"]["armed"] is True
    assert result["rejection_branch"]["m5_leg"] == "next_leg"


def test_v303_no_path_fails_closed() -> None:
    result = build_rizan_style_path_engine(
        atlas_evaluation={"last_closed_m15_price": 4188.0, "path_map": {}},
    )
    assert result["state"] == "NO_STRUCTURAL_PATH"
    assert result["active_direction"] is None
    assert result["execution_authority"] is False
    assert result["execution_influence"] is False

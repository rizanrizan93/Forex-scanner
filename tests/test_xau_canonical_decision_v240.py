from fx_scanner.xau_canonical_decision_v240 import build_canonical_xau_decision


def _v226() -> dict:
    return {
        "focus_direction": "LONG",
        "depth_entry_candidate": {
            "direction": "LONG",
            "entry_low": 100.0,
            "entry_high": 102.0,
            "entry_reference": 101.0,
            "source_layer": "M15_NESTED_LOCATOR",
            "display_status": "PREPARE_ONLY_FRESH_FIRST_TOUCH",
            "approach_state": "AHEAD",
            "calibrated_fresh_first_touch": True,
            "historical_context": {
                "h4_parent_rate": 0.71,
                "h1_standalone_rate": 0.70,
                "m15_standalone_rate": 0.74,
            },
        },
        "four_order_ladder": {
            "slots": [
                {"slot":1,"reference_price":101.8,"stage":"PRE_TOUCH_LIMIT_REFERENCE","activation":"FRESH_DEPTH_ENTRY_CANDIDATE"},
                {"slot":2,"reference_price":101.3,"stage":"PRE_TOUCH_LIMIT_REFERENCE","activation":"FRESH_DEPTH_ENTRY_CANDIDATE"},
                {"slot":3,"reference_price":100.8,"stage":"RESERVE_M5_RECLAIM_MSS_RETEST","activation":"M5_RECLAIM_AND_LOCAL_MSS_CONFIRMED"},
                {"slot":4,"reference_price":100.3,"stage":"RESERVE_M5_DISPLACEMENT_RETEST","activation":"M5_DISPLACEMENT_CONFIRMED_AND_RETEST_AVAILABLE"},
            ]
        },
        "long": {
            "h4": {
                "zone": {
                    "zone_id": "h4-demand",
                    "direction": "LONG",
                    "low": 98.0,
                    "high": 104.0,
                    "atr_points": 4.0,
                }
            }
        },
    }


def _atlas() -> dict:
    return {
        "chart_bars_m15": [],
        "zones": [
            {
                "zone_id":"d1","timeframe":"H1","direction":"LONG",
                "low":99.0,"high":101.0,"research_score":70,
                "lifecycle":{"active":True,"freshness":"FRESH","touch_count":0},
            },
            {
                "zone_id":"m15-s","timeframe":"M15","direction":"SHORT",
                "low":106.0,"high":107.0,"research_score":80,
                "status":"ACTIVE","lifecycle":{"active":True,"freshness":"FRESH","touch_count":0},
            },
            {
                "zone_id":"h1-s","timeframe":"H1","direction":"SHORT",
                "low":110.0,"high":112.0,"research_score":75,
                "status":"ACTIVE","lifecycle":{"active":True,"freshness":"FRESH","touch_count":0},
            },
        ],
        "path_map": {
            "demand_to_supply": {
                "reaction_target": {"price": 106.0},
                "terminal_target_zone": {
                    "zone_id":"h1-s","timeframe":"H1","direction":"SHORT",
                    "low":110.0,"high":112.0,
                    "lifecycle":{"active":True},
                },
                "destination_stack": [
                    {
                        "zone_id":"h1-s","timeframe":"H1","direction":"SHORT",
                        "low":110.0,"high":112.0,
                        "lifecycle":{"active":True},
                    }
                ],
            }
        },
    }


def test_v240_uses_same_v229_plan_for_entry_sl_tp() -> None:
    state = build_canonical_xau_decision(
        v226_evaluation=_v226(),
        atlas_evaluation=_atlas(),
        price_now=103.0,
        path_direction="LONG",
    )
    assert state["state"] == "CANONICAL_PLAN_READY"
    assert state["authority"] == "V229_CANONICAL_GEOMETRY"
    assert state["direction"] == "LONG"
    assert state["entry_low"] == 100.0
    assert state["entry_high"] == 102.0
    assert state["sl"] < 98.0
    assert state["tp1"] > state["entry_reference"]
    assert state["tp2"] >= state["tp1"]
    assert state["structural_targets"]


def test_v240_direction_conflict_fails_closed() -> None:
    state = build_canonical_xau_decision(
        v226_evaluation=_v226(),
        atlas_evaluation=_atlas(),
        price_now=103.0,
        path_direction="SHORT",
    )
    assert state["state"] == "CONFLICT_WAIT"
    assert "DIRECTION_V226_VS_PATH" in state["conflicts"]


def test_v240_stale_state_fails_closed() -> None:
    state = build_canonical_xau_decision(
        v226_evaluation=_v226(),
        atlas_evaluation=_atlas(),
        price_now=103.0,
        path_direction="LONG",
        v226_age_seconds=601.0,
    )
    assert state["state"] == "STALE_WAIT"
    assert state["sl"] is not None
    assert "V226_STALE" in state["stale_reasons"]


def test_v240_saved_geometry_mismatch_is_not_authoritative() -> None:
    state = build_canonical_xau_decision(
        v226_evaluation=_v226(),
        atlas_evaluation=_atlas(),
        price_now=103.0,
        path_direction="LONG",
        saved_v229_geometry={
            "direction":"LONG",
            "candidate_low":90.0,
            "candidate_high":91.0,
        },
    )
    assert state["saved_geometry_match"] is False
    assert state["state"] == "CONFLICT_WAIT"
    assert "SAVED_V229_GEOMETRY_MISMATCH" in state["conflicts"]


def test_v240_exposes_nearest_supply_demand_and_destination() -> None:
    state = build_canonical_xau_decision(
        v226_evaluation=_v226(),
        atlas_evaluation=_atlas(),
        price_now=103.0,
        path_direction="LONG",
    )
    assert state["nearest_demand"]["zone_id"] == "d1"
    assert state["nearest_supply"]["zone_id"] == "m15-s"
    assert state["likely_destination"]["target_price"] > 103.0
    assert state["likely_destination"]["timeframe"] == "M15"



def test_v2401_ranks_primary_reversal_watch_with_v212_evidence() -> None:
    state = build_canonical_xau_decision(
        v226_evaluation=_v226(),
        atlas_evaluation=_atlas(),
        price_now=103.0,
        path_direction="LONG",
        zone_probabilities=[
            {
                "zone_id": "m15-s",
                "destination": {"p_touch": 0.90},
                "reaction": {
                    "p_hold_050": 0.70,
                    "p_break": 0.20,
                    "confidence": "HIGH_HISTORICAL_SUPPORT",
                    "estimate_type": "SHRUNK_EMPIRICAL_HOLDOUT_ESTIMATE",
                    "not_calibrated_probability_claim": True,
                },
            },
            {
                "zone_id": "h1-s",
                "destination": {"p_touch": 0.80},
                "reaction": {
                    "p_hold_050": 0.60,
                    "p_break": 0.30,
                    "confidence": "MEDIUM_HISTORICAL_SUPPORT",
                    "estimate_type": "SHRUNK_EMPIRICAL_HOLDOUT_ESTIMATE",
                    "not_calibrated_probability_claim": True,
                },
            },
        ],
    )
    watch = state["primary_reversal_watch"]
    assert watch["zone_id"] == "m15-s"
    assert abs(watch["research_joint_score"] - 0.63) < 1e-12
    assert watch["not_calibrated_probability_claim"] is True


def test_v2401_does_not_invent_reversal_probability_without_v212_evidence() -> None:
    state = build_canonical_xau_decision(
        v226_evaluation=_v226(),
        atlas_evaluation=_atlas(),
        price_now=103.0,
        path_direction="LONG",
        zone_probabilities=[],
    )
    assert state["primary_reversal_watch"] == {}


def test_v240_discovers_active_path_source_missing_from_flat_zone_list() -> None:
    """Regression: 29 Sep local H1 supply must supersede stale 4357 V226 geometry."""
    v226 = {
        "focus_direction": "SHORT",
        "depth_entry_candidate": {
            "direction": "SHORT",
            "entry_low": 4357.644579093432,
            "entry_high": 4359.524467329546,
            "entry_reference": 4358.397659318671,
            "source_layer": "M15_NESTED_LOCATOR",
            "display_status": "PREPARE_ONLY_FRESH_FIRST_TOUCH",
            "pre_touch_execution_eligible": True,
            "confirmation_execution_eligible": True,
            "calibrated_fresh_first_touch": True,
            "historical_context": {},
        },
        "short": {
            "h4": {
                "zone": {
                    "zone_id": "old-h4-supply",
                    "timeframe": "H4",
                    "direction": "SHORT",
                    "low": 4357.51,
                    "high": 4365.51,
                    "atr_points": 33.8,
                }
            }
        },
        "four_order_ladder": {"slots": []},
    }
    current_h1 = {
        "zone_id": "current-h1-supply",
        "timeframe": "H1",
        "direction": "SHORT",
        "low": 4136.55,
        "high": 4160.48,
        "proximal": 4136.55,
        "research_score": 67.82,
        "status": "APPROACHING_PREPARE_ONLY",
        "lifecycle": {
            "active": True,
            "freshness": "PARTIALLY_MITIGATED",
            "touch_count": 2,
        },
    }
    atlas = {
        # Deliberately omit current_h1 from the flat list. This is the production
        # condition that caused V240 to keep showing the 4357 V226 candidate.
        "zones": [
            {
                "zone_id": "far-flat-supply",
                "timeframe": "H1",
                "direction": "SHORT",
                "low": 4257.52,
                "high": 4266.31,
                "research_score": 89.17,
                "lifecycle": {"active": True, "freshness": "FRESH", "touch_count": 0},
            }
        ],
        "path_map": {
            "active_path": {
                "reaction_direction": "SHORT",
                "source_zone": current_h1,
            }
        },
        "m5_path_projection": {
            "current_leg": {
                "direction": "SHORT",
                "source_zone": current_h1,
            }
        },
        "chart_bars_m15": [],
    }

    state = build_canonical_xau_decision(
        v226_evaluation=v226,
        atlas_evaluation=atlas,
        price_now=4127.42,
        path_direction="SHORT",
    )

    assert state["state"] == "LOCAL_REMAP_WAIT"
    assert state["nearest_supply"]["zone_id"] == "current-h1-supply"
    assert state["local_structure_override"]["zone_id"] == "current-h1-supply"
    assert state["entry_low"] == 4136.55
    assert state["entry_high"] == 4160.48
    assert state["entry_reference"] == 4136.55
    assert state["sl"] is None
    assert state["tp1"] is None
    assert state["tp2"] is None
    assert state["source_layer"] == "ATLAS_LOCAL_H1_WATCH"


def test_v240_local_structure_supersedes_distant_v226_candidate_fail_closed() -> None:
    v226 = {
        "focus_direction": "SHORT",
        "depth_entry_candidate": {
            "direction": "SHORT",
            "entry_low": 4357.64,
            "entry_high": 4359.52,
            "entry_reference": 4358.40,
            "source_layer": "M15_NESTED_LOCATOR",
            "display_status": "PREPARE_ONLY_FRESH_FIRST_TOUCH",
            "pre_touch_execution_eligible": True,
            "confirmation_execution_eligible": True,
            "calibrated_fresh_first_touch": True,
            "historical_context": {},
        },
        "short": {
            "h4": {
                "zone": {
                    "zone_id": "far-h4",
                    "direction": "SHORT",
                    "low": 4357.0,
                    "high": 4365.0,
                    "atr_points": 30.0,
                }
            }
        },
        "four_order_ladder": {"slots": []},
    }
    atlas = {
        "zones": [
            {
                "zone_id": "local-h1-supply",
                "timeframe": "H1",
                "direction": "SHORT",
                "low": 4136.55,
                "high": 4160.48,
                "proximal": 4136.55,
                "research_score": 67.99,
                "lifecycle": {
                    "active": True,
                    "freshness": "PARTIALLY_MITIGATED",
                    "touch_count": 2,
                },
            }
        ],
        "path_map": {},
        "chart_bars_m15": [],
    }

    state = build_canonical_xau_decision(
        v226_evaluation=v226,
        atlas_evaluation=atlas,
        price_now=4128.37,
        path_direction="SHORT",
    )

    assert state["state"] == "LOCAL_REMAP_WAIT"
    assert state["authority"] == "LOCAL_STRUCTURE_WATCH_NO_V229_AUTHORITY"
    assert state["source_layer"] == "ATLAS_LOCAL_H1_WATCH"
    assert state["entry_low"] == 4136.55
    assert state["entry_high"] == 4160.48
    assert state["entry_reference"] == 4136.55
    assert state["sl"] is None
    assert state["tp1"] is None
    assert state["tp2"] is None
    assert state["remap_reasons"] == ["LOCAL_STRUCTURE_AHEAD_OF_V226_CANDIDATE"]
    assert state["local_structure_override"]["zone_id"] == "local-h1-supply"

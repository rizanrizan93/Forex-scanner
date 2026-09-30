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


def test_v240_current_path_direction_overrides_misaligned_v226_research() -> None:
    state = build_canonical_xau_decision(
        v226_evaluation=_v226(),
        atlas_evaluation=_atlas(),
        price_now=103.0,
        path_direction="SHORT",
    )
    assert state["direction"] == "SHORT"
    assert state["state"] == "LOCAL_PATH_WATCH"
    assert state["authority"] == "LOCAL_STRUCTURE_WATCH_NO_V229_AUTHORITY"
    assert state["entry_authorized"] is False
    assert "DIRECTION_V226_VS_CURRENT_PATH" in state["conflicts"]
    assert "V226_CANDIDATE_DIRECTION_MISMATCH" in state["conflicts"]
    assert state["blocking_conflicts"] == []


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



def test_v240_production_regression_old_short_locator_cannot_override_current_long_path() -> None:
    old_v226 = {
        "focus_direction": "SHORT",
        "depth_entry_candidate": {
            "direction": "SHORT",
            "entry_low": 4357.64,
            "entry_high": 4359.52,
            "entry_reference": 4358.40,
            "source_layer": "M15_NESTED_LOCATOR",
        },
        "short": {
            "h4": {
                "zone": {
                    "zone_id": "old-h4",
                    "direction": "SHORT",
                    "low": 4357.51,
                    "high": 4365.51,
                    "atr_points": 30.0,
                }
            }
        },
        "four_order_ladder": {"slots": []},
    }
    demand = {
        "zone_id": "current-demand",
        "timeframe": "H1",
        "direction": "LONG",
        "low": 4114.50,
        "high": 4127.83,
        "proximal": 4127.40,
        "distal": 4114.50,
        "lifecycle": {
            "active": True,
            "freshness": "FIRST_TEST",
            "touch_count": 1,
        },
    }
    supply = {
        "zone_id": "current-supply",
        "timeframe": "H1",
        "direction": "SHORT",
        "low": 4136.55,
        "high": 4160.48,
        "proximal": 4136.55,
        "distal": 4160.48,
        "lifecycle": {
            "active": True,
            "freshness": "PARTIALLY_MITIGATED",
            "touch_count": 3,
        },
    }
    atlas = {
        "zones": [],
        "path_map": {
            "active_path": {
                "reaction_direction": "LONG",
                "source_zone": demand,
                "reaction_target": {"price": 4136.55},
                "primary_opposing_zone": supply,
                "terminal_target_zone": supply,
            },
            "demand_to_supply": {
                "reaction_direction": "LONG",
                "source_zone": demand,
                "reaction_target": {"price": 4136.55},
                "primary_opposing_zone": supply,
                "terminal_target_zone": supply,
            },
        },
        "m5_path_projection": {
            "current_leg": {
                "direction": "LONG",
                "source_zone": demand,
                "terminal_target_zone": supply,
            }
        },
    }

    state = build_canonical_xau_decision(
        v226_evaluation=old_v226,
        atlas_evaluation=atlas,
        price_now=4132.69,
        path_direction="LONG",
    )

    assert state["direction"] == "LONG"
    assert state["direction_source"] == "V182_CURRENT_PATH"
    assert state["state"] == "LOCAL_PATH_WATCH"
    assert state["entry_authorized"] is False
    assert state["active_path_source"]["zone_id"] == "current-demand"
    assert state["entry_low"] == 4114.50
    assert state["entry_high"] == 4127.83
    assert state["sl"] is None
    assert state["tp1"] is None
    assert state["likely_destination"]["target_price"] == 4136.55
    assert state["likely_destination"]["role"] == "PATH_TARGET_WATCH_NOT_ORDER_TP"
    assert "DIRECTION_V226_VS_CURRENT_PATH" in state["conflicts"]
    assert "V226_CANDIDATE_DIRECTION_MISMATCH" in state["conflicts"]


def test_v240_empty_v226_candidate_uses_current_path_source_watch() -> None:
    v226 = {
        "focus_direction": "LONG",
        "depth_entry_candidate": {},
        "four_order_ladder": {"slots": []},
    }
    demand = {
        "zone_id": "fresh-demand",
        "timeframe": "H1",
        "direction": "LONG",
        "low": 100.0,
        "high": 105.0,
        "proximal": 105.0,
        "lifecycle": {"active": True, "freshness": "FIRST_TEST", "touch_count": 1},
    }
    supply = {
        "zone_id": "next-supply",
        "timeframe": "H1",
        "direction": "SHORT",
        "low": 110.0,
        "high": 115.0,
        "lifecycle": {"active": True, "freshness": "FRESH", "touch_count": 0},
    }
    atlas = {
        "zones": [],
        "path_map": {
            "active_path": {
                "reaction_direction": "LONG",
                "source_zone": demand,
                "reaction_target": {"price": 110.0},
                "terminal_target_zone": supply,
            },
            "demand_to_supply": {
                "reaction_direction": "LONG",
                "source_zone": demand,
                "reaction_target": {"price": 110.0},
                "terminal_target_zone": supply,
            },
        },
    }
    state = build_canonical_xau_decision(
        v226_evaluation=v226,
        atlas_evaluation=atlas,
        price_now=106.0,
        path_direction="LONG",
    )
    assert state["state"] == "LOCAL_PATH_WATCH"
    assert state["entry_low"] == 100.0
    assert state["entry_high"] == 105.0
    assert state["entry_authorized"] is False
    assert state["likely_destination"]["target_price"] == 110.0



def test_v2571_marks_path_target_reached_when_price_is_inside_opposing_zone() -> None:
    v226 = {
        "focus_direction": "SHORT",
        "depth_entry_candidate": {
            "direction": "SHORT",
            "entry_low": 4357.64,
            "entry_high": 4359.52,
            "entry_reference": 4358.40,
            "source_layer": "M15_NESTED_LOCATOR",
        },
        "four_order_ladder": {"slots": []},
    }
    demand = {
        "zone_id": "demand-now",
        "timeframe": "H1",
        "direction": "LONG",
        "low": 4114.50,
        "high": 4127.83,
        "proximal": 4127.40,
        "lifecycle": {"active": True, "touch_count": 1},
    }
    supply = {
        "zone_id": "supply-now",
        "timeframe": "H1",
        "direction": "SHORT",
        "low": 4136.55,
        "high": 4160.48,
        "proximal": 4136.55,
        "lifecycle": {"active": True, "touch_count": 4},
    }
    atlas = {
        "zones": [],
        "path_map": {
            "active_path": {
                "reaction_direction": "LONG",
                "source_zone": demand,
                "reaction_target": {"price": 4136.55},
                "primary_opposing_zone": supply,
                "terminal_target_zone": supply,
            },
            "demand_to_supply": {
                "reaction_direction": "LONG",
                "source_zone": demand,
                "reaction_target": {"price": 4136.55},
                "primary_opposing_zone": supply,
                "terminal_target_zone": supply,
            },
        },
    }

    state = build_canonical_xau_decision(
        v226_evaluation=v226,
        atlas_evaluation=atlas,
        price_now=4139.45,
        path_direction="LONG",
    )

    assert state["direction"] == "LONG"
    assert state["entry_authorized"] is False
    assert state["state"] == "TARGET_REACHED_WAIT_HANDOFF"
    assert state["path_completed"] is True
    assert state["path_destination_state"] == "INSIDE_OPPOSING_ZONE"
    assert state["likely_destination"]["role"] == "PATH_TARGET_REACHED"
    assert state["likely_destination"]["target_price"] == 4136.55
    assert state["likely_destination"]["destination_state"] == "INSIDE_OPPOSING_ZONE"


def test_v261_v240_exposes_historical_research_entry_without_broker_authority() -> None:
    state = build_canonical_xau_decision(
        v226_evaluation=_v226(),
        atlas_evaluation=_atlas(),
        price_now=103.0,
        path_direction="LONG",
    )
    research = dict(state["historical_research_entry"])
    assert research["label"] == "HISTORICAL_RESEARCH_ENTRY_NOT_ORDER"
    assert research["direction"] == "LONG"
    assert research["low"] == 100.0
    assert research["high"] == 102.0
    assert research["reference"] == 101.0
    assert research["execution_authority"] is False


def test_v263_v240_confirmation_window_is_visible_but_not_official_entry() -> None:
    source = {
        "zone_id": "local-h1-supply",
        "timeframe": "H1",
        "direction": "SHORT",
        "low": 100.0,
        "high": 120.0,
        "proximal": 100.0,
        "distal": 120.0,
        "atr_points": 10.0,
        "status": "IN_ZONE_PREPARE_ONLY",
        "lifecycle": {
            "active": True,
            "freshness": "PARTIALLY_MITIGATED",
            "touch_count": 3,
        },
    }
    v226 = {
        "focus_direction": "SHORT",
        "depth_entry_candidate": {
            "direction": "SHORT",
            "entry_low": 101.0,
            "entry_high": 104.0,
            "entry_reference": 102.0,
            "source_layer": "V182_ACTIVE_H1_HISTORICAL_HOTSPOT",
            "source_timeframe": "H1",
            "source_zone": source,
            "display_status": "CONFIRMATION_ONLY_RETESTED_HTF",
            "htf_retested": True,
            "retest_confirmation_eligible": True,
            "pre_touch_execution_eligible": False,
            "confirmation_execution_eligible": True,
            "historical_context": {"h1_standalone_rate": 0.70},
        },
        "four_order_ladder": {
            "slots": [
                {"slot": 1, "lot": 0.01, "reference_price": 101.4},
                {"slot": 2, "lot": 0.01, "reference_price": 102.0},
                {"slot": 3, "lot": 0.01, "reference_price": 102.6},
                {"slot": 4, "lot": 0.01, "reference_price": 103.2},
            ]
        },
        "short": {},
    }
    demand = {
        "zone_id": "terminal-h1-demand",
        "timeframe": "H1",
        "direction": "LONG",
        "low": 95.0,
        "high": 98.0,
        "status": "ACTIVE",
        "lifecycle": {"active": True},
    }
    atlas = {
        "chart_bars_m15": [],
        "zones": [source, demand],
        "path_map": {
            "active_path": {
                "reaction_direction": "SHORT",
                "source_zone": source,
                "reaction_target": {"price": 98.0},
                "terminal_target_zone": demand,
                "primary_opposing_zone": demand,
            },
            "supply_to_demand": {"destination_stack": [demand]},
        },
    }

    state = build_canonical_xau_decision(
        v226_evaluation=v226,
        atlas_evaluation=atlas,
        price_now=110.0,
        path_direction="SHORT",
    )

    assert state["state"] == "CONFIRMATION_WINDOW_ARMED"
    assert state["authority"] == "V229_CONFIRMATION_WINDOW_PENDING_M5"
    assert state["entry_authorized"] is False
    assert state["confirmation_window_armed"] is True
    assert state["terminal_rr_recheck_required"] is True
    window = dict(state["confirmation_entry_window"])
    assert 100.0 <= window["low"] < window["high"] <= 120.0
    assert state["active_entry_zone"]["role"] == "M5_CONFIRMATION_WINDOW_NOT_ORDER"
    assert state["historical_research_entry"]["low"] == 101.0
    assert state["historical_research_entry"]["high"] == 104.0


def test_v289_operational_zone_roles_hide_raw_overlap_from_primary_dashboard() -> None:
    demand = {
        "zone_id": "active-demand",
        "timeframe": "H1",
        "direction": "LONG",
        "low": 4167.34,
        "high": 4181.59,
        "proximal": 4176.67,
        "status": "IN_ZONE_PREPARE_ONLY",
        "lifecycle": {"active": True, "freshness": "PARTIALLY_MITIGATED", "touch_count": 1},
    }
    overlapping_supply = {
        "zone_id": "raw-overlap-supply",
        "timeframe": "H1",
        "direction": "SHORT",
        "low": 4179.03,
        "high": 4197.99,
        "proximal": 4179.42,
        "status": "APPROACHING_PREPARE_ONLY",
        "research_score": 80.0,
        "lifecycle": {"active": True, "freshness": "PARTIALLY_MITIGATED", "touch_count": 4},
    }
    forward_supply = {
        "zone_id": "forward-opposing-supply",
        "timeframe": "H1",
        "direction": "SHORT",
        "low": 4194.22,
        "high": 4200.19,
        "proximal": 4194.73,
        "status": "ACTIVE_WATCH_PREPARE_ONLY",
        "lifecycle": {"active": True, "freshness": "FRESH", "touch_count": 0},
    }
    atlas = {
        "zones": [demand, overlapping_supply, forward_supply],
        "path_map": {
            "active_path": {
                "reaction_direction": "LONG",
                "source_zone": demand,
                "reaction_target": {"price": 4190.0},
                "primary_opposing_zone": forward_supply,
                "terminal_target_zone": forward_supply,
            },
            "demand_to_supply": {
                "reaction_direction": "LONG",
                "source_zone": demand,
                "reaction_target": {"price": 4190.0},
                "primary_opposing_zone": forward_supply,
                "terminal_target_zone": forward_supply,
            },
        },
    }
    v226 = {
        "focus_direction": "LONG",
        "depth_entry_candidate": {},
        "four_order_ladder": {"slots": []},
    }

    state = build_canonical_xau_decision(
        v226_evaluation=v226,
        atlas_evaluation=atlas,
        price_now=4177.60,
        path_direction="LONG",
    )

    assert state["direction"] == "LONG"
    assert state["nearest_demand"]["zone_id"] == "active-demand"
    assert state["nearest_supply"]["zone_id"] == "forward-opposing-supply"
    assert state["raw_nearest_supply"]["zone_id"] == "raw-overlap-supply"
    assert state["zone_role_state"]["raw_overlap_detected"] is True
    assert state["zone_role_state"]["source_role"] == "DEMAND_SOURCE"
    assert state["zone_role_state"]["opposing_role"] == "SUPPLY_DESTINATION"
    assert "RAW_NEAREST_SUPPLY_DEMAND_OVERLAP_DIAGNOSTIC_ONLY" in state["conflicts"]

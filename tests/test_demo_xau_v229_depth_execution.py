from __future__ import annotations

from fx_scanner.demo_execution_fresh_ready_handoff import (
    _XAU_DEMO_EXECUTION_STRATEGIES,
)
from fx_scanner.demo_xau_v229_depth_execution import (
    STRATEGY_ID,
    _fresh_first_touch_calibration_arm_allowed,
    _fresh_first_touch_calibration_context,
    build_execution_plan,
)
from fx_scanner.demo_xau_v226_rizan_depth_map import build_depth_map


def _v226(*, fresh: bool = True, first_touch: bool = False, reused: bool = False) -> dict:
    return {
        "focus_direction": "LONG",
        "depth_entry_candidate": {
            "candidate_type": "DEPTH_ENTRY_CANDIDATE",
            "direction": "LONG",
            "entry_low": 100.0,
            "entry_high": 102.0,
            "entry_reference": 101.0,
            "source_layer": "M15_NESTED_LOCATOR",
            "display_status": (
                "PREPARE_ONLY_FRESH_FIRST_TOUCH"
                if fresh
                else "CONFIRMATION_ONLY_FIRST_TOUCH_IN_PROGRESS"
                if first_touch
                else "CONFIRMATION_ONLY_RETESTED_HTF"
                if reused
                else "CONTEXT_ONLY_OUT_OF_SAMPLE"
            ),
            "calibrated_fresh_first_touch": fresh,
            "confirmation_calibrated_first_touch": bool(fresh or first_touch),
            "first_touch_in_progress": first_touch,
            "htf_retested": reused,
            "retest_confirmation_eligible": reused,
            "pre_touch_execution_eligible": fresh,
            "confirmation_execution_eligible": bool(fresh or first_touch or reused),
            "zone_reuse": {
                "h4_touch_count": 3 if reused else 0,
                "h1_touch_count": 2 if reused else 0,
            },
        },
        "four_order_ladder": {
            "slots": [
                {"slot":1,"lot":0.01,"reference_price":101.8,"stage":"PRE_TOUCH_LIMIT_REFERENCE","activation":"FRESH_DEPTH_ENTRY_CANDIDATE"},
                {"slot":2,"lot":0.01,"reference_price":101.3,"stage":"PRE_TOUCH_LIMIT_REFERENCE","activation":"FRESH_DEPTH_ENTRY_CANDIDATE"},
                {"slot":3,"lot":0.01,"reference_price":100.8,"stage":"RESERVE_M5_RECLAIM_MSS_RETEST","activation":"M5_RECLAIM_AND_LOCAL_MSS_CONFIRMED"},
                {"slot":4,"lot":0.01,"reference_price":100.3,"stage":"RESERVE_M5_DISPLACEMENT_RETEST","activation":"M5_DISPLACEMENT_CONFIRMED_AND_RETEST_AVAILABLE"},
            ]
        },
        "long": {
            "h4": {
                "zone": {
                    "zone_id": "h4-demand-1",
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
        "zones": [
            {"zone_id":"m15-s","timeframe":"M15","direction":"SHORT","low":106.0,"high":107.0,"status":"ACTIVE","lifecycle":{"active":True}},
            {"zone_id":"h1-s","timeframe":"H1","direction":"SHORT","low":110.0,"high":112.0,"status":"ACTIVE","lifecycle":{"active":True}},
            {"zone_id":"h4-s","timeframe":"H4","direction":"SHORT","low":118.0,"high":122.0,"status":"ACTIVE","lifecycle":{"active":True}},
        ],
        "path_map": {
            "demand_to_supply": {
                "destination_stack": [
                    {"zone_id":"h1-s","timeframe":"H1","direction":"SHORT","low":110.0,"high":112.0,"status":"ACTIVE","lifecycle":{"active":True}},
                    {"zone_id":"h4-s","timeframe":"H4","direction":"SHORT","low":118.0,"high":122.0,"status":"ACTIVE","lifecycle":{"active":True}},
                ],
            }
        }
    }


def test_v229_builds_four_child_parent_before_touch() -> None:
    plan = build_execution_plan(
        v226_evaluation=_v226(),
        atlas_evaluation=_atlas(),
        live_price=103.0,
    )
    assert plan is not None
    assert plan["direction"] == "LONG"
    assert plan["entry_low"] == 100.0
    assert plan["entry_high"] == 102.0
    assert plan["sl"] < 98.0
    assert plan["source_layer"] == "M15_NESTED_LOCATOR"
    assert len(plan["children"]) == 4
    assert [child["lot"] for child in plan["children"]] == [0.01,0.01,0.01,0.01]
    assert plan["pretouch_slots"] == [1,2]
    assert plan["confirmation_slots"] == [3,4]
    assert plan["generic_market_handoff_allowed"] is False


def test_v229_pre_touch_parent_does_not_require_price_inside_candidate() -> None:
    plan = build_execution_plan(
        v226_evaluation=_v226(),
        atlas_evaluation=_atlas(),
        live_price=103.0,
    )
    assert plan is not None
    assert plan["entry_low"] == 100.0
    assert plan["entry_high"] == 102.0


def test_v229_accepts_retested_htf_as_confirmation_only_parent() -> None:
    plan = build_execution_plan(
        v226_evaluation=_v226(fresh=False, reused=True),
        atlas_evaluation=_atlas(),
        live_price=101.0,
    )
    assert plan is not None
    assert plan["execution_phase"] == "RETEST_CONFIRMATION"
    assert plan["pretouch_slots"] == []
    assert plan["confirmation_slots"] == [3, 4]
    assert plan["retest_confirmation_required"] is True
    assert [child["execution_enabled"] for child in plan["children"]] == [
        False,
        False,
        True,
        True,
    ]


def test_v229_accepts_reused_m15_as_confirmation_only_parent() -> None:
    payload = _v226(fresh=False, reused=True)
    payload["depth_entry_candidate"]["display_status"] = "CONFIRMATION_ONLY_RETESTED_M15"
    payload["depth_entry_candidate"]["m15_retested"] = True
    payload["depth_entry_candidate"]["m15_retest_confirmation_required"] = True
    payload["depth_entry_candidate"]["confirmation_execution_eligible"] = True
    plan = build_execution_plan(
        v226_evaluation=payload,
        atlas_evaluation=_atlas(),
        live_price=101.0,
    )
    assert plan is not None
    assert plan["execution_phase"] == "RETEST_CONFIRMATION"
    assert plan["pretouch_slots"] == []
    assert plan["confirmation_slots"] == [3, 4]
    assert plan["m15_retest_confirmation_required"] is True
    assert [child["execution_enabled"] for child in plan["children"]] == [
        False,
        False,
        True,
        True,
    ]


def test_v229_parent_is_excluded_from_generic_market_handoff() -> None:
    assert STRATEGY_ID == "XAU_RIZAN_DEPTH_EXECUTION_V1"
    assert STRATEGY_ID not in _XAU_DEMO_EXECUTION_STRATEGIES


def test_v229_first_touch_in_progress_builds_confirmation_only_parent() -> None:
    plan = build_execution_plan(
        v226_evaluation=_v226(fresh=False, first_touch=True),
        atlas_evaluation=_atlas(),
        live_price=101.0,
    )
    assert plan is not None
    assert plan["execution_phase"] == "FIRST_TOUCH_CONFIRMATION"
    assert plan["pretouch_slots"] == []
    assert plan["confirmation_slots"] == [3, 4]
    assert [child["execution_enabled"] for child in plan["children"]] == [
        False,
        False,
        True,
        True,
    ]

def test_v229_fails_closed_when_current_v182_path_opposes_v226_focus() -> None:
    atlas = _atlas()
    atlas["path_map"]["active_path"] = {
        "reaction_direction": "SHORT",
        "source_zone": {
            "zone_id": "current-short-source",
            "timeframe": "H1",
            "direction": "SHORT",
            "low": 106.0,
            "high": 108.0,
            "lifecycle": {"active": True},
        },
    }
    plan = build_execution_plan(
        v226_evaluation=_v226(),
        atlas_evaluation=atlas,
        live_price=103.0,
    )
    assert plan is None

def test_v229_fails_closed_when_local_v182_source_supersedes_far_same_side_locator() -> None:
    payload = _v226()
    payload["focus_direction"] = "SHORT"
    candidate = payload["depth_entry_candidate"]
    candidate.update(
        {
            "direction": "SHORT",
            "entry_low": 4357.64,
            "entry_high": 4359.52,
            "entry_reference": 4358.40,
        }
    )
    payload["short"] = {
        "h4": {
            "zone": {
                "zone_id": "old-far-h4-supply",
                "direction": "SHORT",
                "low": 4357.0,
                "high": 4365.0,
                "atr_points": 30.0,
            }
        }
    }

    atlas = _atlas()
    atlas["path_map"]["active_path"] = {
        "reaction_direction": "SHORT",
        "source_zone": {
            "zone_id": "current-local-h1-supply",
            "timeframe": "H1",
            "direction": "SHORT",
            "low": 4136.55,
            "high": 4160.48,
            "proximal": 4136.55,
            "lifecycle": {"active": True, "touch_count": 4},
        },
    }

    plan = build_execution_plan(
        v226_evaluation=payload,
        atlas_evaluation=atlas,
        live_price=4136.46,
    )
    assert plan is None




def test_v2572_v229_blocks_reentry_after_active_path_target_reached() -> None:
    atlas = _atlas()
    atlas["path_map"]["active_path"] = {
        "reaction_direction": "LONG",
        "source_zone": {
            "zone_id": "current-demand",
            "timeframe": "H1",
            "direction": "LONG",
            "low": 99.0,
            "high": 102.0,
            "lifecycle": {"active": True},
        },
        "reaction_target": {"price": 102.5},
        "terminal_target_zone": {
            "zone_id": "current-supply",
            "timeframe": "H1",
            "direction": "SHORT",
            "low": 102.5,
            "high": 107.0,
            "lifecycle": {"active": True},
        },
    }

    plan = build_execution_plan(
        v226_evaluation=_v226(),
        atlas_evaluation=atlas,
        live_price=103.0,
    )

    assert plan is None


def test_v261_v229_accepts_active_v182_h1_research_remap_without_old_h4_parent() -> None:
    source = {
        "zone_id": "local-h1-supply",
        "timeframe": "H1",
        "direction": "SHORT",
        "low": 100.0,
        "high": 110.0,
        "proximal": 100.0,
        "distal": 110.0,
        "atr_points": 5.0,
        "status": "IN_ZONE_PREPARE_ONLY",
        "lifecycle": {
            "active": True,
            "freshness": "PARTIALLY_MITIGATED",
            "touch_count": 3,
        },
    }
    payload = {
        "focus_direction": "SHORT",
        "depth_entry_candidate": {
            "candidate_type": "V182_ACTIVE_SOURCE_DEPTH_ENTRY_CANDIDATE",
            "direction": "SHORT",
            "entry_low": 102.0,
            "entry_high": 104.0,
            "entry_reference": 103.0,
            "source_layer": "V182_ACTIVE_H1_HISTORICAL_HOTSPOT",
            "source_timeframe": "H1",
            "source_zone": source,
            "display_status": "CONFIRMATION_ONLY_RETESTED_HTF",
            "calibrated_fresh_first_touch": False,
            "confirmation_calibrated_first_touch": False,
            "first_touch_in_progress": False,
            "htf_retested": True,
            "retest_confirmation_eligible": True,
            "pre_touch_execution_eligible": False,
            "confirmation_execution_eligible": True,
            "zone_reuse": {
                "h1_touch_count": 3,
                "historical_prior_scope": "FIRST_TOUCH_PRIOR_GEOMETRY_ONLY",
            },
        },
        "four_order_ladder": {
            "slots": [
                {"slot": 1, "lot": 0.01, "reference_price": 102.2, "stage": "PRE_TOUCH_LIMIT_REFERENCE", "activation": "FRESH_DEPTH_ENTRY_CANDIDATE"},
                {"slot": 2, "lot": 0.01, "reference_price": 102.8, "stage": "PRE_TOUCH_LIMIT_REFERENCE", "activation": "FRESH_DEPTH_ENTRY_CANDIDATE"},
                {"slot": 3, "lot": 0.01, "reference_price": 103.4, "stage": "RESERVE_M5_RECLAIM_MSS_RETEST", "activation": "M5_RECLAIM_AND_LOCAL_MSS_CONFIRMED"},
                {"slot": 4, "lot": 0.01, "reference_price": 103.8, "stage": "RESERVE_M5_DISPLACEMENT_RETEST", "activation": "M5_DISPLACEMENT_CONFIRMED_AND_RETEST_AVAILABLE"},
            ]
        },
        "short": {},
    }
    demand = {
        "zone_id": "terminal-h1-demand",
        "timeframe": "H1",
        "direction": "LONG",
        "low": 75.0,
        "high": 80.0,
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
                "reaction_target": {"price": 80.0},
                "terminal_target_zone": demand,
                "primary_opposing_zone": demand,
            },
            "supply_to_demand": {
                "reaction_target": {"price": 80.0},
                "terminal_target_zone": demand,
                "destination_stack": [demand],
            },
        },
    }

    plan = build_execution_plan(
        v226_evaluation=payload,
        atlas_evaluation=atlas,
        live_price=99.0,
    )

    assert plan is not None
    assert plan["direction"] == "SHORT"
    assert plan["source_layer"] == "V182_ACTIVE_H1_HISTORICAL_HOTSPOT"
    assert plan["source_timeframe"] == "H1"
    assert plan["structural_stop_zone_id"] == "local-h1-supply"
    assert plan["structural_stop_timeframe"] == "H1"
    assert plan["sl"] > 110.0
    assert plan["execution_phase"] == "RETEST_CONFIRMATION"
    assert plan["pretouch_slots"] == []
    assert [child["execution_enabled"] for child in plan["children"]] == [
        False,
        False,
        True,
        True,
    ]


def test_v261_v226_prefers_current_v182_h1_source_over_unrelated_h4_requirement() -> None:
    source = {
        "zone_id": "current-h1-supply",
        "timeframe": "H1",
        "direction": "SHORT",
        "low": 100.0,
        "high": 110.0,
        "proximal": 100.0,
        "distal": 110.0,
        "atr_points": 5.0,
        "status": "IN_ZONE_PREPARE_ONLY",
        "lifecycle": {
            "active": True,
            "freshness": "PARTIALLY_MITIGATED",
            "touch_count": 3,
        },
    }
    history = {
        "contract": "XAU_ZONE_REVERSAL_DEPTH_RESEARCH",
        "research_version": "XAU_ZONE_REVERSAL_DEPTH_V225_2",
        "years": list(range(2012, 2027)),
        "year_count": 15,
        "episode_count": 1000,
        "key_findings": [
            {
                "timeframe": "H1",
                "direction": "SHORT",
                "touches": 300,
                "hold_rate": 0.70,
                "hold_wilson_lower_95": 0.65,
                "depth_p25": 0.20,
                "depth_median": 0.35,
                "depth_p75": 0.60,
            }
        ],
        "eras": {
            era: {
                "summary": {
                    "H1": {
                        "SHORT": {
                            "touches": 100,
                            "hold_rate": 0.70,
                            "depth_median": 0.35,
                            "hazard_by_depth_band": [
                                {"band": "00-20%", "lower_depth": 0.0, "upper_depth": 0.2, "at_risk": 100, "reversals": 20, "hazard": 0.20},
                                {"band": "20-40%", "lower_depth": 0.2, "upper_depth": 0.4, "at_risk": 80, "reversals": 24, "hazard": 0.30},
                                {"band": "40-60%", "lower_depth": 0.4, "upper_depth": 0.6, "at_risk": 60, "reversals": 12, "hazard": 0.20},
                                {"band": "60-80%", "lower_depth": 0.6, "upper_depth": 0.8, "at_risk": 40, "reversals": 8, "hazard": 0.20},
                            ],
                        }
                    }
                }
            }
            for era in ("2012_2018", "2019_2024", "2025_2026")
        },
        "hierarchy": {},
    }
    atlas = {
        "last_closed_m15_price": 104.0,
        "as_of": "2026-09-29T07:00:00+00:00",
        "chart_bars_m15": [],
        "zones": [source],
        "path_map": {
            "active_path": {
                "reaction_direction": "SHORT",
                "source_zone": source,
            }
        },
    }

    result = build_depth_map(
        atlas_evaluation=atlas,
        history_details=history,
    )

    candidate = dict(result["depth_entry_candidate"])
    assert result["focus_direction"] == "SHORT"
    assert result["candidate_selection_mode"] == "V182_ACTIVE_SOURCE_HISTORICAL_REMAP"
    assert candidate["source_layer"] == "V182_ACTIVE_H1_HISTORICAL_HOTSPOT"
    assert candidate["source_zone"]["zone_id"] == "current-h1-supply"
    assert candidate["display_status"] == "CONFIRMATION_ONLY_RETESTED_HTF"
    assert candidate["pre_touch_execution_eligible"] is False
    assert candidate["confirmation_execution_eligible"] is True
    assert candidate["zone_reuse"]["historical_prior_scope"] == "FIRST_TOUCH_PRIOR_GEOMETRY_ONLY"
    assert 100.0 <= candidate["entry_low"] < candidate["entry_high"] <= 110.0


def test_v263_v229_arms_rr_eligible_retest_window_instead_of_dropping_parent() -> None:
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
    payload = {
        "focus_direction": "SHORT",
        "depth_entry_candidate": {
            "candidate_type": "V182_ACTIVE_SOURCE_DEPTH_ENTRY_CANDIDATE",
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
    near_demand = {
        "zone_id": "near-h1-demand",
        "timeframe": "H1",
        "direction": "LONG",
        "low": 95.0,
        "high": 98.0,
        "status": "ACTIVE",
        "lifecycle": {"active": True},
    }
    atlas = {
        "chart_bars_m15": [],
        "zones": [source, near_demand],
        "path_map": {
            "active_path": {
                "reaction_direction": "SHORT",
                "source_zone": source,
                "reaction_target": {"price": 98.0},
                "terminal_target_zone": near_demand,
                "primary_opposing_zone": near_demand,
            },
            "supply_to_demand": {
                "destination_stack": [near_demand],
            },
        },
    }
    diagnostics: dict = {}
    plan = build_execution_plan(
        v226_evaluation=payload,
        atlas_evaluation=atlas,
        live_price=110.0,
        diagnostics=diagnostics,
    )

    assert plan is not None
    assert plan["confirmation_window_only"] is True
    assert plan["broker_entry_authorized"] is False
    assert plan["terminal_rr_recheck_required"] is True
    assert plan["confirmation_entry_low"] >= source["low"]
    assert plan["confirmation_entry_high"] <= source["high"]
    assert plan["confirmation_entry_low"] < plan["confirmation_entry_high"]
    assert plan["confirmation_entry_reference"] >= plan["confirmation_entry_low"]
    assert plan["rr2"] >= 1.5
    assert plan["pretouch_slots"] == []
    assert [child["execution_enabled"] for child in plan["children"]] == [
        False,
        False,
        True,
        True,
    ]
    assert diagnostics["state"] == "PLAN_AVAILABLE"
    assert diagnostics["confirmation_window_only"] is True
    assert diagnostics["rr_recheck_at_child"] is True
    assert diagnostics["minimum_terminal_rr"] == 1.5
    assert diagnostics["best_terminal_rr"] < 1.5
    assert diagnostics["structural_stop_zone_id"] == "local-h1-supply"
    assert diagnostics["structural_stop_timeframe"] == "H1"
    assert diagnostics["slot_diagnostics"]


def test_v263_v229_still_rejects_when_no_source_slice_can_reach_1_50r() -> None:
    source = {
        "zone_id": "tight-h1-supply",
        "timeframe": "H1",
        "direction": "SHORT",
        "low": 118.0,
        "high": 120.0,
        "proximal": 118.0,
        "distal": 120.0,
        "atr_points": 10.0,
        "status": "IN_ZONE_PREPARE_ONLY",
        "lifecycle": {
            "active": True,
            "freshness": "PARTIALLY_MITIGATED",
            "touch_count": 3,
        },
    }
    payload = {
        "focus_direction": "SHORT",
        "depth_entry_candidate": {
            "direction": "SHORT",
            "entry_low": 118.2,
            "entry_high": 119.0,
            "entry_reference": 118.6,
            "source_layer": "V182_ACTIVE_H1_HISTORICAL_HOTSPOT",
            "source_timeframe": "H1",
            "source_zone": source,
            "display_status": "CONFIRMATION_ONLY_RETESTED_HTF",
            "htf_retested": True,
            "retest_confirmation_eligible": True,
            "pre_touch_execution_eligible": False,
            "confirmation_execution_eligible": True,
        },
        "four_order_ladder": {
            "slots": [
                {"slot": 1, "lot": 0.01, "reference_price": 118.25},
                {"slot": 2, "lot": 0.01, "reference_price": 118.45},
                {"slot": 3, "lot": 0.01, "reference_price": 118.65},
                {"slot": 4, "lot": 0.01, "reference_price": 118.85},
            ]
        },
        "short": {},
    }
    demand = {
        "zone_id": "too-close-demand",
        "timeframe": "H1",
        "direction": "LONG",
        "low": 116.8,
        "high": 117.8,
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
                "reaction_target": {"price": 117.8},
                "terminal_target_zone": demand,
                "primary_opposing_zone": demand,
            },
            "supply_to_demand": {"destination_stack": [demand]},
        },
    }
    diagnostics: dict = {}
    plan = build_execution_plan(
        v226_evaluation=payload,
        atlas_evaluation=atlas,
        live_price=119.2,
        diagnostics=diagnostics,
    )
    assert plan is None
    assert diagnostics["state"] == "PLAN_REJECTED"
    assert diagnostics["reason"] == "NO_RR_ELIGIBLE_CONFIRMATION_WINDOW"
    assert diagnostics["minimum_terminal_rr"] == 1.5


def test_v264_confirmation_window_is_persisted_armed_not_execution_ready() -> None:
    from pathlib import Path
    source = (
        Path(__file__).resolve().parents[1]
        / "src/fx_scanner/demo_xau_v229_depth_execution.py"
    ).read_text(encoding="utf-8")
    assert '"RIZAN_DEPTH_FIRST_TOUCH_CALIBRATION_ARM"' in source
    assert '"DEMO_CALIBRATION_L1_ONLY"' in source
    assert '"state": (' in source
    assert 'if state in {"ARMED", "EXECUTION_READY"}:' in source
    assert '"M5_ACTUAL_ENTRY_REQUIRED"' in source
    assert '"TERMINAL_RR_RECHECK_1_50R"' in source
    assert "confirmation_authority_only" in source


def test_v275_fresh_first_touch_calibration_arm_requires_nearby_fresh_candidate() -> None:
    plan = {
        "execution_phase": "PRE_TOUCH",
        "confirmation_window_only": False,
        "candidate": {
            "calibrated_fresh_first_touch": True,
            "pre_touch_execution_eligible": True,
            "source_zone": {"distance_atr": 0.35},
        },
    }
    pressure = {
        "state": "WAIT_SECOND_SAMPLE",
        "calibration_entry_allowed": True,
    }
    hazard = {
        "state": "DYNAMIC_DEPTH_HAZARD_AVAILABLE",
        "location_state": "AHEAD_OF_ZONE",
        "execution_ready": False,
    }
    assert _fresh_first_touch_calibration_arm_allowed(
        plan=plan,
        pressure_transition=pressure,
        depth_hazard=hazard,
        atlas_evaluation={},
    ) is True

    too_far = {
        **plan,
        "candidate": {
            **plan["candidate"],
            "source_zone": {"distance_atr": 0.51},
        },
    }
    assert _fresh_first_touch_calibration_arm_allowed(
        plan=too_far,
        pressure_transition=pressure,
        depth_hazard=hazard,
        atlas_evaluation={},
    ) is False

    not_fresh = {
        **plan,
        "candidate": {
            **plan["candidate"],
            "calibrated_fresh_first_touch": False,
        },
    }
    assert _fresh_first_touch_calibration_arm_allowed(
        plan=not_fresh,
        pressure_transition=pressure,
        depth_hazard=hazard,
        atlas_evaluation={},
    ) is False


def test_v275_producer_persists_calibration_arm_without_opening_strict_authority() -> None:
    from pathlib import Path
    source = (
        Path(__file__).resolve().parents[1]
        / "src/fx_scanner/demo_xau_v229_depth_execution.py"
    ).read_text(encoding="utf-8")
    assert "MAX_FRESH_CALIBRATION_APPROACH_ATR = 0.50" in source
    assert 'plan["calibration_only_armed"] = bool(fresh_calibration_arm)' in source
    assert '"FRESH_FIRST_TOUCH_CALIBRATION_ARMED"' in source
    assert '"calibration_authority_only"' in source
    assert '"DEMO_CALIBRATION_L1_ONLY"' in source
    assert "not plan.get(\"calibration_only_armed\")" in source


def test_v276_high_m30_overlap_plus_same_direction_composite_extends_arm_to_one_atr() -> None:
    plan = {
        "direction": "SHORT",
        "execution_phase": "PRE_TOUCH",
        "confirmation_window_only": False,
        "candidate": {
            "calibrated_fresh_first_touch": True,
            "pre_touch_execution_eligible": True,
            "direction": "SHORT",
            "source_zone": {
                "zone_id": "fresh-h1-supply",
                "distance_atr": 0.80,
            },
        },
    }
    atlas = {
        "m30_shadow_v272": {
            "available": True,
            "zones": [
                {
                    "direction": "SHORT",
                    "canonical_match_zone_id": "fresh-h1-supply",
                    "canonical_overlap_ratio": 1.0,
                }
            ],
        },
        "composite_pressure_v272": {
            "available": True,
            "state": "SELLER_LEAN",
            "short_calibration_allowed": True,
            "long_calibration_allowed": False,
        },
    }
    pressure = {"calibration_entry_allowed": True}
    hazard = {
        "state": "DYNAMIC_DEPTH_HAZARD_AVAILABLE",
        "location_state": "AHEAD_OF_ZONE",
    }

    context = _fresh_first_touch_calibration_context(
        plan=plan,
        atlas_evaluation=atlas,
    )
    assert context["m30_parent_overlap_ratio"] == 1.0
    assert context["high_m30_overlap"] is True
    assert context["composite_direction_allowed"] is True
    assert context["max_approach_distance_atr"] == 1.0
    assert context["policy"] == "HIGH_M30_OVERLAP_PLUS_COMPOSITE_SUPPORT_1_00_ATR"
    assert _fresh_first_touch_calibration_arm_allowed(
        plan=plan,
        pressure_transition=pressure,
        depth_hazard=hazard,
        atlas_evaluation=atlas,
    ) is True


def test_v276_opposing_composite_keeps_base_half_atr_even_with_full_m30_overlap() -> None:
    plan = {
        "direction": "SHORT",
        "execution_phase": "PRE_TOUCH",
        "confirmation_window_only": False,
        "candidate": {
            "calibrated_fresh_first_touch": True,
            "pre_touch_execution_eligible": True,
            "direction": "SHORT",
            "source_zone": {
                "zone_id": "fresh-h1-supply",
                "distance_atr": 0.658,
            },
        },
    }
    atlas = {
        "m30_shadow_v272": {
            "zones": [
                {
                    "direction": "SHORT",
                    "canonical_match_zone_id": "fresh-h1-supply",
                    "canonical_overlap_ratio": 1.0,
                }
            ],
        },
        "composite_pressure_v272": {
            "available": True,
            "state": "BUYER_LEAN",
            "short_calibration_allowed": False,
            "long_calibration_allowed": True,
        },
    }
    pressure = {"calibration_entry_allowed": True}
    hazard = {
        "state": "DYNAMIC_DEPTH_HAZARD_AVAILABLE",
        "location_state": "AHEAD_OF_ZONE",
    }

    context = _fresh_first_touch_calibration_context(
        plan=plan,
        atlas_evaluation=atlas,
    )
    assert context["m30_parent_overlap_ratio"] == 1.0
    assert context["composite_direction_allowed"] is False
    assert context["max_approach_distance_atr"] == 0.5
    assert context["policy"] == "BASE_FIRST_TOUCH_0_50_ATR"
    assert _fresh_first_touch_calibration_arm_allowed(
        plan=plan,
        pressure_transition=pressure,
        depth_hazard=hazard,
        atlas_evaluation=atlas,
    ) is False


def test_v276_live_ctrader_price_overrides_stale_snapshot_distance_for_arm() -> None:
    plan = {
        "direction": "SHORT",
        "execution_phase": "PRE_TOUCH",
        "confirmation_window_only": False,
        "candidate": {
            "calibrated_fresh_first_touch": True,
            "pre_touch_execution_eligible": True,
            "direction": "SHORT",
            "source_zone": {
                "zone_id": "fresh-h1-supply",
                "low": 4179.03,
                "high": 4197.99,
                "atr_points": 17.43257897762935,
                "distance_atr": 0.658,
            },
        },
    }
    pressure = {"calibration_entry_allowed": True}
    hazard = {
        "state": "DYNAMIC_DEPTH_HAZARD_AVAILABLE",
        "location_state": "AHEAD_OF_ZONE",
    }
    # Live bid has moved closer: (4179.03 - 4172.50) / 17.4326 ~= 0.375 ATR.
    context = _fresh_first_touch_calibration_context(
        plan=plan,
        atlas_evaluation={},
        live_price=4172.50,
    )
    assert context["snapshot_approach_distance_atr"] == 0.658
    assert 0.37 < context["live_approach_distance_atr"] < 0.38
    assert context["effective_approach_distance_atr"] == context["live_approach_distance_atr"]
    assert context["max_approach_distance_atr"] == 0.5
    assert _fresh_first_touch_calibration_arm_allowed(
        plan=plan,
        pressure_transition=pressure,
        depth_hazard=hazard,
        atlas_evaluation={},
        live_price=4172.50,
    ) is True


def test_v280_producer_blocks_missed_break_and_invalid_before_signal_persist() -> None:
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1]
        / "src/fx_scanner/demo_xau_v229_depth_execution.py"
    ).read_text()
    assert "evaluate_reversal_stage" in source
    assert 'reversal_stage.get("hard_execution_block")' in source
    assert '"V280_BLOCK:" + block_stage' in source
    assert '"reversal_stage": reversal_stage' in source
    block_pos = source.index('if bool(reversal_stage.get("hard_execution_block")):')
    write_pos = source.index("_write_signal(", block_pos)
    assert block_pos < write_pos


def test_v282_v280_hard_block_persists_specific_guard_and_one_shot_event() -> None:
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1]
        / "src/fx_scanner/demo_xau_v229_depth_execution.py"
    ).read_text()
    assert 'V280_STAGE_BLOCK_EVENT_TYPE = "DEMO_XAU_RIZAN_STAGE_BLOCK"' in source
    assert 'guard: str = "RIZAN_DEPTH_CANDIDATE_SUPERSEDED"' in source
    assert '"active_guards": [guard]' in source
    assert 'guard="V280_" + block_stage' in source
    assert "if changed and guard.startswith(\"V280_\"):" in source
    assert "store.record_order_event(" in source
    assert "telemetry write must never undo or fail that block" in source

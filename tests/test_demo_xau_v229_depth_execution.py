from __future__ import annotations

from fx_scanner.demo_execution_fresh_ready_handoff import (
    _XAU_DEMO_EXECUTION_STRATEGIES,
)
from fx_scanner.demo_xau_v229_depth_execution import (
    STRATEGY_ID,
    build_execution_plan,
)


def _v226(*, fresh: bool = True) -> dict:
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
                else "CONTEXT_ONLY_OUT_OF_SAMPLE"
            ),
            "calibrated_fresh_first_touch": fresh,
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
        "path_map": {
            "demand_to_supply": {
                "reaction_target": {"price": 106.0},
                "terminal_target_zone": {
                    "low": 108.0,
                    "high": 110.0,
                },
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


def test_v229_rejects_reused_or_out_of_sample_parent() -> None:
    plan = build_execution_plan(
        v226_evaluation=_v226(fresh=False),
        atlas_evaluation=_atlas(),
        live_price=101.0,
    )
    assert plan is None


def test_v229_parent_is_excluded_from_generic_market_handoff() -> None:
    assert STRATEGY_ID == "XAU_RIZAN_DEPTH_EXECUTION_V1"
    assert STRATEGY_ID not in _XAU_DEMO_EXECUTION_STRATEGIES

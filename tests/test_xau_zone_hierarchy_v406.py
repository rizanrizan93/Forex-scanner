from __future__ import annotations

from fx_scanner.xau_zone_hierarchy_v406 import (
    CONTRACT,
    evaluate_zone_hierarchy_v406,
)


def _snapshot(price: float = 4138.02, *, m15_close: float | None = None) -> dict:
    payload = {
        "price_now": price,
        "main_reversal_zone": {"low": 4100.0, "high": 4111.97, "atr": 20.0},
        "active_zones": [
            {
                "zone_id": "main-buy",
                "direction": "LONG",
                "low": 4100.0,
                "high": 4111.97,
                "timeframe": "H1",
                "condition": "ACTIVE",
                "lifecycle_state": "ACTIVE_SUPPORT",
                "score": 2.0,
                "lifecycle": {"touch_count": 1},
            },
            {
                "zone_id": "decision-pink",
                "direction": "SHORT",
                "low": 4118.0,
                "high": 4140.04,
                "timeframe": "M15",
                "condition": "ACTIVE",
                "lifecycle_state": "ACTIVE_RESISTANCE",
                "score": 1.3,
                "lifecycle": {"touch_count": 1},
            },
            {
                "zone_id": "sell-1",
                "direction": "SHORT",
                "low": 4166.0,
                "high": 4183.0,
                "timeframe": "H1",
                "condition": "ACTIVE",
                "lifecycle_state": "ACTIVE_RESISTANCE",
                "score": 1.9,
                "lifecycle": {"touch_count": 1},
            },
            {
                "zone_id": "sell-2",
                "direction": "SHORT",
                "low": 4216.0,
                "high": 4240.0,
                "timeframe": "H4",
                "condition": "ACTIVE",
                "lifecycle_state": "ACTIVE_RESISTANCE",
                "score": 1.8,
                "lifecycle": {"touch_count": 1},
            },
        ],
        "support_resistance_map": {"levels": []},
        "liquidity_candidates": [
            {"side": "SELL_SIDE", "price": 4106.0},
            {"side": "BUY_SIDE", "price": 4175.0},
            {"side": "BUY_SIDE", "price": 4228.0},
        ],
    }
    if m15_close is not None:
        payload["latest_m15_close"] = m15_close
    return payload


def test_v406_reconstructs_shared_h1_zone_hierarchy():
    out = evaluate_zone_hierarchy_v406(_snapshot())

    assert out["contract"] == CONTRACT
    assert out["state"] == "HIERARCHY_MAPPED"
    assert out["phase"] == "TESTING_DECISION_ZONE"

    assert out["main_buy"]["zone_id"] == "main-buy"
    assert out["main_buy"]["low"] == 4100.0
    assert out["main_buy"]["high"] == 4111.97

    assert out["decision_zone"]["zone_id"] == "decision-pink"
    assert out["decision_zone"]["low"] == 4118.0
    assert out["decision_zone"]["high"] == 4140.04
    assert out["decision_zone"]["zone_role"] == "TRANSITION_DECISION"

    assert out["main_sell"]["zone_id"] == "sell-1"
    assert out["main_sell"]["low"] == 4166.0
    assert out["main_sell"]["high"] == 4183.0
    assert out["next_sell"]["zone_id"] == "sell-2"

    assert out["transition_gate"]["bullish_acceptance_above"] == 4140.04
    assert out["structural_gate"]["bullish_major_reversal_above"] == 4183.0
    assert out["path"]["primary_if_rejected"] == "RETURN_TO_MAIN_BUY"
    assert out["path"]["primary_target"] == 4111.97
    assert out["path"]["alternative_target"] == 4166.0


def test_v406_decision_break_changes_internal_leg_not_major_structure():
    out = evaluate_zone_hierarchy_v406(_snapshot(4142.0, m15_close=4141.0))

    assert out["phase"] == "INTERNAL_BULLISH_TRANSITION"
    assert out["transition_gate"]["bullish_acceptance_above"] == 4140.04
    assert out["structural_gate"]["bullish_major_reversal_above"] == 4183.0
    assert out["transition_gate"]["bullish_acceptance_above"] < out["structural_gate"]["bullish_major_reversal_above"]


def test_v406_m15_rejection_keeps_path_back_to_main_buy():
    out = evaluate_zone_hierarchy_v406(_snapshot(4117.0, m15_close=4117.0))

    assert out["phase"] == "BEARISH_REJECTION_FROM_DECISION"
    assert out["path"]["primary_if_rejected"] == "RETURN_TO_MAIN_BUY"
    assert out["path"]["primary_target"] == 4111.97


def test_v406_preserves_research_only_execution_boundary():
    out = evaluate_zone_hierarchy_v406(_snapshot())

    assert out["proprietary_formula_claimed"] is False
    assert out["execution_authority"] is False
    assert out["demo_auto_execution"] is False
    assert out["live_execution_enabled"] is False
    assert out["validation_status"] == "RECONSTRUCTION_REQUIRES_REPLAY_AND_FORWARD_CALIBRATION"


def test_v406_fails_closed_without_price():
    out = evaluate_zone_hierarchy_v406({"active_zones": []})
    assert out["state"] == "UNAVAILABLE"
    assert out["phase"] == "UNAVAILABLE"
    assert out["execution_authority"] is False

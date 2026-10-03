from __future__ import annotations

from datetime import UTC, datetime

from fx_scanner.demo_xau_v375_reaction_executor import _candidate, _reaction_candidate

NOW = datetime(2026, 10, 3, 2, 30, 30, tzinfo=UTC)


def _reaction_heartbeat(*, price=4111.5, news_state="CLEAR", effective_news="WAIT_CONFIRMATION") -> dict:
    evaluation = {
        "contract": "XAU_RIZAN_SD_LIQUIDITY_V342_12_INTRADAY_REROUTE_V369",
        "execution_authority": True,
        "execution_scope": "DEMO_ONLY",
        "live_execution_enabled": False,
        "price_now": price,
        "expected_reversal_direction": "LONG",
        "main_reversal_zone": {
            "zone_id": "main-h4-demand",
            "timeframe": "H4",
            "direction": "LONG",
            "low": 4065.0,
            "high": 4086.0,
            "atr": 20.0,
        },
        "structural_destination": {
            "zone_id": "dest-h4-supply",
            "price": 4150.0,
        },
        "nearest_roadblock": {},
        "structural_room": {
            "blocked": False,
            "state": "STRUCTURAL_ROOM_OK",
        },
        "roadblock_room": {
            "blocked": False,
            "state": "NO_ROADBLOCK_BEFORE_DESTINATION",
        },
        "micro_confirmation": {
            "stage": "FAR",
            "confirmed": False,
            "early_confirmed": False,
        },
        "entry_guide": {
            "state": "WAIT_CONFIRMATION",
            "direction": "LONG",
        },
        "news_zone": {
            "risk_state": news_state,
            "execution_risk_state": news_state,
            "effective_entry_state": effective_news,
        },
        "support_resistance_map": {
            "nearest_support": {
                "price": 4111.0,
                "band_low": 4109.5,
                "band_high": 4112.5,
                "kind": "SUPPORT",
                "current_role": "SUPPORT",
                "lifecycle_state": "DOWNSIDE_SWEEP_LIKE_REJECTION",
                "strength": 2.0,
                "confirmed_flip": False,
                "reclaim_required": False,
                "sources": ["H2_SWING_LOW", "PRIOR_DAY_LOW"],
            },
            "levels": [
                {
                    "price": 4111.0,
                    "band_low": 4109.5,
                    "band_high": 4112.5,
                    "kind": "SUPPORT",
                    "current_role": "SUPPORT",
                    "lifecycle_state": "DOWNSIDE_SWEEP_LIKE_REJECTION",
                    "strength": 2.0,
                    "confirmed_flip": False,
                    "reclaim_required": False,
                    "sources": ["H2_SWING_LOW", "PRIOR_DAY_LOW"],
                }
            ],
        },
        "liquidity_candidates": [
            {
                "side": "SELL_SIDE",
                "price": 4111.2,
                "strength": 2,
                "sources": ["SWING_LOW_CLUSTER"],
            }
        ],
    }
    return {
        "healthy": True,
        "observed_at": datetime(2026, 10, 3, 2, 30, 0, tzinfo=UTC).isoformat(),
        "details": {"evaluation": evaluation},
    }


def test_v375_reaction_can_enter_before_main_zone_and_before_full_mss():
    heartbeat = _reaction_heartbeat()
    candidate, reason = _candidate(
        heartbeat=heartbeat,
        bid=4111.3,
        ask=4111.4,
        now=NOW,
    )

    assert reason == "ELIGIBLE_REACTION_DEMO"
    assert candidate is not None
    assert candidate["direction"] == "LONG"
    assert candidate["entry_mode"] == "REACTION_EARLY_DEMO_PROBE"
    assert candidate["confirmation_tier"] == "REACTION_EARLY"
    assert candidate["execution_lane"] == "V374_REACTION_INTERCEPTOR"
    assert candidate["entry_low"] <= candidate["entry"] <= candidate["entry_high"]
    assert candidate["stop_loss"] < candidate["entry"] < candidate["take_profit"]
    assert candidate["rr"] >= 1.50
    assert candidate["parent_zone_id"] == "main-h4-demand"
    assert candidate["reaction_lifecycle_state"] == "DOWNSIDE_SWEEP_LIKE_REJECTION"


def test_v375_reaction_never_chases_quote_outside_early_band():
    heartbeat = _reaction_heartbeat()
    candidate, reason = _reaction_candidate(
        heartbeat=heartbeat,
        bid=4117.0,
        ask=4117.1,
        now=NOW,
    )

    assert candidate is None
    assert reason == "REACTION_QUOTE_OUTSIDE_EARLY_BAND_NO_CHASE"


def test_v375_reaction_blocks_move_already_missed():
    heartbeat = _reaction_heartbeat(price=4127.0)
    candidate, reason = _reaction_candidate(
        heartbeat=heartbeat,
        bid=4126.9,
        ask=4127.0,
        now=NOW,
    )

    assert candidate is None
    assert reason == "REACTION_MOVE_MISSED_NO_CHASE"


def test_v375_reaction_respects_verified_event_blackout():
    heartbeat = _reaction_heartbeat(
        news_state="EVENT_WINDOW",
        effective_news="WAIT_FOR_NEWS",
    )
    candidate, reason = _reaction_candidate(
        heartbeat=heartbeat,
        bid=4111.3,
        ask=4111.4,
        now=NOW,
    )

    assert candidate is None
    assert reason == "NEWS_RISK_BLOCK:EVENT_WINDOW"


def test_v375_reaction_fails_closed_when_structural_room_is_blocked():
    heartbeat = _reaction_heartbeat()
    heartbeat["details"]["evaluation"]["structural_room"] = {
        "blocked": True,
        "state": "COMPRESSED_HTF_CORRIDOR",
    }
    candidate, reason = _reaction_candidate(
        heartbeat=heartbeat,
        bid=4111.3,
        ask=4111.4,
        now=NOW,
    )

    assert candidate is None
    assert reason == "STRUCTURAL_ROOM_BLOCK:COMPRESSED_HTF_CORRIDOR"


def test_v375_existing_confirmed_v342_lane_remains_preferred():
    heartbeat = _reaction_heartbeat()
    evaluation = heartbeat["details"]["evaluation"]
    evaluation["expected_reversal_direction"] = "SHORT"
    evaluation["main_reversal_zone"] = {"zone_id": "parent-h4"}
    evaluation["structural_destination"] = {"zone_id": "dest-h4", "price": 90.0}
    evaluation["support_resistance_map"] = {}
    evaluation["liquidity_candidates"] = []
    evaluation["micro_confirmation"] = {
        "confirmed": True,
        "reclaim_at": "2026-10-03T02:30:00+00:00",
    }
    evaluation["entry_guide"] = {
        "state": "CONFIRMED_GUIDANCE",
        "direction": "SHORT",
        "entry_low": 99.0,
        "entry_high": 101.0,
        "entry_reference": 100.0,
        "invalidation": 105.0,
    }
    evaluation["news_zone"] = {
        "risk_state": "CLEAR",
        "effective_entry_state": "CONFIRMED_GUIDANCE",
    }

    candidate, reason = _candidate(
        heartbeat=heartbeat,
        bid=100.0,
        ask=100.1,
        now=NOW,
    )

    assert reason == "ELIGIBLE"
    assert candidate is not None
    assert candidate["execution_lane"] == "V342_MICRO_CONFIRMATION"
    assert candidate["entry_mode"] == "RETEST_ENTRY"

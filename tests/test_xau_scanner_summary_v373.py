from __future__ import annotations

from fx_scanner.xau_scanner_summary_v373 import build_scanner_summary


def _base_sd() -> dict:
    return {
        "price_now": 4140.76,
        "expected_reversal_direction": "LONG",
        "main_reversal_zone": {
            "timeframe": "H4",
            "direction": "LONG",
            "low": 4065.54,
            "high": 4085.82,
            "distance_atr": 1.85,
            "condition": "FRESH",
            "main_reversal_score": 91.48,
            "atr": 20.0,
        },
        "market_structure": {
            "H4": {"state": "BEARISH_RANGE"},
            "H1": {"state": "BEARISH_RANGE"},
        },
        "micro_confirmation": {
            "stage": "FAR",
            "confirmed": False,
            "early_confirmed": False,
        },
        "entry_guide": {
            "state": "WAIT_CONFIRMATION",
            "prepared_entry_low": 4076.81,
            "prepared_entry_high": 4081.76,
            "confirmation_entry_reference": None,
            "entry_low": None,
            "entry_high": None,
            "invalidation": None,
            "targets": [],
        },
        "news_zone": {
            "risk_state": "CLEAR",
            "effective_entry_state": "WAIT_CONFIRMATION",
        },
        "support_resistance_map": {
            "nearest_support": {"price": 4137.98},
            "nearest_resistance": {"price": 4144.98},
            "flip_watch": {"price": 4144.98},
        },
        "liquidity_candidates": [
            {"side": "SELL_SIDE", "price": 4139.76, "distance_atr": 0.04},
            {"side": "SELL_SIDE", "price": 4111.10, "distance_atr": 1.34},
        ],
        "destination_ladder": {
            "primary": {
                "timeframe": "H4",
                "direction": "SHORT",
                "low": 4279.67,
                "high": 4297.27,
            }
        },
    }


def _macro() -> dict:
    return {
        "broader_macro_bias": "BULLISH_XAU",
        "confidence": "MEDIUM",
        "components": {
            "US10Y": {
                "current": 5.24,
                "previous": 5.29,
                "delta": -5.0,
                "freshness": "FRESH",
                "provider": "FEDERAL_RESERVE_FRED",
            }
        },
        "intraday_yield_context": {
            "state": "NO_POST_RELEASE_EVENT_ANCHOR",
            "available": False,
            "gold_implication": "UNAVAILABLE",
        },
    }


def test_v374_waits_on_path_not_mandatory_main_touch_when_no_reaction_is_promoted():
    summary = build_scanner_summary(
        sd_eval=_base_sd(),
        friend_eval={},
        event_risk={"state": "CLEAR"},
        macro_eval=_macro(),
    )

    assert summary["decision"]["state"] == "WAIT_FOR_PATH_LONG"
    assert summary["decision"]["label"] == "WAIT FOR LONG PATH"
    assert summary["main_zone_label"] == "H4 DEMAND 4,065.54–4,085.82"
    assert summary["main_zone_role"] == "PRIMARY_HTF_FALLBACK"
    assert summary["macro"]["yield"]["daily"]["gold_bias"] == "BULLISH_XAU"
    assert summary["macro"]["yield"]["intraday"]["gold_bias"] == "UNAVAILABLE"
    assert summary["execution_authority"] is False


def test_v374_promotes_reaction_liquidity_zone_before_main_zone_is_touched():
    sd = _base_sd()
    sd["price_now"] = 4112.0
    sd["support_resistance_map"]["nearest_support"] = {
        "price": 4112.0,
        "band_low": 4110.0,
        "band_high": 4114.0,
        "current_role": "SUPPORT",
        "lifecycle_state": "DOWNSIDE_SWEEP_LIKE_REJECTION",
        "strength": 2.0,
        "sources": ["H2_SWING_LOW", "ROUND_10"],
    }
    sd["support_resistance_map"]["levels"] = [
        sd["support_resistance_map"]["nearest_support"]
    ]
    sd["liquidity_candidates"] = [
        {"side": "SELL_SIDE", "price": 4111.10, "distance_atr": 0.04},
    ]

    summary = build_scanner_summary(
        sd_eval=sd,
        friend_eval={},
        event_risk={"state": "CLEAR"},
        macro_eval=_macro(),
    )

    assert summary["decision"]["state"] == "EARLY_REACTION_LONG"
    assert summary["decision"]["label"] == "EARLY LONG • REACTION"
    assert summary["decision"]["entry_gate"] == "REACTION_EARLY_CANDIDATE"
    assert summary["reaction_interceptor"]["promoted"] is True
    assert summary["active_reversal_candidate"]["low"] == 4110.0
    assert summary["main_zone_role"] == "DEEP_FALLBACK_NOT_MANDATORY_TOUCH"
    assert summary["entry"]["reaction_early_low"] == 4110.0
    assert summary["entry"]["reaction_early_high"] == 4114.0


def test_v374_does_not_chase_after_promoted_reaction_has_already_moved_far():
    sd = _base_sd()
    sd["price_now"] = 4130.0
    support = {
        "price": 4112.0,
        "band_low": 4110.0,
        "band_high": 4114.0,
        "current_role": "SUPPORT",
        "lifecycle_state": "DOWNSIDE_SWEEP_LIKE_REJECTION",
        "strength": 2.0,
    }
    sd["support_resistance_map"]["nearest_support"] = support
    sd["support_resistance_map"]["levels"] = [support]
    sd["liquidity_candidates"] = [
        {"side": "SELL_SIDE", "price": 4111.10, "distance_atr": 0.04},
    ]

    summary = build_scanner_summary(
        sd_eval=sd,
        friend_eval={},
        event_risk={"state": "CLEAR"},
        macro_eval=_macro(),
    )

    assert summary["decision"]["state"] == "NO_CHASE"
    assert summary["decision"]["label"] == "MOVE MISSED • NO CHASE"
    assert summary["decision"]["entry_gate"] == "NO_CHASE"
    assert summary["reaction_interceptor"]["no_chase"] is True


def test_v373_ready_long_requires_micro_confirmation_and_geometry():
    sd = _base_sd()
    sd["price_now"] = 4079.0
    sd["main_reversal_zone"]["distance_atr"] = 0.1
    sd["micro_confirmation"] = {
        "stage": "CONFIRMED",
        "confirmed": True,
        "early_confirmed": True,
    }
    sd["entry_guide"].update(
        {
            "state": "CONFIRMED_ENTRY",
            "entry_low": 4078.0,
            "entry_high": 4080.0,
            "invalidation": 4063.5,
            "confirmation_entry_reference": 4079.0,
        }
    )
    sd["news_zone"]["effective_entry_state"] = "CONFIRMED_ENTRY"

    summary = build_scanner_summary(
        sd_eval=sd,
        friend_eval={},
        event_risk={"state": "CLEAR"},
        macro_eval=_macro(),
    )

    assert summary["decision"]["state"] == "READY_LONG"
    assert summary["decision"]["label"] == "LONG READY"
    assert summary["zone_location"] == "IN_ZONE"


def test_v373_news_window_overrides_structural_readiness_to_wait():
    sd = _base_sd()
    sd["price_now"] = 4079.0
    sd["micro_confirmation"] = {"stage": "CONFIRMED", "confirmed": True}
    sd["entry_guide"].update({"entry_low": 4078.0, "invalidation": 4063.5})
    sd["news_zone"] = {
        "risk_state": "EVENT_WINDOW",
        "effective_entry_state": "WAIT_EVENT_VOLATILITY",
    }

    summary = build_scanner_summary(
        sd_eval=sd,
        friend_eval={},
        event_risk={"state": "EVENT_WINDOW"},
        macro_eval=_macro(),
    )

    assert summary["decision"]["state"] == "WAIT_NEWS"
    assert summary["decision"]["label"] == "WAIT NEWS"


def test_v373_falls_back_to_latest_actual_event_when_latest_field_missing():
    event = {
        "state": "CLEAR",
        "latest_released_event": None,
        "upcoming_events": [
            {
                "title": "Employment Situation",
                "scheduled_at": "2026-10-02T12:30:00+00:00",
                "actual": 29000,
                "forecast": None,
                "gold_bias": "NEUTRAL_UNKNOWN",
            },
            {
                "title": "Older Event",
                "scheduled_at": "2026-09-30T12:30:00+00:00",
                "actual": 1.0,
                "forecast": 1.1,
            },
        ],
        "focal_event": {
            "title": "U.S. International Trade in Goods and Services",
            "scheduled_at": "2026-10-06T12:30:00+00:00",
        },
    }

    summary = build_scanner_summary(
        sd_eval=_base_sd(),
        friend_eval={},
        event_risk=event,
        macro_eval=_macro(),
    )

    assert summary["event"]["latest_released"]["title"] == "Employment Situation"
    assert summary["event"]["next_event"]["title"] == "U.S. International Trade in Goods and Services"

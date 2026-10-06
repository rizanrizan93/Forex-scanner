from __future__ import annotations

from fx_scanner.xau_whalezone_reconstruction_v405 import (
    CONTRACT,
    evaluate_whalezone_reconstruction_v405,
)


def _snapshot(price: float = 4129.79) -> dict:
    return {
        "price_now": price,
        "main_reversal_zone": {"low": 4118.0, "high": 4134.0, "atr": 20.0},
        "active_zones": [
            {
                "zone_id": "buy-main",
                "direction": "LONG",
                "low": 4118.0,
                "high": 4134.0,
                "timeframe": "H1",
                "condition": "ACTIVE",
                "lifecycle_state": "ACTIVE_SUPPORT",
                "score": 1.8,
                "lifecycle": {"touch_count": 1},
            },
            {
                "zone_id": "sell-local",
                "direction": "SHORT",
                "low": 4168.66,
                "high": 4196.70,
                "timeframe": "H1",
                "condition": "ACTIVE",
                "lifecycle_state": "ACTIVE_RESISTANCE",
                "score": 1.7,
                "lifecycle": {"touch_count": 1},
            },
            {
                "zone_id": "sell-main",
                "direction": "SHORT",
                "low": 4218.0,
                "high": 4235.0,
                "timeframe": "H4",
                "condition": "ACTIVE",
                "lifecycle_state": "ACTIVE_RESISTANCE",
                "score": 1.9,
                "lifecycle": {"touch_count": 1},
            },
            {
                "zone_id": "sell-next",
                "direction": "SHORT",
                "low": 4268.0,
                "high": 4290.0,
                "timeframe": "H4",
                "condition": "ACTIVE",
                "lifecycle_state": "ACTIVE_RESISTANCE",
                "score": 1.6,
                "lifecycle": {"touch_count": 1},
            },
            {
                "zone_id": "retired-noise",
                "direction": "SHORT",
                "low": 4140.0,
                "high": 4145.0,
                "timeframe": "M15",
                "condition": "BROKEN",
                "score": 5.0,
            },
        ],
        "support_resistance_map": {"levels": []},
        "liquidity_candidates": [
            {"side": "SELL_SIDE", "price": 4124.0},
            {"side": "BUY_SIDE", "price": 4188.0},
            {"side": "BUY_SIDE", "price": 4222.0},
        ],
    }


def test_v405_builds_outward_tier_map_from_nearest_reaction_zones():
    out = evaluate_whalezone_reconstruction_v405(_snapshot())

    assert out["contract"] == CONTRACT
    assert out["state"] == "FOCUS_BUY_1"
    assert out["direction"] == "LONG"
    assert out["buy_zones"][0]["label"] == "BUY_1"
    assert out["buy_zones"][0]["zone_id"] == "buy-main"

    sells = out["sell_zones"]
    assert [row["label"] for row in sells] == ["SELL_1", "SELL_2", "SELL_3"]
    assert [row["zone_id"] for row in sells] == [
        "sell-local",
        "sell-main",
        "sell-next",
    ]
    assert [row["low"] for row in sells] == sorted(row["low"] for row in sells)


def test_v405_excludes_broken_zones_and_keeps_liquidity_metadata():
    out = evaluate_whalezone_reconstruction_v405(_snapshot())
    zone_ids = {
        row.get("zone_id")
        for row in [*out["buy_zones"], *out["sell_zones"]]
    }
    assert "retired-noise" not in zone_ids
    assert out["buy_zones"][0]["liquidity"][0]["side"] == "SELL_SIDE"
    assert out["sell_zones"][0]["liquidity"][0]["side"] == "BUY_SIDE"


def test_v405_is_reconstruction_not_execution_or_proprietary_claim():
    out = evaluate_whalezone_reconstruction_v405(_snapshot())

    assert out["proprietary_formula_claimed"] is False
    assert out["execution_authority"] is False
    assert out["demo_auto_execution"] is False
    assert out["live_execution_enabled"] is False
    assert out["confirmation_model"]["validation_timeframe"] == "M15"
    assert out["confirmation_model"]["refinement_timeframe"] == "M5"
    assert out["confirmation_model"]["wick_sweep_alone_invalidates"] is False


def test_v405_fails_closed_without_price():
    out = evaluate_whalezone_reconstruction_v405({"active_zones": []})
    assert out["state"] == "UNAVAILABLE"
    assert out["direction"] == "WAIT"
    assert out["execution_authority"] is False

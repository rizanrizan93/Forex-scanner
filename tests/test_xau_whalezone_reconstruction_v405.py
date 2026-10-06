from __future__ import annotations

from fx_scanner.xau_whalezone_reconstruction_v405 import (
    evaluate_whalezone_reconstruction_v405,
)


def _snapshot() -> dict:
    return {
        "price_now": 4129.79,
        "decision_zone": {"low": 4120.0, "high": 4134.0, "atr": 20.0},
        "active_zones": [
            {
                "zone_id": "buy-h4",
                "direction": "LONG",
                "timeframe": "H4",
                "low": 4120.0,
                "high": 4134.0,
                "condition": "ACTIVE",
                "score": 2.5,
            },
            {
                "zone_id": "sell-h1",
                "direction": "SHORT",
                "timeframe": "H1",
                "low": 4170.0,
                "high": 4197.0,
                "condition": "ACTIVE",
                "score": 2.2,
            },
            {
                "zone_id": "sell-h4-2",
                "direction": "SHORT",
                "timeframe": "H4",
                "low": 4218.0,
                "high": 4235.0,
                "condition": "ACTIVE",
                "score": 2.8,
            },
            {
                "zone_id": "sell-h4-3",
                "direction": "SHORT",
                "timeframe": "H4",
                "low": 4268.0,
                "high": 4290.0,
                "condition": "ACTIVE",
                "score": 2.4,
            },
            {
                "zone_id": "broken-sell",
                "direction": "SHORT",
                "timeframe": "H1",
                "low": 4148.0,
                "high": 4153.0,
                "condition": "BROKEN",
                "score": 3.0,
            },
        ],
        "liquidity_candidates": [
            {"side": "SELL_SIDE", "price": 4125.0, "kind": "LOCAL_LOW"},
            {"side": "BUY_SIDE", "price": 4188.0, "kind": "LOCAL_HIGH"},
        ],
        "support_resistance_map": {"levels": []},
    }


def test_reconstructs_nearest_buy_and_three_ascending_sell_tiers() -> None:
    result = evaluate_whalezone_reconstruction_v405(_snapshot())

    assert result["state"] == "IN_BUY_REACTION_ZONE"
    assert result["active_side"] == "BUY"
    assert result["primary_buy"]["low"] == 4120.0
    assert result["primary_buy"]["high"] == 4134.0

    sells = result["sell_zones"]
    assert [row["tier"] for row in sells] == [1, 2, 3]
    assert [row["zone_id"] for row in sells] == [
        "sell-h1",
        "sell-h4-2",
        "sell-h4-3",
    ]
    assert [row["label"] for row in sells] == [
        "WHALEZONE SELL 1",
        "WHALEZONE SELL 2",
        "WHALEZONE SELL 3",
    ]


def test_broken_or_invalid_zones_are_excluded() -> None:
    result = evaluate_whalezone_reconstruction_v405(_snapshot())
    ids = {
        row.get("zone_id")
        for row in result["buy_zones"] + result["sell_zones"]
    }
    assert "broken-sell" not in ids


def test_m15_acceptance_is_unknown_when_snapshot_has_no_close_evidence() -> None:
    result = evaluate_whalezone_reconstruction_v405(_snapshot())
    assert result["sell_zones"][0]["m15_acceptance"] == {
        "status": "UNKNOWN_NO_M15_CLOSE_INPUT",
        "confirmed": None,
        "close_count": None,
        "source_available": False,
    }


def test_m15_acceptance_is_only_claimed_when_input_supplies_it() -> None:
    snapshot = _snapshot()
    snapshot["active_zones"][1]["m15_acceptance_closes"] = 2
    result = evaluate_whalezone_reconstruction_v405(snapshot)
    assert result["sell_zones"][0]["m15_acceptance"]["status"] == "CONFIRMED"
    assert result["sell_zones"][0]["m15_acceptance"]["close_count"] == 2


def test_no_price_returns_fail_closed_unavailable() -> None:
    result = evaluate_whalezone_reconstruction_v405({"active_zones": []})
    assert result["state"] == "UNAVAILABLE"
    assert result["execution_authority"] is False
    assert result["demo_auto_execution"] is False
    assert result["live_execution_enabled"] is False

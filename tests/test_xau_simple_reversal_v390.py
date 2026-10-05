from fx_scanner.xau_simple_reversal_engine_v390 import evaluate_simple_reversal


def _snapshot(price: float) -> dict:
    return {
        "price_now": price,
        "main_reversal_zone": {
            "zone_id": "H4_SUPPLY_FAR",
            "direction": "SHORT",
            "timeframe": "H4",
            "low": 4278.0,
            "high": 4284.0,
            "atr": 20.0,
        },
        "active_zones": [
            {
                "zone_id": "H4_SUPPLY_FAR",
                "direction": "SHORT",
                "timeframe": "H4",
                "low": 4278.0,
                "high": 4284.0,
                "atr": 20.0,
                "condition": "ACTIVE",
                "score": 7.0,
            }
        ],
        "support_resistance_map": {
            "nearest_support": {
                "price": 4126.0,
                "band_low": 4124.0,
                "band_high": 4128.0,
                "current_role": "SUPPORT",
                "lifecycle_state": "ACTIVE_SUPPORT",
                "strength": 1.7,
            },
            "nearest_resistance": {
                "price": 4160.0,
                "band_low": 4158.0,
                "band_high": 4162.0,
                "current_role": "RESISTANCE",
                "lifecycle_state": "ACTIVE_RESISTANCE",
                "strength": 1.8,
            },
            "levels": [],
        },
        "liquidity_candidates": [
            {"side": "SELL_SIDE", "price": 4125.0},
            {"side": "BUY_SIDE", "price": 4161.0},
        ],
    }


def test_v390_uses_local_range_not_distant_h4_supply() -> None:
    result = evaluate_simple_reversal(_snapshot(4142.0))
    assert result["state"] == "RANGE_WAIT"
    assert result["direction"] == "WAIT"
    assert result["long_zone"]["low"] == 4124.0
    assert result["long_zone"]["high"] == 4128.0
    assert result["short_zone"]["low"] == 4158.0
    assert result["short_zone"]["high"] == 4162.0
    assert result["range"]["state"] == "LOCAL_RANGE"
    assert result["deep_htf_fallback"]["zone_id"] == "H4_SUPPLY_FAR"
    assert result["deep_htf_is_entry_trigger"] is False


def test_v390_can_ready_short_at_local_supply_before_h4() -> None:
    snap = _snapshot(4160.0)
    snap["support_resistance_map"]["nearest_resistance"].update(
        {
            "lifecycle_state": "UPSIDE_SWEEP_LIKE_REJECTION",
            "confirmed_flip": True,
        }
    )
    result = evaluate_simple_reversal(snap)
    assert result["state"] == "READY_SHORT"
    assert result["direction"] == "SHORT"
    assert result["entry"]["low"] == 4158.0
    assert result["entry"]["high"] == 4162.0
    assert result["entry"]["tp1_opposite_local_zone"] == 4128.0


def test_v390_can_ready_long_at_local_demand() -> None:
    snap = _snapshot(4126.0)
    snap["support_resistance_map"]["nearest_support"].update(
        {
            "lifecycle_state": "DOWNSIDE_SWEEP_LIKE_REJECTION",
            "confirmed_flip": True,
        }
    )
    result = evaluate_simple_reversal(snap)
    assert result["state"] == "READY_LONG"
    assert result["direction"] == "LONG"
    assert result["entry"]["low"] == 4124.0
    assert result["entry"]["high"] == 4128.0
    assert result["entry"]["tp1_opposite_local_zone"] == 4158.0


def test_v390_does_not_grant_auto_execution_authority() -> None:
    result = evaluate_simple_reversal(_snapshot(4142.0))
    assert result["execution_authority"] is False
    assert result["demo_auto_execution"] is False
    assert result["live_execution_enabled"] is False

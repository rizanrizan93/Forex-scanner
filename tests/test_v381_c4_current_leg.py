from __future__ import annotations

from fx_scanner.xau_sd_liquidity_engine_v342 import _current_leg_forecast


def _base_result(zone: dict, roadblock: dict | None = None) -> dict:
    return {
        "main_reversal_zone": zone,
        "decision_zone": zone,
        "nearest_roadblock": roadblock or {},
    }


def test_v381_supply_above_price_means_now_leg_long_then_short_reversal():
    result = _base_result(
        {
            "zone_id": "h4-supply",
            "timeframe": "H4",
            "direction": "SHORT",
            "low": 4280.0,
            "high": 4297.0,
            "atr": 28.0,
        }
    )
    leg = _current_leg_forecast(result, price_now=4140.0)
    assert leg["state"] == "TOWARD_NEXT_REVERSAL_ZONE"
    assert leg["direction"] == "LONG"
    assert leg["next_reversal_direction"] == "SHORT"
    assert leg["target_price"] == 4280.0
    assert leg["distance_points"] == 140.0
    assert leg["distance_atr"] == 5.0
    assert leg["horizon"] == "FAR"
    assert leg["eta_clock"] is None
    assert leg["execution_authority"] is False


def test_v381_demand_below_price_means_now_leg_short_then_long_reversal():
    result = _base_result(
        {
            "zone_id": "h4-demand",
            "timeframe": "H4",
            "direction": "LONG",
            "low": 4100.0,
            "high": 4120.0,
            "atr": 20.0,
        }
    )
    leg = _current_leg_forecast(result, price_now=4180.0)
    assert leg["state"] == "TOWARD_NEXT_REVERSAL_ZONE"
    assert leg["direction"] == "SHORT"
    assert leg["next_reversal_direction"] == "LONG"
    assert leg["target_price"] == 4120.0
    assert leg["distance_atr"] == 3.0


def test_v381_inside_main_zone_waits_for_reversal_not_travel_forecast():
    result = _base_result(
        {
            "zone_id": "h1-supply",
            "timeframe": "H1",
            "direction": "SHORT",
            "low": 4279.0,
            "high": 4290.0,
            "atr": 12.0,
        }
    )
    leg = _current_leg_forecast(result, price_now=4284.0)
    assert leg["state"] == "AT_MAIN_REVERSAL_ZONE"
    assert leg["direction"] == "WAIT_REACTION"
    assert leg["horizon"] == "NOW"
    assert leg["distance_atr"] == 0.0


def test_v381_checkpoint_must_lie_between_now_and_main_zone():
    result = _base_result(
        {
            "zone_id": "h4-supply",
            "timeframe": "H4",
            "direction": "SHORT",
            "low": 4280.0,
            "high": 4297.0,
            "atr": 28.0,
        },
        {
            "zone_id": "h1-roadblock",
            "timeframe": "H1",
            "type": "SUPPLY",
            "near_edge": 4180.0,
        },
    )
    leg = _current_leg_forecast(result, price_now=4140.0)
    assert leg["checkpoint"]["price"] == 4180.0
    assert leg["checkpoint"]["zone_id"] == "h1-roadblock"

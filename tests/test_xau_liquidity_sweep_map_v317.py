from fx_scanner.xau_liquidity_sweep_map_v317 import (
    CONTRACT,
    EXECUTION_AUTHORITY,
    EXECUTION_INFLUENCE,
    build_liquidity_sweep_map,
)


def test_v317_maps_narrow_supply_into_broader_parent_sweep_band():
    decision = {
        "zone_id": "narrow-supply",
        "timeframe": "H1",
        "zone_class": "IMBALANCE",
        "pattern": "RBD",
        "direction": "SHORT",
        "low": 4194.22,
        "high": 4200.19,
        "atr_points": 18.0,
        "lifecycle": {"active": True},
        "liquidity": {
            "nearby_levels": [
                {"price": 4200.0, "source": "ROUND_NUMBER"},
            ]
        },
    }
    broader = {
        "zone_id": "broad-supply",
        "timeframe": "H1",
        "zone_class": "STRUCTURAL",
        "pattern": "STRUCTURAL_SUPPLY",
        "direction": "SHORT",
        "low": 4182.85,
        "high": 4219.29,
        "atr_points": 20.0,
        "lifecycle": {"active": True},
        "liquidity": {
            "nearby_levels": [
                {"price": 4215.0, "source": "H1_SWING_HIGH"},
                {"price": 4210.0, "source": "ROUND_NUMBER"},
            ]
        },
    }
    atlas = {
        "zones": [decision, broader],
        "path_map": {
            "active_path": {
                "primary_opposing_zone": decision,
            }
        },
    }
    style = {
        "next_decision_zone": decision,
        "primary_path": {"destination_stack": [decision]},
    }

    result = build_liquidity_sweep_map(
        atlas_evaluation=atlas,
        style_path=style,
        price_now=4197.0,
    )

    assert result["contract"] == CONTRACT
    assert result["direction"] == "SHORT"
    assert result["sweep_side"] == "ABOVE_SUPPLY"
    assert result["decision_zone"]["low"] == 4194.22
    assert result["decision_zone"]["high"] == 4200.19
    assert result["sweep_band"]["low"] == 4194.22
    assert result["sweep_band"]["high"] >= 4215.0
    assert result["parent_extension_present"] is True
    assert result["risk_grade"] == "HIGH"
    assert result["first_touch_warning"] is True
    assert any(
        row["source"] == "H1_SWING_HIGH" and row["price"] == 4215.0
        for row in result["liquidity_levels"]
    )
    assert result["execution_influence"] is False
    assert result["execution_authority"] is False


def test_v317_maps_demand_sweep_below_zone():
    decision = {
        "zone_id": "demand",
        "timeframe": "H1",
        "direction": "LONG",
        "low": 4100.0,
        "high": 4110.0,
        "atr_points": 20.0,
        "lifecycle": {"active": True},
        "liquidity": {
            "nearby_levels": [
                {"price": 4095.0, "source": "EQUAL_LOW"},
            ]
        },
    }
    parent = {
        "zone_id": "parent-demand",
        "timeframe": "H4",
        "direction": "LONG",
        "low": 4090.0,
        "high": 4112.0,
        "atr_points": 25.0,
        "lifecycle": {"active": True},
        "liquidity": {
            "nearby_levels": [
                {"price": 4092.0, "source": "SESSION_ASIA_LOW"},
            ]
        },
    }
    result = build_liquidity_sweep_map(
        atlas_evaluation={"zones": [decision, parent]},
        style_path={"next_decision_zone": decision},
        price_now=4105.0,
    )
    assert result["direction"] == "LONG"
    assert result["sweep_side"] == "BELOW_DEMAND"
    assert result["sweep_band"]["low"] <= 4092.0
    assert result["sweep_band"]["high"] == 4110.0
    assert result["parent_extension_present"] is True


def test_v317_no_decision_zone_is_non_authoritative():
    result = build_liquidity_sweep_map(
        atlas_evaluation={},
        style_path={},
        price_now=4200.0,
    )
    assert result["state"] == "NO_DECISION_ZONE"
    assert result["execution_influence"] is False
    assert result["execution_authority"] is False
    assert EXECUTION_INFLUENCE is False
    assert EXECUTION_AUTHORITY is False

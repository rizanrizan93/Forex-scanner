from datetime import UTC, datetime, timedelta

from fx_scanner.xau_liquidity_pool_envelope_v328 import (
    CONTRACT,
    EXECUTION_AUTHORITY,
    EXECUTION_INFLUENCE,
    build_liquidity_pool_envelope,
)


AT = datetime(2026, 10, 1, 0, 0, tzinfo=UTC)


def _bars(highs, lows=None):
    if lows is None:
        lows = [value - 8.0 for value in highs]
    rows = []
    for i, (high, low) in enumerate(zip(highs, lows)):
        rows.append(
            {
                "time": (AT + timedelta(minutes=15 * i)).isoformat(),
                "open": (high + low) / 2.0,
                "high": high,
                "low": low,
                "close": (high + low) / 2.0,
            }
        )
    return rows


def test_v328_detects_equal_high_liquidity_beyond_narrow_supply_without_parent_zone():
    decision = {
        "zone_id": "supply-4194-4200",
        "timeframe": "H1",
        "zone_class": "STRUCTURAL",
        "pattern": "RBD",
        "direction": "SHORT",
        "low": 4194.0,
        "high": 4200.0,
        "atr_points": 18.0,
        "lifecycle": {"active": True},
    }
    highs = [
        4190.0, 4194.0, 4203.0, 4214.8, 4207.0, 4205.0,
        4208.0, 4215.2, 4206.0, 4204.0, 4202.0, 4201.0,
    ]
    atlas = {
        "zones": [decision],
        "chart_bars_m15": _bars(highs),
        "path_map": {"active_path": {"primary_opposing_zone": decision}},
    }

    result = build_liquidity_pool_envelope(
        atlas_evaluation=atlas,
        style_path={"next_decision_zone": decision},
        price_now=4197.0,
    )

    assert result["contract"] == CONTRACT
    assert result["direction"] == "SHORT"
    assert result["sweep_side"] == "ABOVE_SUPPLY"
    assert result["sweep_band"]["high"] >= 4215.0
    assert result["sweep_band"]["depth_usd"] >= 15.0
    assert result["clustered_liquidity_present"] is True
    assert result["risk_grade"] == "HIGH"
    assert result["first_touch_warning"] is True
    assert any(
        "M15_EQUAL_HIGHS" in row["sources"]
        and 4214.0 <= float(row["price"]) <= 4216.0
        for row in result["liquidity_pools"]
    )
    assert result["execution_influence"] is False
    assert result["execution_authority"] is False


def test_v328_detects_equal_low_liquidity_below_demand():
    decision = {
        "zone_id": "demand",
        "timeframe": "H1",
        "zone_class": "STRUCTURAL",
        "pattern": "DBR",
        "direction": "LONG",
        "low": 4100.0,
        "high": 4110.0,
        "atr_points": 20.0,
        "lifecycle": {"active": True},
    }
    lows = [
        4115.0, 4112.0, 4107.0, 4091.0, 4103.0, 4105.0,
        4102.0, 4091.4, 4104.0, 4106.0, 4108.0, 4110.0,
    ]
    highs = [value + 8.0 for value in lows]
    result = build_liquidity_pool_envelope(
        atlas_evaluation={
            "zones": [decision],
            "chart_bars_m15": _bars(highs, lows),
        },
        style_path={"next_decision_zone": decision},
        price_now=4105.0,
    )

    assert result["direction"] == "LONG"
    assert result["sweep_side"] == "BELOW_DEMAND"
    assert result["sweep_band"]["low"] <= 4091.5
    assert result["clustered_liquidity_present"] is True
    assert any(
        "M15_EQUAL_LOWS" in row["sources"]
        for row in result["liquidity_pools"]
    )


def test_v328_preserves_context_only_authority_when_no_decision_zone():
    result = build_liquidity_pool_envelope(
        atlas_evaluation={},
        style_path={},
        price_now=4200.0,
    )
    assert result["state"] == "NO_DECISION_ZONE"
    assert result["execution_influence"] is False
    assert result["execution_authority"] is False
    assert EXECUTION_INFLUENCE is False
    assert EXECUTION_AUTHORITY is False

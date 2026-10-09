from __future__ import annotations

from fx_scanner.xau_whalezone_reaction_base_v409 import (
    MIN_QUALITY_SCORE,
    evaluate_whalezone_reaction_base_v409,
)


def zone(
    direction: str,
    low: float,
    high: float,
    *,
    timeframe: str = "M15",
    zone_id: str,
    departure_range_atr: float = 1.9,
    departure_body_fraction: float = 0.88,
    structural_bos: bool = True,
    condition: str = "FRESH",
    touch_count: int = 0,
    base_range_atr: float = 0.42,
    base_bars: int = 2,
    intraday_quarantined: bool = False,
) -> dict:
    return {
        "direction": direction,
        "low": low,
        "high": high,
        "timeframe": timeframe,
        "zone_id": zone_id,
        "departure_range_atr": departure_range_atr,
        "departure_body_fraction": departure_body_fraction,
        "structural_bos": structural_bos,
        "condition": condition,
        "lifecycle": {"freshness": condition, "touch_count": touch_count},
        "base_range_atr": base_range_atr,
        "base_bars": base_bars,
        "atr": 20.0,
        "intraday_quarantined": intraday_quarantined,
    }


def test_v409_quality_gate_then_nearest_stacked_tiers() -> None:
    sd = {
        "price_now": 4175.0,
        "active_zones": [
            # Very near supply but poor reaction-base evidence: must not become SELL 1.
            zone(
                "SHORT",
                4176.0,
                4178.0,
                zone_id="weak-near",
                departure_range_atr=0.58,
                departure_body_fraction=0.42,
                structural_bos=False,
                condition="DEGRADED",
                touch_count=4,
                base_range_atr=1.20,
                base_bars=7,
            ),
            zone("SHORT", 4180.0, 4190.0, zone_id="sell-1"),
            zone("SHORT", 4215.0, 4225.0, timeframe="H1", zone_id="sell-2"),
            zone("LONG", 4130.0, 4140.0, zone_id="buy-1"),
            zone("LONG", 4105.0, 4115.0, timeframe="H1", zone_id="buy-2"),
        ],
    }

    result = evaluate_whalezone_reaction_base_v409(sd)

    assert result["state"] == "TWO_SIDED_WHALEZONE_MAP"
    assert [row["zone_id"] for row in result["sell_zones"]] == ["sell-1", "sell-2"]
    assert [row["zone_id"] for row in result["buy_zones"]] == ["buy-1", "buy-2"]
    assert [row["visual_label"] for row in result["sell_zones"]] == [
        "WHALEZONE SELL 1",
        "WHALEZONE SELL 2",
    ]
    assert [row["visual_label"] for row in result["buy_zones"]] == [
        "WHALEZONE BUY 1",
        "WHALEZONE BUY 2",
    ]
    assert all(row["quality_score"] >= MIN_QUALITY_SCORE for row in result["sell_zones"])
    assert all(row["quality_score"] >= MIN_QUALITY_SCORE for row in result["buy_zones"])


def test_v409_excludes_broken_and_quarantined_zones() -> None:
    broken = zone("LONG", 4140.0, 4150.0, zone_id="broken", condition="BROKEN")
    quarantined = zone(
        "SHORT", 4180.0, 4190.0, zone_id="quarantined", intraday_quarantined=True
    )
    good = zone("LONG", 4120.0, 4130.0, zone_id="good")

    result = evaluate_whalezone_reaction_base_v409(
        {"price_now": 4175.0, "active_zones": [broken, quarantined, good]}
    )

    assert [row["zone_id"] for row in result["buy_zones"]] == ["good"]
    assert result["sell_zones"] == []
    assert result["execution_authority"] is False
    assert result["live_execution_enabled"] is False
    assert result["proprietary_formula_claimed"] is False


def test_v409_missing_fvg_and_sweep_are_not_fabricated() -> None:
    row = zone("LONG", 4130.0, 4140.0, zone_id="transparent")
    result = evaluate_whalezone_reaction_base_v409(
        {"price_now": 4175.0, "active_zones": [row]}
    )
    selected = result["buy_zones"][0]
    components = selected["quality_components"]

    assert components["imbalance_fvg"]["available"] is False
    assert components["liquidity_sweep"]["available"] is False
    assert selected["evidence_weight"] < 1.0
    assert result["model"]["missing_evidence_policy"] == (
        "RENORMALIZE_AVAILABLE_COMPONENTS_DO_NOT_INVENT"
    )

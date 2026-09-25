from pathlib import Path

from fx_scanner.demo_xau_v226_rizan_depth_map import (
    _applicability,
    _depth_band_prices,
    _historical_profile,
    _nested_locator,
    _select_h1,
    _select_m15,
    build_depth_map,
)

ROOT = Path(__file__).resolve().parents[1]


def _history() -> dict:
    def band(name: str, lo: float, hi: float, at_risk: int, reversals: int) -> dict:
        return {
            "band": name,
            "lower_depth": lo,
            "upper_depth": hi,
            "at_risk": at_risk,
            "reversals": reversals,
            "hazard": reversals / at_risk,
        }

    eras = {}
    for era in ("2012_2018", "2019_2024", "2025_2026"):
        eras[era] = {
            "summary": {
                "H4": {
                    "LONG": {
                        "touches": 100,
                        "hold_rate": 0.70,
                        "depth_median": 0.20,
                        "hazard_by_depth_band": [
                            band("00-10%", 0.0, 0.1, 100, 24),
                            band("10-20%", 0.1, 0.2, 75, 10),
                        ],
                        "highest_hazard_bands_min_n": [
                            band("00-10%", 0.0, 0.1, 100, 24),
                        ],
                    },
                    "SHORT": {
                        "touches": 100,
                        "hold_rate": 0.70,
                        "depth_median": 0.20,
                        "hazard_by_depth_band": [
                            band("00-10%", 0.0, 0.1, 100, 23),
                            band("10-20%", 0.1, 0.2, 77, 11),
                        ],
                        "highest_hazard_bands_min_n": [
                            band("00-10%", 0.0, 0.1, 100, 23),
                        ],
                    },
                },
                "H1": {
                    "LONG": {
                        "touches": 200,
                        "hold_rate": 0.71,
                        "depth_median": 0.21,
                        "hazard_by_depth_band": [
                            band("00-10%", 0.0, 0.1, 200, 42),
                            band("10-20%", 0.1, 0.2, 158, 23),
                        ],
                        "highest_hazard_bands_min_n": [
                            band("00-10%", 0.0, 0.1, 200, 42),
                        ],
                    },
                    "SHORT": {
                        "touches": 200,
                        "hold_rate": 0.69,
                        "depth_median": 0.21,
                        "hazard_by_depth_band": [
                            band("00-10%", 0.0, 0.1, 200, 41),
                            band("10-20%", 0.1, 0.2, 159, 22),
                        ],
                        "highest_hazard_bands_min_n": [
                            band("00-10%", 0.0, 0.1, 200, 41),
                        ],
                    },
                },
                "M15": {
                    "LONG": {
                        "touches": 500,
                        "hold_rate": 0.88,
                        "depth_median": 0.58,
                        "hazard_by_depth_band": [
                            band("00-10%", 0.0, 0.1, 500, 15),
                            band("90-100%", 0.9, 1.0, 160, 46),
                        ],
                        "highest_hazard_bands_min_n": [
                            band("90-100%", 0.9, 1.0, 160, 46),
                        ],
                    },
                    "SHORT": {
                        "touches": 500,
                        "hold_rate": 0.88,
                        "depth_median": 0.58,
                        "hazard_by_depth_band": [
                            band("00-10%", 0.0, 0.1, 500, 15),
                            band("90-100%", 0.9, 1.0, 160, 47),
                        ],
                        "highest_hazard_bands_min_n": [
                            band("90-100%", 0.9, 1.0, 160, 47),
                        ],
                    },
                },
            }
        }
    return {
        "contract": "XAU_ZONE_REVERSAL_DEPTH_V225_1_EVIDENCE_1_FULL_2012_2026_1",
        "research_version": "XAU_ZONE_REVERSAL_DEPTH_V225_1",
        "years": list(range(2012, 2027)),
        "year_count": 15,
        "episode_count": 71739,
        "key_findings": [
            {
                "timeframe": "H4",
                "direction": "LONG",
                "touches": 300,
                "hold_rate": 0.71,
                "hold_wilson_lower_95": 0.65,
                "depth_p25": 0.07,
                "depth_median": 0.20,
                "depth_p75": 0.44,
            },
            {
                "timeframe": "H4",
                "direction": "SHORT",
                "touches": 300,
                "hold_rate": 0.70,
                "hold_wilson_lower_95": 0.64,
                "depth_p25": 0.06,
                "depth_median": 0.19,
                "depth_p75": 0.43,
            },
            {
                "timeframe": "H1",
                "direction": "LONG",
                "touches": 600,
                "hold_rate": 0.72,
                "hold_wilson_lower_95": 0.68,
                "depth_p25": 0.07,
                "depth_median": 0.21,
                "depth_p75": 0.44,
            },
            {
                "timeframe": "H1",
                "direction": "SHORT",
                "touches": 600,
                "hold_rate": 0.70,
                "hold_wilson_lower_95": 0.66,
                "depth_p25": 0.07,
                "depth_median": 0.21,
                "depth_p75": 0.46,
            },
            {
                "timeframe": "M15",
                "direction": "LONG",
                "touches": 1500,
                "hold_rate": 0.88,
                "hold_wilson_lower_95": 0.86,
                "depth_p25": 0.35,
                "depth_median": 0.58,
                "depth_p75": 0.79,
            },
            {
                "timeframe": "M15",
                "direction": "SHORT",
                "touches": 1500,
                "hold_rate": 0.88,
                "hold_wilson_lower_95": 0.86,
                "depth_p25": 0.36,
                "depth_median": 0.58,
                "depth_p75": 0.79,
            },
        ],
        "hierarchy": {
            "h4_successes": 3448,
            "h1_child_coverage": 0.459,
            "m15_child_coverage_given_h1": 0.388,
            "h1_child_depth": {
                "n_total": 1583,
                "n_inside_0_100": 1581,
                "p25": 0.17,
                "median": 0.37,
                "p75": 0.64,
                "modal_bands": [{"band": "00-10%", "count": 247}],
            },
            "m15_child_depth": {
                "n_total": 614,
                "n_inside_0_100": 611,
                "p25": 0.22,
                "median": 0.46,
                "p75": 0.72,
                "modal_bands": [{"band": "10-20%", "count": 72}],
            },
        },
        "eras": eras,
    }


def _zone(
    zone_id: str,
    *,
    timeframe: str,
    direction: str,
    low: float,
    high: float,
    touches: int = 0,
    score: float = 70.0,
) -> dict:
    return {
        "zone_id": zone_id,
        "timeframe": timeframe,
        "direction": direction,
        "low": low,
        "high": high,
        "origin_at": "2026-09-25T00:00:00+00:00",
        "available_at": "2026-09-25T04:00:00+00:00",
        "research_score": score,
        "status": "ACTIVE_WATCH_PREPARE_ONLY",
        "lifecycle": {
            "active": True,
            "touch_count": touches,
            "freshness": "FRESH" if touches == 0 else "MULTI_TESTED",
        },
    }


def test_v226_depth_band_converts_demand_and_supply_to_prices() -> None:
    demand = _zone("d", timeframe="H4", direction="LONG", low=4244.0, high=4275.0)
    supply = _zone("s", timeframe="H4", direction="SHORT", low=4300.0, high=4320.0)
    assert _depth_band_prices(demand, 0.0, 0.1) == {
        "low": 4271.9,
        "high": 4275.0,
        "lower_depth": 0.0,
        "upper_depth": 0.1,
    }
    assert _depth_band_prices(supply, 0.0, 0.1) == {
        "low": 4300.0,
        "high": 4302.0,
        "lower_depth": 0.0,
        "upper_depth": 0.1,
    }


def test_v226_historical_profile_aggregates_eras_and_confirms_stability() -> None:
    profile = _historical_profile(_history(), "H4", "LONG")
    top = profile["highest_hazard_band"]
    assert top["band"] == "00-10%"
    assert top["at_risk"] == 300
    assert top["reversals"] == 72
    assert profile["stable_top_band_across_eras"] is True
    assert abs(profile["hazard_bands"][0]["hazard"] - 0.24) < 1e-12


def test_v226_marks_multitested_zone_as_low_first_touch_applicability() -> None:
    zone = _zone(
        "d",
        timeframe="H4",
        direction="LONG",
        low=4244.0,
        high=4275.0,
        touches=3,
    )
    result = _applicability(zone, 4290.0)
    assert result["state"] == "LOW_REUSE_OUT_OF_SAMPLE"


def test_v226_h1_selector_prefers_child_intersecting_h4_hotspot() -> None:
    parent = _zone("h4", timeframe="H4", direction="LONG", low=4240, high=4280)
    hotspot = {"low": 4276.0, "high": 4280.0}
    zones = [
        _zone("near-but-deep", timeframe="H1", direction="LONG", low=4250, high=4260),
        _zone("hotspot-child", timeframe="H1", direction="LONG", low=4274, high=4278),
    ]
    selected = _select_h1(
        zones,
        parent=parent,
        hotspot=hotspot,
        direction="LONG",
        price=4290.0,
    )
    assert selected["zone_id"] == "hotspot-child"


def test_v226_m15_selector_uses_nested_locator_overlap_not_standalone_deep_profile() -> None:
    parent = _zone("h1", timeframe="H1", direction="LONG", low=4270, high=4280)
    locator = {"low": 4274.0, "high": 4277.0}
    zones = [
        _zone("m15-a", timeframe="M15", direction="LONG", low=4270.5, high=4272.0),
        _zone("m15-b", timeframe="M15", direction="LONG", low=4275.0, high=4276.5),
    ]
    selected = _select_m15(
        zones,
        parent=parent,
        locator=locator,
        direction="LONG",
        price=4285.0,
    )
    assert selected["zone_id"] == "m15-b"


def test_v226_nested_locator_maps_child_quantiles_to_actual_prices() -> None:
    child = _zone("m15", timeframe="M15", direction="LONG", low=100.0, high=110.0)
    locator = _nested_locator(
        child,
        {"n_total": 100, "n_inside_0_100": 99, "p25": 0.20, "median": 0.50, "p75": 0.70},
    )
    assert locator["envelope"]["low"] == 103.0
    assert locator["envelope"]["high"] == 108.0
    assert locator["median"]["price"] == 105.0


def test_v226_build_map_keeps_execution_authority_off() -> None:
    atlas = {
        "as_of": "2026-09-25T16:00:00+00:00",
        "last_closed_m15_price": 4290.0,
        "zones": [
            _zone("h4d", timeframe="H4", direction="LONG", low=4244.0, high=4275.0),
            _zone("h1d", timeframe="H1", direction="LONG", low=4269.0, high=4274.0),
            _zone("h4s", timeframe="H4", direction="SHORT", low=4310.0, high=4340.0),
            _zone("h1s", timeframe="H1", direction="SHORT", low=4310.0, high=4316.0),
        ],
        "chart_bars_m15": [],
        "m5_path_projection": {"current_leg": {"direction": "LONG"}},
    }
    result = build_depth_map(atlas_evaluation=atlas, history_details=_history())
    assert result["state"] == "RIZAN_DEPTH_MAP_AVAILABLE"
    assert result["focus_direction"] == "LONG"
    assert result["long"]["h4"]["hotspot"]["low"] == 4271.9
    assert result["execution_influence"] is False
    assert result["execution_authority"] is False
    assert result["promotion_authority"] is False


def test_v226_workflow_and_dashboard_are_shadow_only() -> None:
    workflow = (ROOT / ".github/workflows/ctrader-demo-maintenance-pipeline.yml").read_text()
    assert "python -m fx_scanner.demo_xau_v226_rizan_depth_map" in workflow
    assert workflow.index("demo_xau_supply_demand_atlas_v182") < workflow.index(
        "demo_xau_v226_rizan_depth_map"
    )

    dashboard = (ROOT / "streamlit_app.py").read_text()
    assert "V226 — RIZAN Depth Map" in dashboard
    assert "RIZAN Depth hotspot" in dashboard
    assert "V226 tetap shadow-only" in dashboard

    source = (ROOT / "src/fx_scanner/demo_xau_v226_rizan_depth_map.py").read_text()
    assert 'POLICY_EFFECT = "SHADOW_ONLY"' in source
    assert '"execution_authority": False' in source

from fx_scanner.dashboard import merge_runtime_heartbeat_rows


def test_v259_v226_empty_candidate_clears_cached_old_locator() -> None:
    base = [
        {
            "worker_name": "ctrader_demo_xau_v226_rizan_depth_map",
            "observed_at": "2026-09-29T05:35:00+00:00",
            "healthy": True,
            "lag_seconds": 0,
            "details": {
                "evaluation": {
                    "focus_direction": "SHORT",
                    "depth_entry_candidate": {
                        "direction": "SHORT",
                        "entry_low": 4357.64,
                        "entry_high": 4359.52,
                    },
                    "short": {
                        "h4": {
                            "zone": {
                                "zone_id": "old-short-h4",
                                "direction": "SHORT",
                                "low": 4357.51,
                                "high": 4365.51,
                            },
                            "historical_profile": {"touches": 2000},
                        }
                    },
                }
            },
        }
    ]
    overlay = [
        {
            "worker_name": "ctrader_demo_xau_v226_rizan_depth_map",
            "observed_at": "2026-09-29T05:42:30+00:00",
            "healthy": True,
            "lag_seconds": 0,
            "details": {
                "evaluation": {
                    "focus_direction": "LONG",
                    "depth_entry_candidate": {},
                    "four_order_ladder": {},
                    "long": {
                        "h4": {
                            "zone": {
                                "zone_id": "new-long-h4",
                                "direction": "LONG",
                                "low": 4110.0,
                                "high": 4128.0,
                            }
                        }
                    },
                },
                "transport_projection": "V226_OPERATIONAL_60S",
            },
        }
    ]

    row = merge_runtime_heartbeat_rows(base, overlay)[0]
    evaluation = row["details"]["evaluation"]
    assert row["observed_at"] == "2026-09-29T05:42:30+00:00"
    assert evaluation["focus_direction"] == "LONG"
    assert evaluation["depth_entry_candidate"] == {}
    assert evaluation["long"]["h4"]["zone"]["zone_id"] == "new-long-h4"
    assert evaluation["short"]["h4"]["historical_profile"]["touches"] == 2000


def test_v259_v182_current_path_and_refined_m5_replace_cached_leg_only() -> None:
    base = [
        {
            "worker_name": "ctrader_demo_xau_supply_demand_atlas_v182",
            "observed_at": "2026-09-29T05:36:00+00:00",
            "healthy": True,
            "lag_seconds": 0,
            "details": {
                "evaluation": {
                    "zones": [{"zone_id": "cached-zone"}],
                    "chart_bars_m15": [{"time": "cached"}],
                    "path_map": {
                        "active_path": {
                            "reaction_direction": "SHORT",
                            "source_zone": {"zone_id": "old-supply"},
                        }
                    },
                    "m5_path_projection": {
                        "current_leg": {
                            "direction": "SHORT",
                            "pocket_state": "NO_M5_POCKET_YET",
                        }
                    },
                }
            },
        }
    ]
    overlay = [
        {
            "worker_name": "ctrader_demo_xau_supply_demand_atlas_v182",
            "observed_at": "2026-09-29T05:42:27+00:00",
            "healthy": True,
            "lag_seconds": 0,
            "details": {
                "evaluation": {
                    "nearest_demand": {"zone_id": "current-demand"},
                    "nearest_supply": {"zone_id": "current-supply"},
                    "path_map": {
                        "active_path": {
                            "reaction_direction": "LONG",
                            "source_zone": {"zone_id": "current-demand"},
                            "reaction_target": {"price": 4136.55},
                        }
                    },
                    "m5_path_projection": {
                        "current_leg": {
                            "direction": "LONG",
                            "pocket_state": "REFINED_M5_POCKET",
                            "m5_pocket": {"low": 4122.14, "high": 4129.96},
                        },
                        "next_leg": {
                            "direction": "SHORT",
                            "pocket_state": "NO_M5_POCKET_YET",
                        },
                    },
                },
                "transport_projection": "V182_OPERATIONAL_60S",
            },
        }
    ]

    row = merge_runtime_heartbeat_rows(base, overlay)[0]
    evaluation = row["details"]["evaluation"]
    assert evaluation["zones"] == [{"zone_id": "cached-zone"}]
    assert evaluation["chart_bars_m15"] == [{"time": "cached"}]
    assert evaluation["path_map"]["active_path"]["reaction_direction"] == "LONG"
    assert evaluation["path_map"]["active_path"]["source_zone"]["zone_id"] == "current-demand"
    assert evaluation["m5_path_projection"]["current_leg"]["pocket_state"] == "REFINED_M5_POCKET"
    assert evaluation["m5_path_projection"]["current_leg"]["m5_pocket"] == {
        "low": 4122.14,
        "high": 4129.96,
    }


def test_v279_prepared_null_live_price_clears_cached_old_price() -> None:
    base = [
        {
            "worker_name": "ctrader_demo_xau_rizan_prepared_plan_producer",
            "observed_at": "2026-09-29T20:59:08+00:00",
            "healthy": True,
            "lag_seconds": 0,
            "details": {
                "forecast_state": "NO_MAP_ZONE",
                "live_price": 4166.165,
                "distance_to_zone_points": 12.0,
                "proximity_state": "FAR",
            },
        }
    ]
    overlay = [
        {
            "worker_name": "ctrader_demo_xau_rizan_prepared_plan_producer",
            "observed_at": "2026-09-29T21:04:51+00:00",
            "healthy": True,
            "lag_seconds": 0,
            "details": {
                "forecast_state": "NO_MAP_ZONE",
                "live_price": None,
                "distance_to_zone_points": None,
                "proximity_state": "UNKNOWN",
            },
        }
    ]

    row = merge_runtime_heartbeat_rows(base, overlay)[0]
    assert row["observed_at"] == "2026-09-29T21:04:51+00:00"
    assert row["details"]["live_price"] is None
    assert row["details"]["distance_to_zone_points"] is None
    assert row["details"]["proximity_state"] == "UNKNOWN"

from types import SimpleNamespace

from fx_scanner.dashboard import (
    SupabaseDashboardReader,
    merge_runtime_heartbeat_rows,
)


class _Query:
    def __init__(self, row):
        self.row = row
        self.selected = None
        self.worker = None
    def table(self, name):
        assert name == "runtime_heartbeats"
        return self
    def select(self, fields):
        self.selected = fields
        return self
    def eq(self, field, value):
        assert field == "worker_name"
        self.worker = value
        return self
    def order(self, *_args, **_kwargs):
        return self
    def limit(self, n):
        assert n == 1
        return self
    def execute(self):
        return SimpleNamespace(data=[self.row])


def test_v332_v296_projection_omits_heavy_calibration_and_votes():
    query = _Query({
        "worker_name": "ctrader_demo_xau_decision_center_v296",
        "observed_at": "2026-10-01T08:00:00+00:00",
        "healthy": True,
        "lag_seconds": 0,
        "action": "WAIT_NO_CANONICAL_GEOMETRY",
        "agreement": 1.0,
        "confidence": 24.1,
        "consensus_direction": "SHORT",
        "coverage": 0.8,
        "dominant_direction": "SHORT",
        "evidence_coverage": 0.7,
        "geometry": {},
        "hard_blocks": [],
        "liquidity_sweep_map_v328": {"risk_grade": "HIGH"},
        "meta_research_calibration": {"state": "COLLECTING"},
        "reference_geometry": {},
        "rizan_style_path_engine": {"active_direction": "SHORT"},
        "support_evidence": [{"engine": "TEST"}],
        "code_version": "abc",
    })
    row = SupabaseDashboardReader(query).latest_xau_decision_center_operational_heartbeat()
    assert row is not None
    decision = row["details"]["decision"]
    assert decision["action"] == "WAIT_NO_CANONICAL_GEOMETRY"
    assert decision["liquidity_sweep_map_v328"]["risk_grade"] == "HIGH"
    assert "votes" not in decision
    assert "rizan_style_path_calibration_v304" not in decision
    assert "votes:details->decision->votes" not in query.selected
    assert "rizan_style_path_calibration_v304" not in query.selected


def test_v332_v328_projection_keeps_micro_ui_fields_without_duplicate_h1_m5_payloads():
    query = _Query({
        "worker_name": "ctrader_demo_xau_micro_destination_v328",
        "observed_at": "2026-10-01T08:00:00+00:00",
        "healthy": True,
        "lag_seconds": 0,
        "state": "READY",
        "direction": "SHORT",
        "phase": "WATCH",
        "price_now": 4190.0,
        "confidence": 0.7,
        "primary": {"setup_role": "PRIMARY"},
        "decision_zone": {"low": 4194.0, "high": 4200.0},
        "entries": [{"price": 4198.0}],
        "targets": [{"price": 4170.0}],
        "anchor": {"price": 4198.0},
        "levels": {"entry": 4198.0},
        "nearest_opposing_zone": {"low": 4160.0, "high": 4170.0},
        "destination_cascade": {"skipped_zones": []},
        "liquidity_sweep_context": {"risk_grade": "HIGH"},
        "primary_setup_role": "PRIMARY",
        "active_zone": {"zone_id": "supply"},
        "active_no_chase": True,
        "active_distance_atr": 0.2,
        "active_price_relation": "BELOW",
        "next_zone": {"zone_id": "demand"},
        "next_selected_rank": 1,
        "next_price_relation": "ABOVE",
        "next_cascaded": False,
    })
    row = SupabaseDashboardReader(query).latest_xau_micro_destination_operational_heartbeat()
    assert row is not None
    ev = row["details"]["evaluation"]
    assert ev["decision_zone"]["high"] == 4200.0
    assert ev["active_source"]["zone"]["zone_id"] == "supply"
    assert ev["next_opposing"]["zone"]["zone_id"] == "demand"
    assert "active_source->h1" not in query.selected
    assert "active_source->m5" not in query.selected
    assert "next_opposing->h1" not in query.selected
    assert "next_opposing->m5" not in query.selected


def test_v332_compact_v296_overlay_preserves_hourly_votes_and_updates_action():
    base = [{
        "worker_name": "ctrader_demo_xau_decision_center_v296",
        "observed_at": "2026-10-01T07:00:00+00:00",
        "healthy": True,
        "details": {
            "decision": {
                "action": "OLD",
                "votes": [{"engine": "V1"}],
                "rizan_style_path_calibration_v304": {"state": "CALIBRATED"},
            },
            "engine_calibration": {"large": True},
        },
    }]
    overlay = [{
        "worker_name": "ctrader_demo_xau_decision_center_v296",
        "observed_at": "2026-10-01T08:00:00+00:00",
        "healthy": True,
        "details": {
            "decision": {
                "action": "WAIT_LIQUIDITY_SWEEP_CONFIRMATION",
                "confidence": 55.0,
            },
            "transport_projection": "V296_OPERATIONAL_60S",
        },
    }]
    merged = merge_runtime_heartbeat_rows(base, overlay)
    decision = merged[0]["details"]["decision"]
    assert decision["action"] == "WAIT_LIQUIDITY_SWEEP_CONFIRMATION"
    assert decision["confidence"] == 55.0
    assert decision["votes"][0]["engine"] == "V1"
    assert decision["rizan_style_path_calibration_v304"]["state"] == "CALIBRATED"
    assert merged[0]["details"]["engine_calibration"]["large"] is True


def test_v332_compact_v328_overlay_preserves_hourly_diagnostic_fields():
    base = [{
        "worker_name": "ctrader_demo_xau_micro_destination_v328",
        "observed_at": "2026-10-01T07:00:00+00:00",
        "healthy": True,
        "details": {
            "evaluation": {
                "state": "OLD",
                "h1_debug": {"large": True},
                "primary": {"old": True},
            }
        },
    }]
    overlay = [{
        "worker_name": "ctrader_demo_xau_micro_destination_v328",
        "observed_at": "2026-10-01T08:00:00+00:00",
        "healthy": True,
        "details": {
            "evaluation": {
                "state": "READY",
                "primary": {"new": True},
            },
            "transport_projection": "V328_OPERATIONAL_60S",
        },
    }]
    merged = merge_runtime_heartbeat_rows(base, overlay)
    ev = merged[0]["details"]["evaluation"]
    assert ev["state"] == "READY"
    assert ev["primary"] == {"new": True}
    assert ev["h1_debug"]["large"] is True


def test_v344_v342_projection_keeps_structural_tab_fields_without_full_details():
    query = _Query({
        "worker_name": "ctrader_demo_xau_sd_liquidity_v342",
        "observed_at": "2026-10-02T04:25:45+00:00",
        "healthy": True,
        "lag_seconds": 0,
        "state": "MAP_AVAILABLE",
        "price_now": 4187.99,
        "decision_zone": {"timeframe": "H4", "low": 4176.54, "high": 4219.29},
        "main_reversal_zone": {"timeframe": "H4", "direction": "SHORT"},
        "refinement_zone": {"timeframe": "H1", "direction": "SHORT"},
        "structural_destination": {"low": 4144.56, "high": 4175.17},
        "structural_room": {"state": "COMPRESSED_HTF_CORRIDOR", "blocked": True},
        "structural_path": {"state": "PATH_AVAILABLE", "checkpoints": [{"order": 1}]},
        "failure_path": {"state": "CONDITIONAL_ONLY", "checkpoints": []},
        "support_resistance": [{"kind": "RESISTANCE", "price": 4187.3}],
        "nearest_roadblock": {},
        "micro_confirmation": {"stage": "RECLAIM_WAIT_MSS_DISPLACEMENT"},
        "entry_guide": {"state": "WAIT_STRUCTURAL_ROOM"},
        "liquidity_map": {"side": "BUY_SIDE"},
        "news_zone": {"risk_state": "CLEAR"},
        "market_structure": {"H4": {"state": "BEARISH_RANGE"}},
        "expected_reversal_direction": "SHORT",
        "historical_depth_prior": {"H4": {"touches": 4831}},
        "active_zones": [{"timeframe": "H4", "direction": "SHORT"}],
    })
    row = SupabaseDashboardReader(query).latest_xau_sd_liquidity_operational_heartbeat()
    assert row is not None
    ev = row["details"]["evaluation"]
    assert ev["state"] == "MAP_AVAILABLE"
    assert ev["price_now"] == 4187.99
    assert ev["structural_path"]["checkpoints"][0]["order"] == 1
    assert ev["entry_guide"]["state"] == "WAIT_STRUCTURAL_ROOM"
    assert ev["market_structure"]["H4"]["state"] == "BEARISH_RANGE"
    assert "details" not in query.selected.split(",")
    assert "structural_checkpoints:details->evaluation->structural_path->checkpoints" in query.selected
    assert "active_zones:" not in query.selected
    assert row["details"]["transport_projection"] == "V342_OPERATIONAL_60S_COMPACT"


def test_v344_v343_projection_keeps_micro_entry_tab_fields_without_full_details():
    query = _Query({
        "worker_name": "ctrader_demo_xau_friend_entry_v343",
        "observed_at": "2026-10-02T04:25:45+00:00",
        "healthy": True,
        "lag_seconds": 0,
        "state": "Y_RETEST_WINDOW",
        "direction": "SHORT",
        "price_now": 4187.99,
        "delta": 0.5431,
        "parent_zone": {"timeframe": "H4", "direction": "SHORT"},
        "levels": {"A": 4150.2, "X": 4149.65, "Y": 4149.11},
        "entries": {"historical_primary_price": 4149.11},
        "targets": {"TP5": 4147.48, "TP8": 4145.85, "TP13": 4143.14},
        "stop_loss": 4219.83,
        "historical_evidence": {"full_2012_2026": {"fills": 13933}},
        "news_zone_context": {"risk_state": "CLEAR"},
    })
    row = SupabaseDashboardReader(query).latest_xau_friend_entry_operational_heartbeat()
    assert row is not None
    ev = row["details"]["evaluation"]
    assert ev["state"] == "Y_RETEST_WINDOW"
    assert ev["direction"] == "SHORT"
    assert ev["entries"]["historical_primary_price"] == 4149.11
    assert ev["targets"]["TP13"] == 4143.14
    assert "details" not in query.selected.split(",")
    assert "historical_evidence:details->evaluation->historical_evidence" in query.selected
    assert row["details"]["transport_projection"] == "V343_OPERATIONAL_60S"


def test_v344_generic_merge_preserves_v342_compact_evaluation_over_summary_row():
    base = [{
        "worker_name": "ctrader_demo_xau_sd_liquidity_v342",
        "observed_at": "2026-10-02T06:00:00+00:00",
        "healthy": True,
        "lag_seconds": 0,
    }]
    overlay = [{
        "worker_name": "ctrader_demo_xau_sd_liquidity_v342",
        "observed_at": "2026-10-02T06:01:00+00:00",
        "healthy": True,
        "lag_seconds": 0,
        "details": {
            "evaluation": {
                "state": "MAP_AVAILABLE",
                "price_now": 4187.99,
                "entry_guide": {"state": "WAIT_STRUCTURAL_ROOM"},
            },
            "transport_projection": "V342_OPERATIONAL_60S_COMPACT",
        },
    }]
    merged = merge_runtime_heartbeat_rows(base, overlay)
    assert merged[0]["details"]["evaluation"]["state"] == "MAP_AVAILABLE"
    assert merged[0]["details"]["evaluation"]["price_now"] == 4187.99
    assert merged[0]["details"]["transport_projection"] == "V342_OPERATIONAL_60S_COMPACT"


def test_v344_generic_merge_preserves_v343_compact_evaluation_over_summary_row():
    base = [{
        "worker_name": "ctrader_demo_xau_friend_entry_v343",
        "observed_at": "2026-10-02T06:00:00+00:00",
        "healthy": True,
        "lag_seconds": 0,
    }]
    overlay = [{
        "worker_name": "ctrader_demo_xau_friend_entry_v343",
        "observed_at": "2026-10-02T06:01:00+00:00",
        "healthy": True,
        "lag_seconds": 0,
        "details": {
            "evaluation": {
                "state": "Y_RETEST_WINDOW",
                "direction": "SHORT",
                "entries": {"historical_primary_price": 4149.11},
            },
            "transport_projection": "V343_OPERATIONAL_60S",
        },
    }]
    merged = merge_runtime_heartbeat_rows(base, overlay)
    assert merged[0]["details"]["evaluation"]["state"] == "Y_RETEST_WINDOW"
    assert merged[0]["details"]["evaluation"]["direction"] == "SHORT"
    assert merged[0]["details"]["transport_projection"] == "V343_OPERATIONAL_60S"

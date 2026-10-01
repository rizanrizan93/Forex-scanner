from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_v209_dashboard_uses_60_second_cache_for_user_facing_state() -> None:
    text = _read("streamlit_app.py")
    assert text.count("@st.cache_data(ttl=60") >= 2
    assert "def _load_backend_fast_snapshot" in text
    assert "def _load_backend_slow_snapshot" in text
    assert "def _load_backend_decision_snapshot" in text
    assert "@st.cache_data(ttl=300" in text
    assert '"signals": list(reader.latest_signals())' in text
    assert '"broker_account": broker_account' in text
    assert '"heartbeats": list(reader.heartbeat_summaries())' in text
    assert "reader.heartbeats_for_workers" in text
    assert "def _load_full_heartbeat_details" in text
    assert '"xau_geometry_events": list(reader.latest_xau_geometry_events_compact(limit=2))' in text
    assert "merged.update(_load_backend_fast_snapshot" in text


def test_v209_reference_symbol_noop_updates_are_suppressed_in_database() -> None:
    schema = _read("supabase/schemas/fx_core.sql")
    assert "fx_symbols_skip_noop_update_v209" in schema
    assert "before update on public.fx_symbols" in schema
    assert "return null;" in schema

def test_v209_broker_order_identity_index_is_declared() -> None:
    schema = _read("supabase/schemas/fx_core.sql")
    assert "broker_order_events_backend_account_order_event_idx" in schema
    assert "(backend, account_id, broker_order_id, event_type)" in schema
    assert "FOREX_SCANNER_IO_BUDGET_V209" in schema


def test_v209_keeps_bounded_discovery_and_pauses_heavy_calibration() -> None:
    supervisor = _read(".github/workflows/ctrader-demo-auto-supervisor.yml")
    discovery = _read(".github/workflows/ctrader-demo-discovery-pipeline.yml")
    calibration = _read(".github/workflows/ctrader-demo-calibration-pipeline.yml")

    assert "discovery_check_seconds=900" in supervisor
    assert "calibration_mode=PAUSED_XAU_ONLY" in supervisor
    assert "SUPERVISOR_CALIBRATION_PAUSED_XAU_ONLY" in supervisor
    assert "dispatch_workflow ctrader-demo-calibration-pipeline.yml" not in supervisor

    assert "python -m fx_scanner.demo_xau_technical_producer" in discovery
    assert "python -m fx_scanner.demo_closed_trade_reconciler" not in discovery
    assert "python -m fx_scanner.demo_xau_strategy_latency_telemetry" not in discovery

    assert "python -m fx_scanner.demo_xau_strategy_latency_telemetry" in calibration
    assert "python -m fx_scanner.demo_closed_trade_reconciler" in calibration
    assert "python -m fx_scanner.demo_normalized_calibration_runner adaptive-v2" in calibration

    execution = _read(".github/workflows/ctrader-demo-xau-execution-lane.yml")
    auto = _read(".github/workflows/ctrader-demo-auto-pipeline.yml")
    assert "ctrader_demo_xau_execution_lane RUNNING" not in execution
    assert "ctrader_demo_xau_execution_lane SUCCESS" in execution
    assert "ctrader_demo_auto_pipeline RUNNING" not in auto
    assert "ctrader_demo_auto_pipeline SUCCESS" in auto
    assert "ctrader_demo_discovery_pipeline RUNNING" not in discovery
    assert "ctrader_demo_discovery_pipeline SUCCESS" in discovery


def test_v209_dashboard_hot_path_keeps_bounded_egress_contract() -> None:
    app = _read("streamlit_app.py")
    dashboard = _read("src/fx_scanner/dashboard.py")

    assert "RIZAN_DASHBOARD_HOT_HEARTBEATS" in app
    assert "RIZAN_DASHBOARD_SUPPORT_HEARTBEATS" in app
    assert "def _load_backend_support_snapshot" in app
    assert "def heartbeat_summaries" in dashboard
    assert "def heartbeats_for_workers" in dashboard
    assert "def latest_xau_geometry_events" in dashboard
    assert "symbol:payload->>symbol" in dashboard
    assert "prepared_plan:payload->prepared_plan" in dashboard
    assert "map_at:payload->forecast->>map_at" in dashboard
    assert '"heartbeats": list(reader.heartbeat_summaries())' in app


def test_v2593_geometry_hot_path_is_server_projected() -> None:
    dashboard = _read("src/fx_scanner/dashboard.py")
    assert "def latest_xau_geometry_events_compact" in dashboard
    assert "def latest_rizan_execution_geometry_compact" in dashboard
    assert "candidate_low:payload->candidate_low" in dashboard
    assert "planned_sl:payload->planned_sl" in dashboard

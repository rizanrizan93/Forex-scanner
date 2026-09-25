from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_v209_dashboard_uses_tiered_cache_without_slowing_fast_state() -> None:
    text = _read("streamlit_app.py")
    assert "@st.cache_data(ttl=15" in text
    assert "def _load_backend_fast_snapshot" in text
    assert "@st.cache_data(ttl=60" in text
    assert "def _load_backend_slow_snapshot" in text
    assert '"signals": list(reader.latest_signals())' in text
    assert '"broker_account": broker_account' in text
    assert '"heartbeats": list(reader.heartbeats())' in text
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


def test_v209_keeps_minute_discovery_and_moves_heavy_calibration_to_5m_lane() -> None:
    supervisor = _read(".github/workflows/ctrader-demo-auto-supervisor.yml")
    discovery = _read(".github/workflows/ctrader-demo-discovery-pipeline.yml")
    calibration = _read(".github/workflows/ctrader-demo-calibration-pipeline.yml")

    assert "discovery_check_seconds=60" in supervisor
    assert "calibration_cadence_seconds=300" in supervisor
    assert "SUPERVISOR_CALIBRATION_DISPATCH" in supervisor
    assert 'if [ "${cycle}" -eq 1 ]' in supervisor

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

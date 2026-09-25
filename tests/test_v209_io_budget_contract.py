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


def test_v209_reference_symbol_sync_skips_noop_writes() -> None:
    text = _read("src/fx_scanner/storage/supabase_operational.py")
    assert 'select("symbol,base_currency,quote_currency,pip_size,tier,active")' in text
    assert "if changed:" in text
    assert "unconditional UPSERT" in text


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

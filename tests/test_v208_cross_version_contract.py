from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_v203_remains_direction_agnostic_shadow_only() -> None:
    text = _read("src/fx_scanner/demo_xau_v203_volatility_shock_guard.py")
    assert 'CONTRACT = "XAU_VOLATILITY_SHOCK_GUARD_V203"' in text
    assert '"effective_execution_block": False' in text
    assert '"execution_influence": False' in text
    assert '"execution_authority": False' in text
    assert '"promotion_authority": False' in text
    assert '"direction_engine_influence": False' in text
    assert "current_unfinished_m5_excluded" in text


def test_v204_m5_watch_label_does_not_misrepresent_parent_zone_as_pocket() -> None:
    dashboard = _read("streamlit_app.py")
    v196 = _read("src/fx_scanner/demo_xau_m5_bidirectional_path_v196.py")

    assert "PRE-CONFIRMATION M5 **" not in dashboard
    assert "PARENT WATCH ZONE / PRE-M5" in dashboard
    assert "Belum ada M5 pocket aktual pada tahap ini." in dashboard
    assert "Candidate M5 pocket baru dibentuk" in dashboard
    assert "only called an M5 pocket after fresh M5 evidence exists" in v196
    assert "CANDIDATE_M5_POCKET" in v196
    assert "REFINED_M5_POCKET" in v196


def test_v205_latency_read_remains_bounded_and_narrow() -> None:
    text = _read("src/fx_scanner/demo_xau_strategy_latency_telemetry.py")
    assert "EVENT_LOOKBACK_HOURS = 48" in text
    assert '.in_("event_type", list(wanted))' in text
    assert '.select("observed_at,signal_key,event_type,accepted")' in text
    assert '.select("observed_at,signal_key,event_type,accepted,payload")' not in text


def test_v206_and_v207_database_hot_path_indexes_remain_declared() -> None:
    schema = _read("supabase/schemas/fx_core.sql")
    assert "signals_observed_at_desc_idx" in schema
    assert "FOREX_SCANNER_SIGNAL_QUERY_BUDGET_V206" in schema
    assert "broker_order_events_backend_event_account_observed_idx" in schema
    assert "FOREX_SCANNER_BROKER_EVENT_HOT_PATH_V207" in schema


def test_v208_recovers_only_stale_discovery_runs_and_adds_pipeline_heartbeat() -> None:
    supervisor = _read(".github/workflows/ctrader-demo-auto-supervisor.yml")
    discovery = _read(".github/workflows/ctrader-demo-discovery-pipeline.yml")

    assert "cancel_stale_discovery_runs()" in supervisor
    assert 'local workflow_file="ctrader-demo-discovery-pipeline.yml"' in supervisor
    assert "local stale_after_seconds=1800" in supervisor
    assert "/actions/runs/${run_id}/cancel" in supervisor
    assert "SUPERVISOR_DISCOVERY_STALE_CANCELLED" in supervisor
    assert "SUPERVISOR_DISCOVERY_STALE_CHECK_FAILED safety=FAIL_CLOSED" in supervisor
    assert "discovery_stale_seconds=1800" in supervisor
    assert supervisor.index("cancel_stale_discovery_runs\n            active_discovery=") < supervisor.index(
        'SUPERVISOR_DISCOVERY_DISPATCH'
    )

    assert (
        "python -m fx_scanner.demo_runtime_heartbeat "
        "ctrader_demo_discovery_pipeline SUCCESS"
    ) in discovery
    assert (
        "python -m fx_scanner.demo_runtime_heartbeat "
        "ctrader_demo_discovery_pipeline FAILED"
    ) in discovery
    assert "demo_execution_fresh_ready_handoff" not in discovery

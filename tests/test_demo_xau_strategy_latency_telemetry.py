from datetime import datetime, timedelta, timezone
from pathlib import Path

from fx_scanner.demo_xau_strategy_latency_telemetry import (
    EVENT_TYPE,
    STRATEGY_ACTIVATED_AT,
    STRATEGY_ID,
    build_latency_payload,
)

UTC = timezone.utc
ROOT = Path(__file__).resolve().parents[1]


def test_latency_payload_persists_explicit_active_strategy_identity():
    start = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)
    signal = {
        "id": "12345678-1234-5678-1234-567812345678",
        "run_id": "run-1",
        "observed_at": start.isoformat(),
        "symbol": "XAUUSD",
        "direction": "LONG",
        "state": "EXECUTION_READY",
        "final_score": 98.0,
        "setup_type": "TREND_CONTINUATION",
    }
    payload = build_latency_payload(
        signal,
        {
            "geometry_at": start + timedelta(seconds=2),
            "feature_snapshot_at": start + timedelta(seconds=3),
            "order_accepted_at": start + timedelta(seconds=17),
            "protection_verified_at": start + timedelta(seconds=18),
        },
    )
    assert EVENT_TYPE == "DEMO_XAU_STRATEGY_LATENCY_V2"
    assert STRATEGY_ACTIVATED_AT == datetime(2026, 9, 10, 7, 42, 49, tzinfo=UTC)
    assert payload["telemetry_version"] == 2
    assert payload["strategy_id"] == STRATEGY_ID == "IMPULSE_RETEST_V2"
    assert payload["strategy_activated_at"] == STRATEGY_ACTIVATED_AT.isoformat()
    assert payload["strategy_authority"] == "SOLE_DEMO_EXECUTION_STRATEGY"
    assert payload["signal_to_order_seconds"] == 17.0
    assert payload["order_to_protection_seconds"] == 1.0
    assert payload["execution_influence"] is False
    assert payload["m5_close_to_detection_seconds"] is None


def test_workflow_runs_xau_telemetry_best_effort_after_pair_discovery():
    workflow = (ROOT / ".github/workflows/ctrader-demo-discovery-pipeline.yml").read_text(encoding="utf-8")
    producer = "python -m fx_scanner.demo_execution_technical_producer"
    telemetry = "python -m fx_scanner.demo_xau_strategy_latency_telemetry"
    reconciler = "python -m fx_scanner.demo_closed_trade_reconciler"
    assert workflow.index(producer) < workflow.index(telemetry) < workflow.index(reconciler)
    block = workflow[workflow.index("- name: Persist XAU active strategy identity and latency telemetry"):workflow.index("- name: Reconcile cTrader closed DEMO outcomes")]
    assert "continue-on-error: true" in block
    assert "if: ${{ always() }}" in block


def test_telemetry_has_no_execution_path_and_filters_by_activation_time():
    source = (ROOT / "src/fx_scanner/demo_xau_strategy_latency_telemetry.py").read_text(encoding="utf-8")
    assert 'STRATEGY_ID = "IMPULSE_RETEST_V2"' in source
    assert '.gte("observed_at", STRATEGY_ACTIVATED_AT.isoformat())' in source
    assert '"v1_historical_rows_excluded_from_strategy_identity": True' in source
    assert '"execution_influence": False' in source
    assert "ExecutionRouter" not in source
    assert "demo_fresh_ready_handoff" not in source
    assert "build_broker_gateway" not in source

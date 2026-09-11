from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_supervisor_is_bounded_stateless_and_has_no_self_handoff() -> None:
    text = _read(".github/workflows/ctrader-demo-auto-supervisor.yml")

    assert 'cron: "*/5 * * * *"' in text
    assert "for cycle in" not in text
    assert "sleep 60" not in text
    assert "cadence_minutes=5" in text
    assert "universe=XAUUSD,EURUSD" in text
    assert "strategies=PAIR_SPECIFIC" in text
    assert "cancel-in-progress: false" in text
    assert "CTRADER_DEMO_SUPERVISOR_HANDOFF" not in text
    assert "dispatch_workflow ctrader-demo-auto-supervisor.yml" not in text
    assert "self_handoff=DISABLED" in text


def test_split_lanes_remain_fail_safe_and_discovery_never_executes() -> None:
    fast = _read(".github/workflows/ctrader-demo-auto-pipeline.yml")
    discovery = _read(".github/workflows/ctrader-demo-discovery-pipeline.yml")

    assert "cancel-in-progress: false" in fast
    assert "python -m fx_scanner.demo_execution_fast_candidate_producer" in fast
    assert "python -m fx_scanner.demo_execution_fresh_ready_handoff --limit 2" in fast
    assert "python -m fx_scanner.demo_structural_profit_protector" in fast
    assert 'CTRADER_DEMO_FAST_MAX_SYMBOLS: "2"' in fast

    assert "cancel-in-progress: false" in discovery
    assert "python -m fx_scanner.demo_execution_technical_producer" in discovery
    assert "python -m fx_scanner.demo_closed_trade_reconciler" in discovery
    assert "python -m fx_scanner.demo_trajectory_finalizer" in discovery
    assert "python -m fx_scanner.demo_normalized_calibration_runner incremental" in discovery
    assert "python -m fx_scanner.demo_normalized_calibration_runner adaptive-v2" in discovery
    assert "demo_execution_fresh_ready_handoff" not in discovery
    assert "demo_calibration_autotrade" not in discovery
    assert "ctrader-demo-order-smoke" not in discovery

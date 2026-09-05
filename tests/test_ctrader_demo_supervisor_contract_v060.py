from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_supervisor_keeps_bounded_cadence_and_self_handoffs() -> None:
    text = _read(".github/workflows/ctrader-demo-auto-supervisor.yml")

    assert "for cycle in $(seq 1 30)" in text
    assert "sleep 120" in text
    assert "((cycle - 1) % 3)" in text
    assert "cancel-in-progress: true" in text
    assert "CTRADER_DEMO_SUPERVISOR_HANDOFF" in text
    assert "dispatch_workflow ctrader-demo-auto-supervisor.yml" in text
    assert "self_handoff=ENABLED" in text


def test_split_lanes_remain_fail_safe_and_discovery_never_executes() -> None:
    fast = _read(".github/workflows/ctrader-demo-auto-pipeline.yml")
    discovery = _read(".github/workflows/ctrader-demo-discovery-pipeline.yml")

    assert "cancel-in-progress: false" in fast
    assert "python -m fx_scanner.demo_fast_candidate_producer" in fast
    assert "python -m fx_scanner.demo_calibration_autotrade --limit 10" in fast
    assert "python -m fx_scanner.demo_structural_profit_protector" in fast

    assert "cancel-in-progress: false" in discovery
    assert "python -m fx_scanner.demo_technical_producer" in discovery
    assert "python -m fx_scanner.demo_closed_trade_reconciler" in discovery
    assert "python -m fx_scanner.demo_trajectory_finalizer" in discovery
    assert "python -m fx_scanner.demo_incremental_calibration" in discovery
    assert "demo_calibration_autotrade" not in discovery
    assert "ctrader-demo-order-smoke" not in discovery

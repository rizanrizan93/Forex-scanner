from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_supervisor_keeps_bounded_one_minute_cadence_without_recursive_handoff() -> None:
    text = _read(".github/workflows/ctrader-demo-auto-supervisor.yml")

    assert "for cycle in $(seq 1 5)" in text
    assert "sleep 60" in text
    assert "fast_cadence_seconds=60" in text
    assert "maintenance_cadence_seconds=300" in text
    assert "discovery_check_seconds=60" in text
    assert "universe=XAUUSD" in text
    assert "universe=XAUUSD,EURUSD" not in text
    assert "strategies=XAU_V24_CHAMPION_DEMO_V1,XAU_M15_EMA_SMC_RECLAIM_V1" in text
    assert "cancel-in-progress: false" in text
    assert "authority=SCHEDULE_5M" in text
    assert "self_handoff=DISABLED" in text
    assert "CTRADER_DEMO_SUPERVISOR_HANDOFF" not in text
    assert "dispatch_workflow ctrader-demo-auto-supervisor.yml" not in text
    assert "workflow_run:" not in text
    assert "push:" in text
    assert '".github/workflows/ctrader-demo-auto-supervisor.yml"' in text
    assert '".github/workflows/ctrader-demo-auto-pipeline.yml"' in text
    assert '".github/workflows/ctrader-demo-xau-execution-lane.yml"' in text
    assert '".github/workflows/ctrader-demo-maintenance-pipeline.yml"' in text
    assert "push_kick=SUPERVISOR_EXECUTION_OR_MAINTENANCE_CHANGE" in text
    assert "head_sha=${GITHUB_SHA}" in text
    assert 'cron: "2,7,12,17,22,27,32,37,42,47,52,57 * * * 0-5"' in text
    assert "market_open_utc" in text
    assert "action=STOP" in text
    assert "calendar=FOREX_WEEK_24X5" in text
    assert '"${weekday}" -eq 7' in text
    assert '"${hour}" -ge 21' in text

    parsed = yaml.safe_load(text)
    schedules = parsed[True]["schedule"]
    assert all(len(item["cron"].split()) == 5 for item in schedules)


def test_split_lanes_remain_fail_safe_and_discovery_never_executes() -> None:
    fast = _read(".github/workflows/ctrader-demo-auto-pipeline.yml")
    discovery = _read(".github/workflows/ctrader-demo-discovery-pipeline.yml")

    assert "cancel-in-progress: false" in fast
    assert "python -m fx_scanner.demo_execution_fast_candidate_producer" not in fast
    assert "python -m fx_scanner.demo_xau_v24_champion_candidate_producer" in fast
    assert "python -m fx_scanner.demo_xau_m15_ema_smc_reclaim_candidate_producer" in fast
    assert "python -m fx_scanner.demo_execution_fresh_ready_handoff --limit 10" in fast
    assert "python -m fx_scanner.demo_five_core_time_exit" in fast
    assert "python -m fx_scanner.demo_structural_profit_protector" in fast
    assert 'CTRADER_DEMO_FAST_MAX_SYMBOLS: "1"' in fast
    assert 'CTRADER_DEMO_ALLOW_SAME_SYMBOL_STACKING: "1"' in fast
    assert 'CTRADER_DEMO_STACK_MIN_SCORE: "50.01"' in fast
    assert 'CTRADER_DEMO_MAX_SAME_SYMBOL_POSITIONS: "10"' in fast
    assert 'CTRADER_DEMO_MIN_STACK_SPACING_SECONDS: "0"' in fast
    assert 'CTRADER_DEMO_MAX_PORTFOLIO_RISK_PCT: "20.0"' in fast
    assert 'CTRADER_DEMO_ADAPTIVE_PROFIT_LOCK_ENABLED: "0"' in fast
    assert 'CTRADER_DEMO_STRUCTURAL_PROFIT_PROTECT_ENABLED: "0"' in fast

    assert "cancel-in-progress: false" in discovery
    assert "python -m fx_scanner.demo_xau_technical_producer" in discovery
    assert "python -m fx_scanner.demo_execution_technical_producer" not in discovery
    assert "python -m fx_scanner.demo_closed_trade_reconciler" in discovery
    assert "python -m fx_scanner.demo_trajectory_finalizer" in discovery
    assert "python -m fx_scanner.demo_normalized_calibration_runner incremental" in discovery
    assert "python -m fx_scanner.demo_normalized_calibration_runner adaptive-v2" in discovery
    assert "demo_execution_fresh_ready_handoff" not in discovery
    assert "demo_calibration_autotrade" not in discovery
    assert "ctrader-demo-order-smoke" not in discovery

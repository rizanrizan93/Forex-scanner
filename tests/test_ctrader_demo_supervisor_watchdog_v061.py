from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WATCHDOG = ROOT / ".github/workflows/ctrader-demo-auto-supervisor-watchdog.yml"


def test_watchdog_is_hourly_recovery_only_and_never_executes_lanes_directly() -> None:
    text = WATCHDOG.read_text()

    assert 'cron: "32 * * * 1-5"' in text
    assert "timeout-minutes: 70" in text
    assert "window_cycles=59" in text
    assert "cadence_seconds=60" in text
    assert "ctrader-demo-auto-supervisor.yml/dispatches" in text
    assert "authority=RECOVERY_ONLY execution_authority=NONE" in text
    assert "ctrader-demo-auto-pipeline.yml" not in text
    assert "ctrader-demo-discovery-pipeline.yml" not in text


def test_watchdog_preserves_weekday_24x5_and_active_supervisor_guard() -> None:
    text = WATCHDOG.read_text()

    assert "date -u +%u" in text
    assert 'if [ "${weekday}" -gt 5 ]' in text
    assert "active_supervisor_count" in text
    assert 'if [ "${active_supervisor}" -gt 0 ]' in text
    assert "action=NO_DISPATCH" in text
    assert "action=DISPATCHED" in text

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
    assert "ctrader-demo-auto-pipeline.yml" in text  # push-path only, never direct dispatch
    assert "ctrader-demo-discovery-pipeline.yml" not in text
    assert "dispatches\"" in text
    assert "/actions/workflows/ctrader-demo-auto-pipeline.yml/dispatches" not in text


def test_watchdog_preserves_weekday_24x5_and_active_supervisor_guard() -> None:
    text = WATCHDOG.read_text()

    assert "market_weekday_utc()" in text
    assert "date -u +%u" in text
    assert '[ "${weekday}" -le 5 ]' in text
    assert "if ! market_weekday_utc" in text
    assert "active_supervisor_count" in text
    assert 'if [ "${active_supervisor}" -gt 0 ]' in text
    assert "action=NO_DISPATCH" in text
    assert "action=DISPATCHED" in text


def test_watchdog_push_kick_tracks_control_plane_changes_and_sha() -> None:
    text = WATCHDOG.read_text()

    assert "push:" in text
    assert '".github/workflows/ctrader-demo-auto-supervisor-watchdog.yml"' in text
    assert '".github/workflows/ctrader-demo-auto-supervisor.yml"' in text
    assert '".github/workflows/ctrader-demo-auto-pipeline.yml"' in text
    assert "push_kick=WATCHDOG_SUPERVISOR_OR_AUTO_PIPELINE" in text
    assert "head_sha=${GITHUB_SHA}" in text

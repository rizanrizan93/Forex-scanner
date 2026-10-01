from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_dashboard_publisher_has_serialized_schedule_and_self_handoff() -> None:
    text = _read(".github/workflows/forexrizan-dashboard-bridge-v254.yml")
    assert 'cron: "3,33 * * * 0-5"' in text
    # V319 keeps the currently healthy publisher alive across main pushes; the
    # repo-aware watchdog handles stale/zombie recovery rather than cancelling
    # an active 64-minute publisher on every push.
    assert "cancel-in-progress: false" in text
    assert "actions: write" in text
    assert "for i in $(seq 1 64)" in text
    assert 'gh workflow run -R "${GITHUB_REPOSITORY}" forexrizan-dashboard-bridge-v254.yml --ref main' in text
    assert "FOREXRIZAN_DASHBOARD_PUBLISHER_SELF_HANDOFF_DISPATCHED" in text
    assert "market_open_utc()" in text


def test_standalone_publisher_is_serialized_and_self_handoff_only() -> None:
    text = _read(".github/workflows/rizan-xau-standalone-v253.yml")
    assert 'cron: "7,37 * * * 0-5"' in text
    assert "cancel-in-progress: true" in text
    assert "actions: write" in text
    assert "gh workflow run rizan-xau-standalone-v253.yml --ref main" in text
    assert "RIZAN_STANDALONE_PUBLISHER_SELF_HANDOFF_DISPATCHED" in text


def test_bridge_watchdog_can_recover_missed_publisher_schedule() -> None:
    text = _read(".github/workflows/forexrizan-dashboard-bridge-smoke.yml")
    assert 'cron: "8,18,28,38,48,58 * * * 0-5"' in text
    assert "actions: write" in text
    assert "Recover dashboard publisher when bridge is stale" in text
    assert "active_publishers" in text
    assert 'if [ "${active_publishers}" -eq 0 ]' in text
    assert "publisher already active; wait without cancelling/restarting it" in text
    assert "for attempt in range(1, 17)" in text
    assert "gh workflow run forexrizan-dashboard-bridge-v254.yml --ref main" in text


def test_canonical_xau_lane_refreshes_rizan_fast_handoff() -> None:
    text = _read(".github/workflows/ctrader-demo-xau-execution-lane.yml")
    assert "Execute fresh RIZAN prepared-path DEMO signal" in text
    assert "python -m fx_scanner.demo_xau_afic_fresh_ready_handoff" in text
    assert "RIZAN_PATH_HANDOFF_OUTCOME" in text


def test_v324_structural_and_micro_refresh_precede_slow_prepared_path() -> None:
    text = _read(".github/workflows/ctrader-demo-xau-execution-lane.yml")
    atlas = text.index("Refresh XAU Supply/Demand Atlas V182")
    micro = text.index("Build RIZAN Style Micro Handoff Confluence V322")
    legacy = text.index("Evaluate RIZAN prepared/confirmed path")
    assert atlas < micro < legacy
    assert "Tab 1/Tab 2 fresh" in text

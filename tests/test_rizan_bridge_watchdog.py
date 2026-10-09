import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("watchdog", Path("scripts/rizan_bridge_watchdog.py"))
watchdog = importlib.util.module_from_spec(spec)
spec.loader.exec_module(watchdog)


def test_healthy_publication_never_cancels_publisher():
    assert watchdog.recovery_action(60, [{"id": 1, "status": "in_progress", "run_age": 1000}]) == ("HEALTHY", [])


def test_old_snapshot_preserves_new_runner_startup():
    assert watchdog.recovery_action(900, [{"id": 1, "status": "in_progress", "run_age": 40}]) == ("WAIT_ACTIVE_PUBLISHER", [])


def test_missing_publisher_dispatches_recovery():
    assert watchdog.recovery_action(900, []) == ("DISPATCH", [])


def test_confirmed_stall_cancels_only_old_running_worker():
    active = [{"id": 1, "status": "in_progress", "run_age": 600},
              {"id": 2, "status": "queued", "run_age": 600},
              {"id": 3, "status": "in_progress", "run_age": 20}]
    assert watchdog.recovery_action(900, active) == ("RESTART", [1])


def test_api_or_timestamp_uncertainty_is_not_evidence_of_zombie():
    assert watchdog.recovery_action(None, [{"id": 1, "status": "in_progress", "run_age": 1000}]) == ("WAIT_ACTIVE_PUBLISHER", [])

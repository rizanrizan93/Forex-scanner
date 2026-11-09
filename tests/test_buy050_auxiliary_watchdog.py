"""Fail-closed BUY050 auxiliary watchdog regression tests."""
import importlib.util
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("buy050_aux", Path("scripts/buy050_auxiliary_watchdog.py"))
aux = importlib.util.module_from_spec(spec)
spec.loader.exec_module(aux)


class TestBuy050AuxiliaryWatchdog(unittest.TestCase):
    def test_shadow_and_event_must_be_distinct_readonly_feeds(self):
        self.assertEqual({f[0] for f in aux.FEEDS}, {"SHADOW", "EVENT"})
        self.assertNotEqual(aux.FEEDS[0][2], aux.FEEDS[1][2])

    def test_recent_completed_run_blocks_dispatch(self):
        self.assertEqual(aux.decide(3600, [{"status": "completed", "start_age": 250}]), "RECENT_ATTEMPT_BACKOFF")

    def test_existing_active_job_prevents_duplicate(self):
        for state in aux.ACTIVE:
            with self.subTest(state=state):
                self.assertEqual(aux.decide(3600, [{"status": state, "start_age": 1000}]), "PUBLISHER_ACTIVE")

    def test_aged_out_snapshot_dispatches_only_when_idle(self):
        self.assertEqual(aux.decide(3600, [{"status": "completed", "start_age": 1000}]), "DISPATCH_READONLY")

    def test_recent_snapshot_never_dispatches(self):
        self.assertEqual(aux.decide(50, []), "FRESH")

    def test_bad_run_history_never_dispatches(self):
        now = datetime(2026, 11, 9, 0, tzinfo=timezone.utc)
        payload = '{"read_only":true,"execution_authority":false,"as_of":"2026-11-08T22:00:00Z"}'
        with patch.object(aux, "gh", side_effect=[payload, "not-json"]) as gh:
            result = aux.inspect_one("rizanrizan93/Forex-scanner", now, aux.FEEDS[0])
        self.assertEqual(result, "UNVERIFIED")
        self.assertEqual(gh.call_count, 2)

    def test_missing_snapshot_with_recent_runner_backs_off(self):
        now = datetime(2026, 11, 9, 0, tzinfo=timezone.utc)
        history = '{"workflow_runs":[{"status":"completed","created_at":"2026-11-08T23:55:00Z"}]}'
        with patch.object(aux, "gh", side_effect=[ValueError("invalid"), history]) as gh:
            result = aux.inspect_one("rizanrizan93/Forex-scanner", now, aux.FEEDS[1])
        self.assertEqual(result, "RECENT_ATTEMPT_BACKOFF")
        self.assertEqual(gh.call_count, 2)


if __name__ == "__main__":
    unittest.main()

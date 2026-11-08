"""Watchdog safety tests: only recover missing publications, never send orders."""
import importlib.util
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("buy050_watch", Path("scripts/buy050_publication_watchdog.py"))
WATCH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(WATCH)


class PublicationWatchdogTests(unittest.TestCase):
    def test_fresh_suppresses_dispatch(self):
        self.assertEqual(WATCH.decide(200, []), "FRESH")

    def test_queued_run_suppresses_duplicate(self):
        self.assertEqual(WATCH.decide(1000, [{"status": "queued", "start_age": 999}]), "PUBLISHER_ACTIVE")

    def test_in_progress_suppresses_duplicate(self):
        self.assertEqual(WATCH.decide(1000, [{"status": "in_progress", "start_age": 999}]), "PUBLISHER_ACTIVE")

    def test_failed_recent_run_has_backoff(self):
        self.assertEqual(WATCH.decide(1100, [{"status": "completed", "start_age": 180}]), "RECENT_ATTEMPT_BACKOFF")

    def test_stale_no_publisher_dispatch(self):
        self.assertEqual(WATCH.decide(1100, [{"status": "completed", "start_age": 1200}]), "DISPATCH_READONLY")

    def test_unknown_age_requires_inspected_absence(self):
        self.assertEqual(WATCH.decide(None, []), "DISPATCH_READONLY")


if __name__ == "__main__":
    unittest.main()

"""R8-Q: causal availability semantics regression tests (research-only).

The current R8-G implementation measures age from bar close, whereas the
acquisition contract defines quote_age from bar close PLUS publication lag.
These tests document the difference; no market accuracy is inferred.
"""
import csv
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

def latest_eligible(open_times, event_utc, lag_seconds=120):
    return max((t for t in open_times
                if t+timedelta(seconds=60+lag_seconds)<=event_utc),
               default=None)

def causal_ages(end_open, event_utc, lag_seconds=120):
    bar_close=end_open+timedelta(minutes=1)
    availability=bar_close+timedelta(seconds=lag_seconds)
    return ((event_utc-bar_close).total_seconds(),
            (event_utc-availability).total_seconds())

class CausalQuoteAgeTests(unittest.TestCase):
    def test_bar_not_eligible_before_close_plus_lag(self):
        t=datetime(2020,1,2,12,0,tzinfo=timezone.utc)
        self.assertIsNone(latest_eligible([t],t+timedelta(seconds=179)))
        self.assertEqual(latest_eligible([t],t+timedelta(seconds=180)),t)
    def test_age_from_close_and_age_from_availability_differ(self):
        t=datetime(2020,1,2,12,0,tzinfo=timezone.utc)
        close_age,availability_age=causal_ages(t,t+timedelta(seconds=240))
        self.assertEqual(close_age,180)
        self.assertEqual(availability_age,60)
    def test_boundary_changes_coverage_at_300_seconds(self):
        t=datetime(2020,1,2,12,0,tzinfo=timezone.utc)
        event=t+timedelta(seconds=420)
        close_age,availability_age=causal_ages(t,event)
        self.assertEqual(close_age,360)
        self.assertEqual(availability_age,240)
        self.assertFalse(close_age<=300)
        self.assertTrue(availability_age<=300)
    def test_zero_lag_equivalence(self):
        t=datetime(2020,1,2,12,0,tzinfo=timezone.utc)
        self.assertEqual(*causal_ages(t,t+timedelta(minutes=5),0))

if __name__=="__main__":
    unittest.main()

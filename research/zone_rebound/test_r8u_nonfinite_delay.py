"""R8-U: synthetic adversarial tests for nonfinite time parameters.
Research only. No Dukascopy data, replay, or accuracy claims.
Run: python -m unittest discover -s research/zone_rebound -p 'test_r8u_nonfinite_delay.py'
"""
import unittest
from datetime import datetime, timedelta, timezone
from r8r_causal_availability_gate import causal_window

class NonfiniteTimeParameterTests(unittest.TestCase):
    def setUp(self):
        t = datetime(2020, 1, 2, 12, 0, tzinfo=timezone.utc)
        self.bars = [t + timedelta(minutes=i) for i in range(61)]
        self.event = t + timedelta(minutes=63)

    def test_reject_nonfinite_lag(self):
        for value in (float('nan'), float('inf'), -float('inf')):
            with self.subTest(value=str(value)), self.assertRaisesRegex(ValueError, 'BAD_DELAY'):
                causal_window(self.bars, self.event, lag_seconds=value)

    def test_reject_nonfinite_quote_age(self):
        for value in (float('nan'), float('inf'), -float('inf')):
            with self.subTest(value=str(value)), self.assertRaisesRegex(ValueError, 'BAD_DELAY'):
                causal_window(self.bars, self.event, max_age_seconds=value)

    def test_finite_boundary_unchanged(self):
        result = causal_window(self.bars, self.event, lag_seconds=120.0, max_age_seconds=300.0)
        self.assertEqual(result['status'], 'OK')
        self.assertEqual(result['age_seconds'], 0)
        self.assertTrue(all(result['windows'].values()))

if __name__ == '__main__':
    unittest.main()

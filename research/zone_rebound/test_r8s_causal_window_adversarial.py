"""R8-S adversarial R8-R causal-window tests; research-only, synthetic clock fixtures.
No vendor data or strategy accuracy is inferred from these tests.
"""
import unittest
from datetime import datetime, timedelta, timezone
from r8r_causal_availability_gate import causal_window

class CausalWindowAdversarialTests(unittest.TestCase):
    def setUp(self):
        self.t=datetime(2020,1,2,12,0,tzinfo=timezone.utc)
        self.bars=[self.t+timedelta(minutes=i) for i in range(61)]
    def test_exact_availability_boundary(self):
        r=causal_window(self.bars,self.t+timedelta(minutes=63))
        self.assertEqual(r["age_seconds"],0)
        self.assertTrue(all(r["windows"].values()))
    def test_one_second_before_availability_uses_earlier_bar(self):
        r=causal_window(self.bars,self.t+timedelta(minutes=63,seconds=-1))
        self.assertEqual(r["bar_open_utc"],self.bars[-2].isoformat())
    def test_missing_lookback_abstains_60m_only(self):
        bars=self.bars[:40]+self.bars[41:]
        r=causal_window(bars,self.t+timedelta(minutes=63))
        self.assertFalse(r["windows"][60])
        self.assertTrue(r["windows"][15])
    def test_quote_age_boundary(self):
        r=causal_window(self.bars,self.t+timedelta(minutes=68))
        self.assertEqual(r["age_seconds"],300)
        self.assertTrue(r["windows"][5])
        r=causal_window(self.bars,self.t+timedelta(minutes=68,seconds=1))
        self.assertFalse(r["windows"][5])
    @unittest.expectedFailure
    def test_non_minute_aligned_bar_open_rejected(self):
        # A shifted sequence is internally contiguous but violates UTC M1 open semantics.
        shifted=[x+timedelta(seconds=30) for x in self.bars]
        with self.assertRaisesRegex(ValueError,"BAR_NOT_MINUTE_ALIGNED"):
            causal_window(shifted,self.t+timedelta(minutes=63,seconds=30))
    @unittest.expectedFailure
    def test_invalid_window_rejected_even_when_no_bar_available(self):
        # Current early return bypasses window validation.
        with self.assertRaisesRegex(ValueError,"BAD_WINDOW"):
            causal_window(self.bars,self.t,windows=(0,5))
    @unittest.expectedFailure
    def test_empty_windows_rejected(self):
        # Current function can return UNAVAILABLE without any requested horizon.
        with self.assertRaisesRegex(ValueError,"BAD_WINDOW"):
            causal_window(self.bars,self.t+timedelta(minutes=63),windows=())

if __name__=="__main__":
    unittest.main()

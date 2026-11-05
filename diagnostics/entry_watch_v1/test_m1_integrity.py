"""Pure unit tests; no broker/VPS access or external dependencies."""
import unittest
from datetime import datetime, timezone
from m1_integrity import inspect, market_open, retry_windows, public_report

UTC = timezone.utc


def at(s):
    return datetime.fromisoformat(s.replace('Z', '+00:00'))


XAU = {'scheduleTimeZone': 'America/New_York', 'schedule': [
    {'startSecond': 64800, 'endSecond': 147540},
    {'startSecond': 151200, 'endSecond': 233940},
    {'startSecond': 237600, 'endSecond': 320340},
    {'startSecond': 324000, 'endSecond': 406740},
    {'startSecond': 410400, 'endSecond': 493080},
]}
BTC = {'scheduleTimeZone': 'America/New_York', 'schedule': [
    {'startSecond': 61200, 'endSecond': 147540},
    {'startSecond': 147600, 'endSecond': 233940},
    {'startSecond': 234000, 'endSecond': 320340},
    {'startSecond': 320400, 'endSecond': 406740},
    {'startSecond': 406800, 'endSecond': 493140},
]}


class IntegrityTests(unittest.TestCase):
    def test_new_york_dst_shift_xau_reopen(self):
        self.assertTrue(market_open(at('2026-10-26T22:00:00Z'), XAU))
        self.assertFalse(market_open(at('2026-11-02T22:00:00Z'), XAU))
        self.assertTrue(market_open(at('2026-11-02T23:00:00Z'), XAU))

    def test_market_close_not_false_gap(self):
        result = inspect('XAUUSD', [at('2026-11-04T21:58:00Z'),
                                    at('2026-11-04T23:01:00Z')], XAU)
        self.assertEqual(result['closed_missing'], 61)
        self.assertEqual(result['open_missing'], 1)
        self.assertEqual(result['strategy_missing'], 0)
        self.assertEqual(result['status'], 'OUTSIDE_STRATEGY_SESSION_M1_UNRESOLVED')

    def test_open_btc_gap_is_not_silently_synthetic(self):
        result = inspect('BTCUSD', [at('2026-10-29T14:41:00Z'),
                                     at('2026-10-29T14:44:00Z')], BTC)
        self.assertEqual(result['open_missing'], 2)
        self.assertEqual(result['strategy_missing'], 2)
        self.assertFalse(result['interpolation_used'])
        self.assertEqual(result['status'], 'STRATEGY_SESSION_M1_UNRESOLVED')

    def test_closed_btc_weekend(self):
        result = inspect('BTCUSD', [at('2026-10-30T20:58:00Z'),
                                     at('2026-11-01T22:00:00Z')], BTC)
        self.assertEqual(result['open_missing'], 0)
        self.assertTrue(result['closed_missing'] > 2800)

    def test_backfill_day_clustering_bounded(self):
        xs = [at('2026-11-03T22:03:00Z'), at('2026-11-03T22:04:00Z'),
              at('2026-11-04T22:03:00Z')]
        windows = retry_windows(xs)
        self.assertEqual(len(windows), 2)
        self.assertLessEqual((windows[0][1] - windows[0][0]).total_seconds(), 45 * 60)
        self.assertEqual(len(retry_windows(xs, max_days=1)), 1)

    def test_invalid_m1_alignment_rejected(self):
        with self.assertRaisesRegex(ValueError, 'INVALID_M1_TIMESTAMP_ALIGNMENT'):
            inspect('BTCUSD', [at('2026-10-29T14:41:30Z')], BTC)

    def test_no_bars_fail_closed(self):
        self.assertEqual(inspect('BTCUSD', [], BTC)['status'], 'NO_BROKER_BARS')

    def test_public_report_does_not_serialize_datetimes(self):
        x = inspect('BTCUSD', [at('2026-10-29T14:41:00Z'),
                               at('2026-10-29T14:44:00Z')], BTC)
        self.assertNotIn('open_missing_minutes', public_report(x))


if __name__ == '__main__':
    unittest.main()

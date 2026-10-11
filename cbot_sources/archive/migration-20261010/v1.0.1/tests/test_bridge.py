import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bridge'))
from server import Store, CONTRACTS, strict_load
from feeds import macro_point, ff_events, bls_events, category

class BridgeTests(unittest.TestCase):
    def test_durable_identity_cas_and_exclusive_lease(self):
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / 'state.sqlite')
            store = Store(path)
            key, lease = 'RZEU3:1237903:EURUSD', 'a' * 32
            self.assertEqual(store.acquire(key, lease), (0, None))
            with self.assertRaisesRegex(ValueError, 'LEASE_BUSY'):
                store.acquire(key, 'b' * 32)
            state = {'Schema': 1, 'ContractHash': CONTRACTS['RZEU3'], 'AccountNumber': 1237903,
                     'Symbol': 'EURUSD', 'Revision': 1, 'PendingLabel': 'prepared-before-order'}
            self.assertEqual(store.save(key, lease, 0, 1, state), 1)
            with self.assertRaisesRegex(ValueError, 'REVISION_CONFLICT'):
                store.save(key, lease, 0, 2, {**state, 'Revision': 2})
            with self.assertRaisesRegex(ValueError, 'STATE_IDENTITY_INVALID'):
                store.save(key, lease, 1, 2, {**state, 'Revision': 2, 'AccountNumber': 99})
            with self.assertRaisesRegex(ValueError, 'STATE_REVISION_NOT_INCREASING'):
                store.save(key, lease, 1, 1, state)
            store.db.close()
            recovered = Store(path)
            self.assertEqual(recovered.acquire(key, 'b' * 32), (1, state))
            recovered.leases[key] = ('b' * 32, 0)
            with self.assertRaisesRegex(ValueError, 'LEASE_EXPIRED'):
                recovered.touch(key, 'b' * 32)
            recovered.db.close()

    def test_nonfinite_rejected(self):
        with self.assertRaises(ValueError):
            strict_load('{"RiskBudget":NaN}')
        with self.assertRaises(ValueError):
            strict_load('{"RiskBudget":Infinity}')

    def test_macro_holiday_availability_and_stale(self):
        csv = b'DATE,DGS10\n2026-07-01,4.1\n2026-07-02,4.2\n'
        with self.assertRaisesRegex(ValueError, 'MACRO_STALE'):
            macro_point(csv, 'DGS10', datetime(2026, 7, 7, 3, 59, tzinfo=timezone.utc))
        point = macro_point(csv, 'DGS10', datetime(2026, 7, 7, 4, tzinfo=timezone.utc))
        self.assertAlmostEqual(point['Delta'], .1)
        self.assertEqual(point['AvailableUtc'], '2026-07-07T04:00:00+00:00')
        with self.assertRaisesRegex(ValueError, 'MACRO_STALE'):
            macro_point(csv, 'DGS10', datetime(2026, 7, 15, tzinfo=timezone.utc))

    def test_calendar_timezone_scope_and_old_week_rejection(self):
        now = datetime(2026, 10, 9, 12, tzinfo=timezone.utc)
        source = json.dumps([{'date': '2026-10-09T08:30:00-04:00', 'country': 'USD', 'title': 'Core CPI m/m'},
                             {'date': '2026-10-08T10:00:00-04:00', 'country': 'EUR', 'title': 'PPI'}]).encode()
        events, start, end = ff_events(source, now)
        self.assertEqual(events, [{'AtUtc': '2026-10-09T12:30:00+00:00', 'Category': 'CPI'}])
        with self.assertRaisesRegex(ValueError, 'FF_WEEK_MISMATCH'):
            ff_events(source, now+timedelta(days=7))
        with self.assertRaises(ValueError):
            ff_events(b'[]', now)
        ics = b'BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nDTSTART:20260101T133000Z\r\nSUMMARY:CPI\r\nEND:VEVENT\r\nBEGIN:VEVENT\r\nDTSTART:20261231T133000Z\r\nSUMMARY:Employment Situation\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n'
        self.assertEqual(len(bls_events(ics, start, end)), 2)
        with self.assertRaises(ValueError):
            bls_events(b'BEGIN:VCALENDAR\r\nVERSION:2.0\r\nEND:VCALENDAR\r\n', start, end)
        self.assertEqual(category('FOMC Statement'), 'FOMC')
        self.assertIsNone(category('Unrelated event'))

if __name__ == '__main__':
    unittest.main()

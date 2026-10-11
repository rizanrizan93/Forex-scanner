import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import feeds

sys.path.insert(0, str(Path(__file__).resolve().parent))
from server import Store, CONTRACTS, strict_load
from feeds import macro_point, ff_events, bls_events, category

class FeedTests(unittest.TestCase):
    def test_macro_holiday_availability_and_stale(self):
        csv = b'DATE,DGS10\n2026-07-01,4.1\n2026-07-02,4.2\n'
        with self.assertRaisesRegex(ValueError, 'MACRO_DELTA_MISSING'):
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

    def test_all_provider_failure_is_unhealthy_snapshot(self):
        with patch.object(feeds, 'fetch', side_effect=OSError('synthetic-unavailable')):
            result=feeds.snapshot(datetime(2026,10,9,12,tzinfo=timezone.utc))
        self.assertFalse(result['ForexFactoryOk']);self.assertFalse(result['BlsOk'])
        self.assertIsNone(result['Dgs10']);self.assertIsNone(result['Dfii10'])
        self.assertEqual(result['Events'],[]);self.assertTrue(result['Errors'])

    def test_malformed_macro_schema_rejected(self):
        with self.assertRaisesRegex(ValueError,'MACRO_SCHEMA_INVALID'):
            macro_point(b'bad,columns\n1,2\n','DGS10',datetime(2026,10,9,tzinfo=timezone.utc))

    def test_monitor_health_matches_freshness_and_coverage(self):
        from server import snapshot_ready
        import copy
        now=datetime(2026,10,9,12,tzinfo=timezone.utc)
        good=dict(ProducedUtc=now.isoformat(),CoverageFromUtc=(now-timedelta(hours=1)).isoformat(),CoverageToUtc=(now+timedelta(days=1)).isoformat(),ForexFactoryOk=True,BlsOk=True,Errors=[],Dgs10=dict(Delta=.1,AvailableUtc=(now-timedelta(days=1)).isoformat()),Dfii10=dict(Delta=-.1,AvailableUtc=(now-timedelta(days=1)).isoformat()),Events=[])
        self.assertTrue(snapshot_ready(good,now.timestamp()))
        for key,value in [('ProducedUtc',(now-timedelta(seconds=181)).isoformat()),('CoverageToUtc',(now+timedelta(minutes=494)).isoformat()),('Events',None),('BlsOk',False)]:
            self.assertFalse(snapshot_ready({**good,key:value},now.timestamp()))
        for value,available in [(float('inf'),now-timedelta(days=1)),(.1,now+timedelta(seconds=1)),(.1,now-timedelta(days=8))]:
            bad=copy.deepcopy(good);bad['Dgs10']=dict(Delta=value,AvailableUtc=available.isoformat())
            self.assertFalse(snapshot_ready(bad,now.timestamp()))

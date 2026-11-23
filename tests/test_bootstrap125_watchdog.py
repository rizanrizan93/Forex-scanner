import importlib.util
from pathlib import Path
import sys
import unittest
from datetime import timedelta
from test_cbot_v1_dashboard import sample,NOW

path=Path(__file__).resolve().parents[1]/'operations/bootstrap125_watchdog/watchdog.py'
from fx_scanner import cbot_v1_reliability
sys.modules['cbot_v1_reliability']=cbot_v1_reliability
spec=importlib.util.spec_from_file_location('v1watchdog',path)
watchdog=importlib.util.module_from_spec(spec);spec.loader.exec_module(watchdog)

class WatchdogTests(unittest.TestCase):
    def test_lost_heartbeat_alerts_even_with_active_bridge(self):
        p=sample();p['roles'][1]['lease_expires_at']=(NOW-timedelta(seconds=1)).isoformat()
        r=watchdog.check(p,NOW)
        self.assertEqual(r['event'],'V1_HEARTBEAT_ALERT')
        self.assertTrue(r['bridge_active']);self.assertFalse(r['automatic_recovery'])
    def test_stale_publisher_independently_alerted(self):
        self.assertEqual(watchdog.check(sample(),NOW+timedelta(seconds=31))['event'],'V1_HEARTBEAT_ALERT')
    def test_wrong_contract_and_duplicate_roles_rejected(self):
        p=sample();p['profile']='legacy'
        with self.assertRaises(ValueError):watchdog.check(p,NOW)
        p=sample();p['roles'][0]=p['roles'][1]
        with self.assertRaises(ValueError):watchdog.check(p,NOW)
    def test_current_traffic_never_grants_execution_permission(self):
        r=watchdog.check(sample(),NOW)
        self.assertEqual(r['event'],'V1_HEARTBEAT_OBSERVED')
        self.assertIsNone(r['execution_ready']);self.assertFalse(r['automatic_recovery'])

if __name__=='__main__':unittest.main()

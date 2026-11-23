"""P0 failure-injection tests of monitoring decisions; no LIVE side effects."""
import copy
import unittest
from datetime import timedelta
from test_cbot_v1_dashboard import sample, NOW
from fx_scanner.cbot_v1_dashboard import evaluate_snapshot

class ReliabilityTests(unittest.TestCase):
    def observe(self,p):
        result=evaluate_snapshot(p,now=NOW)['reliability']
        self.assertIsNone(result['execution_ready'])
        self.assertFalse(result['automatic_recovery'])
        for r in result['roles'].values():
            self.assertFalse(r['recovery_allowed'])
            self.assertIsNone(r['execution_ready'])
            self.assertNotIn(r['status'],('HEALTHY','STOPPED','DISCONNECTED','RECOVERING'))
        return result

    def expired(self):
        p=sample()
        for r in p['roles']:
            r.update(lease_active=False,lease_touched_at=(NOW-timedelta(minutes=1)).isoformat(),lease_expires_at=(NOW-timedelta(seconds=15)).isoformat())
        return p

    def test_01_websocket_disconnect_without_native_receipt_is_unverified(self):
        p=sample();p['roles'][0]['lease_active']=False
        r=self.observe(p);self.assertTrue(r['attention_required']);self.assertEqual(r['roles']['BOOTSTRAP']['bot_connected'],'UNVERIFIED')

    def test_02_bot_crash_and_expired_lease_does_not_assert_stopped(self):
        r=self.observe(self.expired());self.assertEqual({v['status'] for v in r['roles'].values()},{'STALE'})

    def test_03_bridge_restart_does_not_grant_execution_authority(self):
        p=sample();p['service_active']=False
        self.assertFalse(self.observe(p)['bridge_active'])
        p['service_active']=True
        self.assertTrue(self.observe(p)['bridge_active'])

    def test_04_missing_heartbeat_even_if_boolean_true_is_not_live(self):
        p=sample();p['roles'][1]['lease_touched_at']=None
        self.assertFalse(self.observe(p)['roles']['XAUUSD']['lease_active'])

    def test_05_expired_lease_overrides_active_boolean(self):
        p=sample();p['roles'][1]['lease_expires_at']=(NOW-timedelta(seconds=1)).isoformat()
        r=self.observe(p)['roles']['XAUUSD'];self.assertFalse(r['lease_active']);self.assertEqual(r['reason'],'LEASE_EXPIRED')

    def test_06_old_identity_reconnect_remains_closed(self):
        p=sample();p['roles'][2]['identity_ok']=False
        r=self.observe(p)['roles']['EURUSD'];self.assertFalse(r['lease_active']);self.assertEqual(r['status'],'UNKNOWN')

    def test_07_duplicate_role_inventory_rejected(self):
        p=sample();p['roles'][0]=copy.deepcopy(p['roles'][1])
        with self.assertRaises(ValueError):self.observe(p)

    def test_08_pending_order_or_intent_cannot_authorize_restart(self):
        p=sample();p['roles'][1].update(pending_intent=True,checkpoint_basket=True)
        self.observe(p)

    def test_09_checkpoint_without_instance_traffic_is_not_connected(self):
        r=self.observe(self.expired());self.assertTrue(r['attention_required'])
        self.assertTrue(all(v['bot_connected']=='UNVERIFIED' for v in r['roles'].values()))

    def test_10_active_service_broken_execution_path_no_false_healthy(self):
        p=sample();p['bridge']['observed_at']=(NOW-timedelta(seconds=31)).isoformat()
        r=self.observe(p);self.assertFalse(r['bridge_active']);self.assertTrue(r['attention_required'])

    def test_old_or_future_observation_cannot_hide_lease_loss(self):
        for seconds in (-31,6):
            p=sample();p['observed_at']=(NOW+timedelta(seconds=seconds)).isoformat()
            self.assertFalse(self.observe(p)['source_fresh'])

    def test_current_lease_is_only_recent_traffic_evidence(self):
        p=sample();before=copy.deepcopy(p);r=self.observe(p)
        self.assertEqual(p,before);self.assertFalse(r['attention_required'])
        self.assertTrue(all(v['status']=='LEASE_ACTIVE' for v in r['roles'].values()))

if __name__=='__main__':unittest.main()

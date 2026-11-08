"""BUY050 event audit regression tests, no broker/network or LIVE writes."""
import unittest
from datetime import datetime,timedelta,timezone

from scripts.watch_buy050_native_events import transition,identify
from scripts.merge_buy050_event_audit import merge,PROFILE
from fx_scanner.cbot_buy050_event_dashboard import evaluate_timeline

T=datetime(2026,11,9,0,0,tzinfo=timezone.utc)
def stamp(offset):
    return (T+timedelta(seconds=offset)).isoformat()
def state(sig=None,version=10):
    return {s:{"version":version,"signal":sig,"intent":False,"basket":False,
               "quarantine":False,"fault":False,"exit_pending":False,"origin":None}
            for s in ("XAUUSD","EURUSD","BTCUSD")}
def audit():
    return {
        "contract":"RIZAN_BUY050_EVENT_AUDIT_V1",
        "strategy":"P3_BUY050","profile_sha256":PROFILE,"read_only":True,
        "execution_authority":False,"execution_influence":False,
        "started_at":stamp(0),"ended_at":stamp(12),"samples":13,
        "failures":0,"max_interval_s":1,"start_state":state(),
        "end_state":state(),"events":[],"source":"VPS_SQLITE_READONLY_1S_SAMPLING",
        "terminal_journal_available":False,"broker_deals_verified":False
    }

class EventAuditTests(unittest.TestCase):
    def test_transition_is_not_broker_fill(self):
        before=state()
        after=state(stamp(5),11)
        after["XAUUSD"]["basket"]=True
        events=transition(before,after,stamp(6))
        types={e["event"] for e in events}
        self.assertEqual(types,{"SIGNAL_RECORDED","BASKET_STATE_ACTIVE"})
        self.assertTrue(all("FILLED" not in x for x in types))
        self.assertTrue(all("account" not in str(e).lower() for e in events))

    def test_reject_old_and_foreign_bridge_keys(self):
        self.assertEqual(identify("TPX_13bfa137:1237903:XAUUSD"),("XAUUSD","1237903"))
        self.assertIsNone(identify("RZXRC1:1237903:XAUUSD"))
        self.assertIsNone(identify("TPX_13bfa137:1234567:XAUUSD"))

    def test_merge_never_infers_rejection_from_empty_broker(self):
        b={"contract":"RIZAN_BUY050_BROKER_OPEN_V1","read_only":True,
           "execution_authority":False,"deals_history_checked":False,
           "observed_at":stamp(13),"open_position_evidence":[]}
        out=merge(audit(),broker=b,now=T+timedelta(seconds=20))
        self.assertEqual(out["events"],[])
        self.assertFalse(out["broker_deals_verified"])
        self.assertFalse(out["continuous_coverage_confirmed"])

    def test_gap_signal_is_inferred_not_exact(self):
        prior=merge(audit(),now=T+timedelta(seconds=20))
        curr=audit()
        curr["started_at"]=stamp(50)
        curr["ended_at"]=stamp(60)
        curr["start_state"]=state(stamp(40),20)
        curr["end_state"]=state(stamp(40),20)
        result=merge(curr,previous=prior,now=T+timedelta(seconds=65))
        self.assertEqual(result["unobserved_gap_s"],38.0)
        self.assertEqual(len([r for r in result["events"] if r["event"]=="SIGNAL_CHANGED_DURING_GAP"]),3)
        self.assertFalse(result["continuous_coverage_confirmed"])

    def test_broker_open_position_is_positive_evidence_only(self):
        a=audit()
        b={"contract":"RIZAN_BUY050_BROKER_OPEN_V1","read_only":True,
           "execution_authority":False,"deals_history_checked":False,
           "observed_at":stamp(13),
           "open_position_evidence":[{"symbol":"XAUUSD","signal_at":stamp(-60),
               "open_positions":1,"sl_protected":True,"tp_protected":False}]}
        out=merge(a,broker=b,now=T+timedelta(seconds=20))
        e=[e for e in out["events"] if e["event"]=="BROKER_OPEN_POSITION_OBSERVED"]
        self.assertEqual(len(e),1)
        self.assertEqual(e[0]["protection"],"PROTECTION_INCOMPLETE")

    def test_public_view_rejects_claims_of_deals_coverage(self):
        p=merge(audit(),now=T+timedelta(seconds=20))
        self.assertTrue(evaluate_timeline(p,now=T+timedelta(seconds=30))["fresh"])
        p["broker_deals_verified"]=True
        with self.assertRaises(ValueError):
            evaluate_timeline(p,now=T+timedelta(seconds=30))

    def test_broker_confirmed_deal_and_order_statuses_with_provenance(self):
        a=audit()
        b={"contract":"RIZAN_BUY050_BROKER_OPEN_V1","read_only":True,
           "execution_authority":False,"deals_history_checked":True,
           "orders_history_checked":True,
           "history_from":stamp(-86400),"history_to":stamp(12),
           "observed_at":stamp(13),"open_position_evidence":[],
           "execution_evidence":[
               {"symbol":"XAUUSD","signal_at":stamp(-60),
                "observed_at":stamp(10),"event":"BROKER_DEAL_FILLED"},
               {"symbol":"EURUSD","signal_at":stamp(-20),
                "observed_at":stamp(11),"event":"BROKER_ORDER_REJECTED"},
           ]}
        out=merge(a,broker=b,now=T+timedelta(seconds=20))
        self.assertTrue(out["broker_deals_verified"])
        self.assertTrue(out["broker_orders_history_complete"])
        kinds={x["event"] for x in out["events"]}
        self.assertEqual(kinds,{"BROKER_DEAL_FILLED","BROKER_ORDER_REJECTED"})
        self.assertTrue(evaluate_timeline(out,now=T+timedelta(seconds=20))["fresh"])

    def test_broker_future_event_fails_closed(self):
        b={"contract":"RIZAN_BUY050_BROKER_OPEN_V1","read_only":True,
           "execution_authority":False,"deals_history_checked":True,
           "orders_history_checked":True,
           "history_from":stamp(-86400),"history_to":stamp(12),
           "observed_at":stamp(13),"open_position_evidence":[],
           "execution_evidence":[
               {"symbol":"XAUUSD","signal_at":stamp(10),
                "observed_at":stamp(600),"event":"BROKER_DEAL_FILLED"},
           ]}
        with self.assertRaises(ValueError):
            merge(audit(),broker=b,now=T+timedelta(seconds=20))

    def test_raw_state_never_reaches_display_json(self):
        a=audit()
        a["start_state"]["XAUUSD"]["account"]=1237903
        out=merge(a,now=T+timedelta(seconds=20))
        self.assertNotIn("1237903",str(out))
        self.assertEqual(set(out["end_state"]["XAUUSD"]),{"signal","version"})

if __name__=="__main__":
    unittest.main()

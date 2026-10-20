import unittest
import numpy as np
import pandas as pd
from book_adapter import Book, decision_features
from evaluate import simulate, generate_events
from zone_overlay import Zone, annotate

def message(t, typ='snapshot', b=None, a=None, seq=5):
    return {'ts':t, 'type':typ, 'data': {'b': b if b is not None else [['100','2']],
            'a':a if a is not None else [['101','1']], 'seq':seq, 'u':2}}

class Tests(unittest.TestCase):
    def test_zone_venue_and_future_guards(self):
        z=Zone('a','XAUUSD','FP',100,1,99,101)
        t=np.arange(100)*1000;x=np.full(100,.5)
        self.assertEqual(annotate(z,60000,'GC','CME',t,x)['status'],'INSTRUMENT_OR_VENUE_MISMATCH')
        z=Zone('a','BTCUSDT','Bybit',61000,1,99,101)
        self.assertEqual(annotate(z,60000,'BTCUSDT','Bybit',t,x)['status'],'INVALID_OR_FUTURE_ZONE')

    def test_zone_unchanged_and_no_probability_invented(self):
        z=Zone('a','BTCUSDT','Bybit',100,1,99,101)
        r=annotate(z,60000,'BTCUSDT','Bybit',np.arange(100)*1000,np.full(100,.5))
        self.assertEqual((r['zone_low'],r['zone_high']),(99,101))
        self.assertIsNone(r['calibrated_reversal_probability'])
        self.assertFalse(r['execution_influence'])

    def test_actual_repo_feature_prefix_is_causal(self):
        import importlib.util
        from pathlib import Path
        p=Path(__file__).parent/'origin'/'repo'/'reversal_zones.py'
        spec=importlib.util.spec_from_file_location('repo_test',p)
        mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
        idx=pd.date_range('2024-01-01',periods=100*60,freq='min',tz='UTC',name='timestamp')
        price=100+np.sin(np.arange(len(idx))*.01)
        df=pd.DataFrame({'open':price,'high':price+.1,'low':price-.1,'close':price+.01},index=idx)
        a=mod.closed_features(df)
        cut=idx[70*60];df.loc[df.index>=cut,['open','high','low','close']]+=500
        b=mod.closed_features(df)
        pd.testing.assert_frame_equal(a.loc[a.index<=cut],b.loc[b.index<=cut])

    def test_snapshot_delta_delete_and_new_snapshot(self):
        b = Book(); b.apply(message(1000))
        b.apply(message(1100, 'delta', [['100','0'],['99','3']], [], 6))
        self.assertEqual(b.sample(1200)[:2], (99,101))
        b.apply(message(1300, seq=7))
        self.assertNotIn(990, b.bids)

    def test_missing_snapshot_stale_and_crossed_reject(self):
        b = Book(); self.assertFalse(b.apply(message(1000,'delta')))
        b.apply(message(1000)); self.assertIsNone(b.sample(3001))
        b.apply(message(2000,'delta',[['102','1']],[],6))
        self.assertIsNone(b.sample(2000))

    def test_reordering_blocks_until_snapshot(self):
        b = Book(); b.apply(message(1000))
        self.assertFalse(b.apply(message(900,'delta',[],[],4)))
        self.assertIsNone(b.sample(1100))
        b.apply(message(1200, seq=10)); self.assertIsNotNone(b.sample(1200))

    def test_features_strictly_pre_decision(self):
        t=np.arange(100)*1000; x=np.full(100,.5)
        a=decision_features(t,x,60000,1)
        x[60:]=-1
        self.assertEqual(a,decision_features(t,x,60000,1))
        self.assertEqual(a['feature_last_ms'],59000)

    def test_missing_feature_window_not_filled(self):
        t=np.arange(100)*1000;x=np.full(100,.5);x[:10]=np.nan
        self.assertFalse(decision_features(t,x,60000,1)['feature_valid'])

    def test_latest_feature_missing_rejects_even_if_window_is_full(self):
        t=np.arange(100)*1000;x=np.full(100,.5);x[59]=np.nan
        self.assertFalse(decision_features(t,x,60000,1)['feature_valid'])

    def test_stress_spread_fixed_cost_monotonic(self):
        t=np.arange(2000)*1000
        q=np.column_stack([np.full(2000,100.),np.full(2000,100.01)])
        q[100:]=[102,102.01]
        e={'decision_ms':1000,'side':1,'stop':99,'atr':1}
        r=simulate(e,t,q)
        self.assertEqual(r['reason'],'target')
        self.assertGreater(r['net_R_1x'],r['net_R_1.5x'])
        self.assertGreater(r['net_R_1.5x'],r['net_R_2x'])
        self.assertAlmostEqual(r['entry_px'],100.01)

    def test_quote_gap_is_censored(self):
        t=np.arange(2000)*1000
        q=np.column_stack([np.full(2000,100.),np.full(2000,100.01)])
        q[5]=np.nan
        r=simulate({'decision_ms':1000,'side':1,'stop':99,'atr':1},t,q)
        self.assertEqual(r['status'],'quote_gap_censored')

    def test_first_touch_ignores_future_bar_ohlc(self):
        at=pd.Timestamp('2024-01-02',tz='UTC');start=at.value//1_000_000
        t=start+np.arange(900)*1000;mid=np.full(900,100.);mid[10]=98.
        m=pd.DataFrame([dict(open=100,high=105,low=98,close=100,count=900,atr=1,usable=True,
                            history_usable=True,hi16=104,lo16=99)],index=[at])
        a=[x for x in generate_events(t,mid,m) if x['cohort']=='exante_touch']
        m.loc[at,['high','low','close','count','usable']]=[500,1,400,50,False]
        b=[x for x in generate_events(t,mid,m) if x['cohort']=='exante_touch']
        self.assertEqual(a,b)
        self.assertEqual(a[0]['decision_ms'],start+11000)

if __name__=='__main__':unittest.main(verbosity=2)

import unittest
from unittest.mock import patch
import numpy as np,pandas as pd
from challenger import upstream,born_zones,context,flow_arrays,absorption,reclaim,simulate,phase_times
from book_adapter import Book

class Tests(unittest.TestCase):
    def fixture(self):
        idx=pd.date_range('2024-01-01',periods=45,freq='h',tz='UTC',name='timestamp')
        p=100+np.sin(np.arange(45))*.05
        f=pd.DataFrame({'open':p,'high':p+.2,'low':p-.2,'close':p+.01,'count':3600,'atr':1.},index=idx)
        f.iloc[25,f.columns.get_indexer(['open','high','low','close'])]=[100,102.2,99.9,102]
        f.iloc[30,f.columns.get_indexer(['open','high','low','close'])]=[100,100.1,97,97.2]
        return f

    def test_births_not_survivorship_filtered(self):
        f=self.fixture();mod=upstream();cut=f.index[26]
        early=mod.detect(f.reset_index().to_dict('records'),'H1',cut)
        self.assertTrue(early)
        ids={x['zone_id'] for x in born_zones(f)}
        self.assertTrue(set(z['zone_id'] for z in early)<=ids)
        full=mod.detect(f.reset_index().to_dict('records'),'H1',f.index[-1]+pd.Timedelta(hours=1))
        self.assertTrue(set(z['zone_id'] for z in early)-{z['zone_id'] for z in full})

    def test_original_zone_prefix_ignores_future(self):
        f=self.fixture();mod=upstream();cut=f.index[27]
        a=mod.detect(f.reset_index().to_dict('records'),'H1',cut)
        f.loc[f.index>=cut,['open','high','low','close']]+=500
        b=mod.detect(f.reset_index().to_dict('records'),'H1',cut)
        self.assertEqual(a,b)

    def test_h4_context_ignores_unfinished(self):
        idx=pd.date_range('2024-01-01',periods=3,freq='4h',tz='UTC')
        f=pd.DataFrame({'high':[101,102,50],'low':[99,100,1]},index=idx)
        ms=(idx[2]+pd.Timedelta(minutes=5)).value//1_000_000
        self.assertEqual(context(f,ms),'BULL')

    def test_late_trade_not_exposed_at_exchange_time(self):
        start=pd.Timestamp('2024-02-01',tz='UTC').value//1_000_000;t=start+np.arange(4000)*1000
        z={'available_us':np.array([(start+10000)*1000]),'exchange_us':np.array([(start+1000)*1000]),
           'price':np.array([100.]),'amount':np.array([2.]),'side':np.array([-1])}
        with patch('challenger.np.load',return_value=z):f=flow_arrays('2024-02-01',t)
        self.assertEqual(f['sell15'][14],200.)
        # A trade arriving at10s cannot enter any bin at/before10s.
        with patch('challenger.np.load',return_value={**z,'available_us':np.array([(start+20000)*1000])}):g=flow_arrays('2024-02-01',t)
        self.assertEqual(g['sell15'][14],0.)

    def test_no_tape_cannot_claim_absorption(self):
        r,why=absorption({'touch_ix':0},np.arange(10)*1000,np.ones((10,5)),np.ones(10),{'ready':np.zeros(10,bool)})
        self.assertIsNone(r);self.assertEqual(why,'NO_TAPE_WARMUP_AT_TOUCH')

    def test_reclaim_only_after_m1_close(self):
        t=np.arange(2000)*1000;q=np.column_stack([np.full(2000,100.),np.full(2000,100.1)]);mid=q.mean(axis=1)
        idx=pd.to_datetime([0,60000,120000],unit='ms',utc=True)
        bars={'M1':pd.DataFrame({'close':[99.,99.,101.]},index=idx)}
        e={'side':1,'stop':98,'proximal':100};signal={'signal_ms':121000,'signal_ix':121}
        result,_=reclaim(e,signal,t,q,mid,bars)
        self.assertEqual(result,180000)

    def test_stress_does_not_change_spread_or_fill(self):
        t=np.arange(8000)*1000;q=np.column_stack([np.full(8000,100.),np.full(8000,100.1)])
        q[20:]=[102,102.1];e={'side':1,'stop':99,'atr':1}
        r=simulate(e,0,t,q,30)
        self.assertEqual(r['reason'],'TARGET');self.assertEqual(r['entry_px'],100.1)
        self.assertGreater(r['net_R_1x'],r['net_R_1.5x']);self.assertGreater(r['net_R_1.5x'],r['net_R_2x'])

    def test_gap_censored_and_right_edge_not_forced(self):
        t=np.arange(8000)*1000;q=np.column_stack([np.full(8000,100.),np.full(8000,100.1)]);q[10]=np.nan
        self.assertEqual(simulate({'side':1,'stop':99,'atr':1},0,t,q,30)['status'],'QUOTE_GAP_CENSORED')
        self.assertEqual(simulate({'side':1,'stop':99,'atr':1},t[-100],t,q,30)['status'],'RIGHT_CENSORED')

    def test_snapshot_required(self):
        b=Book();m={'ts':0,'type':'delta','data':{'b':[['100','1']],'a':[['101','1']],'seq':2,'u':2}}
        self.assertFalse(b.apply(m));self.assertIsNone(b.sample(0))

    def test_horizon_units_are_explicit_minutes(self):
        t=np.arange(8000)*1000;q=np.column_stack([np.full(8000,100.),np.full(8000,100.1)])
        e={'side':1,'stop':95,'atr':3}
        a=simulate(e,0,t,q,30);b=simulate(e,0,t,q,120)
        self.assertEqual(a['duration_s'],1800)
        self.assertEqual(b['duration_s'],7200)

    def test_waiting_reclaim_cannot_ignore_stop(self):
        t=np.arange(2000)*1000;q=np.column_stack([np.full(2000,100.),np.full(2000,100.1)]);q[140]=[97,97.1]
        idx=pd.to_datetime([120000],unit='ms',utc=True);bars={'M1':pd.DataFrame({'close':[101.]},index=idx)}
        result,why=reclaim({'side':1,'stop':98,'proximal':100},{'signal_ms':121000,'signal_ix':121},t,q,q.mean(axis=1),bars)
        self.assertIsNone(result);self.assertEqual(why,'INVALIDATED_OR_GAP_BEFORE_RECLAIM')

    def test_original_m15_then_m5_sequence_uses_closed_candles(self):
        t=np.arange(4000)*1000;q=np.column_stack([np.full(4000,101.),np.full(4000,101.1)])
        idx=pd.to_datetime([0,300000,600000,900000],unit='ms',utc=True);idx.name='timestamp'
        m5=pd.DataFrame({'open':[100,100,100,101],'high':[101,101,101,103],
                         'low':[99.5,99.5,99.5,100.5],'close':[100,100,100,102]},index=idx)
        mi=pd.to_datetime([0,900000],unit='ms',utc=True);mi.name='timestamp'
        m15=pd.DataFrame({'open':[99.5,102],'high':[102,103],'low':[99,101],'close':[101.5,102]},index=mi)
        e={'zone_id':'z','side':1,'available_ms':0,'low':99,'high':100,'stop':98,'touch_ms':60000,'touch_ix':60}
        result=phase_times(e,t,q,q.mean(axis=1),{'M5':m5,'M15':m15})
        self.assertTrue(result)
        self.assertEqual(result[0]['observed_ms'],1200000)
        self.assertEqual(result[0]['m15_closed_ms'],900000)
        self.assertEqual(result[0]['m5_closed_ms'],1200000)

if __name__=='__main__':unittest.main(verbosity=2)

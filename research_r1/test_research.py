import unittest,numpy as np,pandas as pd
from replay import simulate
from signals import features,generate
from macro_models import availability_join,DataUnavailable
class ExecutionTests(unittest.TestCase):
 def sim(self,bid,ask=None,side=1,limit=0,islimit=0,initial=10000.,dist=1.,expiry=900000,ts=None):
  ts=np.array(ts if ts is not None else np.arange(len(bid))*1000+100000,dtype=np.int64)
  s=np.array([[100000,100000+expiry,10000000,side,islimit,limit,dist,2.]])
  bid=np.array(bid,dtype=float);ask=bid+.2 if ask is None else np.array(ask,float)
  return simulate(ts,bid,ask,s,initial,initial,0.,1.,0.,6.,False,initial)
 def test_buy_uses_ask_and_sell_uses_bid(self):
  t,*_=self.sim([100,100]);self.assertAlmostEqual(t[0,4],100.2);self.assertAlmostEqual(t[0,9],-.26*t[0,8])
  t,*_=self.sim([100,100],side=-1);self.assertAlmostEqual(t[0,4],100.);self.assertAlmostEqual(t[0,9],-.26*t[0,8])
 def test_gap_stop_fills_at_quote(self):
  t,*_=self.sim([100,98]);self.assertAlmostEqual(t[0,5],98.);self.assertEqual(t[0,14],1)
 def test_limit_not_filled_by_bid_only(self):
  t,*_=self.sim([99.9,99.8],[100.1,100.],limit=99.95,islimit=1);self.assertEqual(len(t),0)
 def test_minimum_lot_skipped(self):
  t,*_=self.sim([100,100],initial=100,dist=10);self.assertEqual(len(t),0)
 def test_limit_expiry(self):
  t,*_=self.sim([100,99],[100.2,99.2],limit=99.5,islimit=1,expiry=500,ts=[100000,101000]);self.assertEqual(len(t),0)
 def test_floating_dd_exceeds_closed_dd(self):
  t,b,p,dd,_=self.sim([100,100.8,99.5,100.5],dist=2);self.assertGreater(dd,0);self.assertGreater(dd,max(0,(10000-b)/10000))
 def test_tp_gap_does_not_create_phantom_equity_peak(self):
  t,b,p,dd,_=self.sim([100,200]);self.assertAlmostEqual(p,b);self.assertAlmostEqual(t[0,5],102.2)
 def test_strict_closed_bar_signal_and_prefix_invariance(self):
  rng=np.random.default_rng(3);n=1200;c=1800+np.cumsum(rng.normal(0,1,n));idx=pd.date_range('2020-01-01',periods=n,freq='5min',tz='UTC')
  b=pd.DataFrame({'open':c-.2,'high':c+.8,'low':c-.8,'close':c,'bid_close':c-.1,'ask_close':c+.1,'spread':.2,'ticks':10,'max_gap_ms':1000},index=idx)
  for setup in ['MOMENTUM','SWEEP_MSS_FVG','OPENING_BREAKOUT','NY_CONTINUATION','TREND_FVG']:
   a=generate(features(b),'ASIA_FULL',setup,2.);partial=generate(features(b.iloc[:1000]),'ASIA_FULL',setup,2.)
   a=a[a.index<idx[1000]]
   pd.testing.assert_frame_equal(a,partial)
   self.assertTrue((a.signal_ms==(a.index+pd.Timedelta(minutes=5)).as_unit('ms').asi8).all())
 def test_macro_future_release_cannot_join_early(self):
  d=pd.DataFrame({'decision_at':pd.to_datetime(['2025-01-02T02:00Z','2025-01-02T03:00Z'])});o=pd.DataFrame({'available_at':pd.to_datetime(['2025-01-02T02:30Z']),'value':[4.3]})
  r=availability_join(d,o);self.assertTrue(pd.isna(r.value.iloc[0]));self.assertEqual(r.value.iloc[1],4.3)
 def test_unknown_macro_release_rejected(self):
  d=pd.DataFrame({'decision_at':pd.to_datetime(['2025-01-02T02:00Z'])});o=pd.DataFrame({'available_at':[pd.NaT],'value':[4.3]})
  with self.assertRaises(DataUnavailable):availability_join(d,o)
if __name__=='__main__':unittest.main(verbosity=2)

import sys
from pathlib import Path
import numpy as np,pandas as pd
from fx_scanner.reversal_families_v2 import GRID,SHAPE,LOCAL_SHAPE,CONFIGURATIONS,features,events,filter_events,rsi
from fx_scanner.reversal_zones import normalize_bars
sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
import research_reversal_families_v2 as r

def fixture():
 n=70*1440;t=pd.date_range('2020-01-01',periods=n,freq='min',tz='UTC');rng=np.random.default_rng(91);c=1500+np.cumsum(rng.normal(0,.2,n));o=np.r_[c[0],c[:-1]]
 return pd.DataFrame(dict(timestamp=t,open=o,high=np.maximum(o,c)+.1,low=np.minimum(o,c)-.1,close=c))

def test_grid_and_twenty_families():
 assert len(GRID['family'])==20 and len(set(GRID['family']))==20
 assert CONFIGURATIONS==20_000_000 and np.prod(LOCAL_SHAPE)==1_000_000

def test_prefix_and_midnight_causality():
 raw=fixture();cut=pd.Timestamp('2020-03-05T00:00Z');a=features(normalize_bars(raw));raw.loc[raw.timestamp>=cut,['open','high','low','close']]+=1000;b=features(normalize_bars(raw));pd.testing.assert_frame_equal(a.loc[:cut],b.loc[:cut])

def test_all_family_events_are_typed_and_known():
 f=features(normalize_bars(fixture()))
 for family in GRID['family']:
  for side in [1,-1]:
   e=events(f,side,family)
   assert np.isfinite(e[['level','atr5','adr20','retest']].to_numpy()).all()
   assert e.index.is_monotonic_increasing
   if family.startswith('M15_'):assert np.all(e.index.minute%15==0)

def simulate(low=99.9,high=100.2,opening=100.,retest=99.):
 t=np.arange(12*3600,21*3600,60,dtype=np.int64)
 return r.simulate(t,np.full(len(t),opening),np.full(len(t),high),np.full(len(t),low),np.array([0]),np.array([98.]),np.array([1.]),np.array([30.]),np.array([retest]),1)

def test_retest_unfilled_not_counted_as_trade_or_replaced():
 rr,ss,risk,ft=simulate();assert np.all(ss[0,1]!=1) and (ss[0,1]==-7).any()
 days=np.array([1,1],np.int64);returns=np.zeros((2,2,5,5,5,3));status=np.ones((2,2,5,5,5,3),np.int8);status[0]=-7;returns[1]=3
 out=r.statistics(days,np.zeros(2,np.int64),np.ones((2,5),bool),np.zeros(2,np.int64),np.zeros(2,np.int64),np.ones(2,np.int64)*2,returns,status,np.ones((2,2,5,5,5)),np.ones(2)*30)
 assert out[0,0,0,0,0,0,0,0,2,0]==0 and out[0,0,0,0,0,0,0,0,2,14]==1

def test_stop_first_and_adverse_gap_fills():
 rr,ss,_,_=simulate(low=90.,high=140.);assert ss[0,0,0,4,0,1]==-1 and rr[0,0,0,4,0,1]<-1

def test_intrabar_retest_cannot_use_earlier_high_for_tp():
 t=np.arange(12*3600,21*3600,60,dtype=np.int64);op=np.full(len(t),100.);h=np.full(len(t),100.);l=np.full(len(t),100.);h[0]=130.;l[0]=99.;op[1:]=99.
 rr,ss,_,_=r.simulate(t,op,h,l,np.array([0]),np.array([98.]),np.array([1.]),np.array([30.]),np.array([99.]),1)
 assert ss[0,1,0,0,0,1]!=1

def test_rsi_monotone_values_and_phase_filter():
 x=pd.Series(np.arange(50,dtype=float));assert rsi(x,7).iloc[-1]==100.
 e=pd.DataFrame({'strength_bin':[4,4],'confirm_0':[True,True],'session':[1,1],'phase_minute':[10,100],'regime_bin':[0,0]})
 c={k:v[0] for k,v in GRID.items()};c['session_utc']=6;c['session_phase']='FIRST_60';assert filter_events(e,c).tolist()==[True,False]

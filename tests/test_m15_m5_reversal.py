import importlib.util
from pathlib import Path
import numpy as np
import pandas as pd
from fx_scanner.m15_m5_reversal import CONFIGURATIONS,SHAPE,features,events
from fx_scanner.reversal_zones import normalize_bars
spec=importlib.util.spec_from_file_location('m15m5',Path(__file__).parents[1]/'scripts/research_m15_m5_reversal.py')
r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)

def frame():
 t=pd.date_range('2020-02-10T12:15Z',periods=8,freq='5min')
 f=pd.DataFrame(index=t)
 for c in ['open','high','low','close']:f[c]=100.
 for c in ['seed_open','seed_high','seed_low','seed_close','seed_atr','seed_adr20','seed_slope','seed_anchor_1_PREV_D1']:f[c]=np.nan
 f.loc[t[0],['seed_open','seed_high','seed_low','seed_close','seed_atr','seed_adr20','seed_slope','seed_anchor_1_PREV_D1']]=[99.,102.,98.,101.,2.,10.,.1,100.]
 return f

def test_one_million():assert CONFIGURATIONS==1_000_000 and np.prod(SHAPE)==1_000_000

def test_m15_seed_requires_later_displacement_not_touch():
 f=frame();f.loc[f.index[0],['open','close']]=[102.,105.]
 assert events(f,1,'PREV_D1',.05).empty
 f.loc[f.index[2],['open','close']]=[101.,103.]
 e=events(f,1,'PREV_D1',.05)
 assert len(e)==1 and e.index[0]==f.index[2]
 assert e.level.iloc[0]==98. and e.seed_time.iloc[0]==f.index[0]

def test_confirmation_expires_and_empty_labels_work():
 f=frame();f.loc[f.index[-1],['open','close']]=[101.,103.]
 e=events(f,1,'PREV_D1',.05);assert e.empty
 m=normalize_bars(pd.DataFrame({'timestamp':pd.date_range('2020-02-10T12:00Z',periods=60,freq='min'),'open':100.,'high':101.,'low':99.,'close':100.}))
 ee,(rr,ss,risk)=r.labelled(m,e,1);assert len(ee)==0

def test_seed_not_reclaiming_is_rejected():
 f=frame();f.loc[f.index[0],'seed_close']=99.;f.loc[f.index[1],['open','close']]=[101.,103.]
 assert events(f,1,'PREV_D1',0).empty

def test_feature_and_event_prefix_causality():
 t=pd.date_range('2020-01-01',periods=35*1440,freq='min',tz='UTC');rng=np.random.default_rng(7)
 c=1500+np.cumsum(rng.normal(0,.15,len(t)));o=np.r_[c[0],c[:-1]]
 raw=pd.DataFrame(dict(timestamp=t,open=o,high=np.maximum(o,c)+.2,low=np.minimum(o,c)-.2,close=c))
 cut=pd.Timestamp('2020-02-01T12:00Z');a=features(normalize_bars(raw));raw.loc[raw.timestamp>=cut,['open','high','low','close']]+=1000
 b=features(normalize_bars(raw));pd.testing.assert_frame_equal(a.loc[:cut],b.loc[:cut])
 ea=events(a.loc[:cut],1,'PREV_D1',.05);eb=events(b.loc[:cut],1,'PREV_D1',.05);pd.testing.assert_frame_equal(ea,eb)

def test_stats_projection_shape():
 d=np.array([1],np.int64);bin=np.array([4],np.int64)
 rr=np.ones((1,3));ss=np.ones((1,3),np.int8)
 out=r.first_valid_stats(d,bin,np.array([0]),np.array([0]),np.array([2]),rr,ss,np.ones(1),np.ones(1),4.,np.ones(1)*4.)
 assert out[:,:2,:1,:,:,0].shape==SHAPE[6:] and out[0,1,0,0,2,0]==1

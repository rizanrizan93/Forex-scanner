import importlib.util,sys
from pathlib import Path
import numpy as np,pandas as pd
from fx_scanner.h4_d1_reversal import CONFIGURATIONS,SHAPE,LOCAL_SHAPE,h4_zones,features,events,GRID,filter_events
from fx_scanner.reversal_zones import normalize_bars
sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
import research_h4_d1_reversal as r

def h4_fixture(n=25):
 t=pd.date_range('2020-01-01',periods=n,freq='4h',tz='UTC',name='timestamp')
 return pd.DataFrame(dict(open=100.,high=101.,low=99.,close=100.2),index=t)

def test_grid_20m_streams_2m():
 assert CONFIGURATIONS==20_000_000 and np.prod(SHAPE)==20_000_000
 assert np.prod(LOCAL_SHAPE)==2_000_000

def test_pivot_delay_no_backdating():
 f=h4_fixture();f.loc[f.index[5],'low']=90.;z=h4_zones(f)
 assert z.loc[f.index[6],'z_1_H4_PIVOT_2_low']!=90.
 assert z.loc[f.index[7],'z_1_H4_PIVOT_2_low']==90.
 assert z.loc[f.index[7],'z_1_H4_PIVOT_2_formed']==f.index[7].value/3.6e12

def test_ob_created_on_bos_displacement_and_invalidated():
 f=h4_fixture();f.loc[f.index[18],['open','close','high','low']]=[100.8,100.,101.,99.5]
 f.loc[f.index[19],['open','close','high','low']]=[100.,105.,105.2,99.9]
 f.loc[f.index[20],['open','close','high','low']]=[105.,98.,105.1,97.9]
 z=h4_zones(f)
 assert pd.isna(z.loc[f.index[18],'z_1_H4_OB_3_low'])
 assert z.loc[f.index[19],'z_1_H4_OB_3_low']==99.5
 assert z.loc[f.index[19],'z_1_H4_OB_3_high']==100.8
 assert z.loc[f.index[19],'z_1_H4_OB_3_formed']==f.index[19].value/3.6e12
 assert pd.isna(z.loc[f.index[20],'z_1_H4_OB_3_low'])

def test_h4_d1_prefix_causality():
 n=70*1440;t=pd.date_range('2020-01-01',periods=n,freq='min',tz='UTC');rng=np.random.default_rng(73);c=1500+np.cumsum(rng.normal(0,.1,n));o=np.r_[c[0],c[:-1]]
 raw=pd.DataFrame(dict(timestamp=t,open=o,high=np.maximum(o,c)+.1,low=np.minimum(o,c)-.1,close=c));cut=t[-3000]
 a=features(normalize_bars(raw));raw.loc[raw.timestamp>=cut,['open','high','low','close']]+=1000
 b=features(normalize_bars(raw));pd.testing.assert_frame_equal(a.loc[:cut],b.loc[:cut])
 # D1 at M5 close midnight uses the previously known daily close, not just-ended day.
 stamp=pd.Timestamp('2020-03-05T00:00Z');assert a.loc[stamp,'z_1_D1_PREVIOUS_formed']<stamp.value/3.6e12

def test_censored_first_claim_and_unknown_ineligible_skip():
 days=np.array([1,1],np.int64);wick=np.zeros((2,5),np.int64);flags=np.ones((2,5),bool)
 ret=np.ones((2,5,5,4,3));status=np.ones((2,5,5,4,3),np.int8);risk=np.ones((2,5,5,4));status[0]=-9
 out=r.statistics(days,wick,np.zeros(2,np.int64),np.zeros(2,np.int64),flags,np.zeros(2,np.int64),ret,status,risk,np.ones(2)*10)
 assert out[0,0,0,0,0,0,0,0,0]==0 and out[0,0,0,0,0,0,0,0,13]==1
 status[0]=-8;out=r.statistics(days,wick,np.zeros(2,np.int64),np.zeros(2,np.int64),flags,np.zeros(2,np.int64),ret,status,risk,np.ones(2)*10)
 assert out[0,0,0,0,0,0,0,0,0]==1

def test_confirmation_modes_wick_filters_and_source_config():
 rows=pd.DataFrame({'confirm_4':[True,False],'wick_4':[3,4],'age':[12,12],'session':[1,1],'regime_bin':[0,0]})
 idx=(0,2,0,0,0,0,3,1,1,4,1);cfg={k:v[i] for (k,v),i in zip(GRID.items(),idx)}
 assert filter_events(rows,cfg).tolist()==[True,False]
 assert cfg['zone_source']=='H4_OB_12' and cfg['confirmation']=='M15_SWEEP'

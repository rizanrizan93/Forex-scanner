"""RIZAN XAU H1/H4 R2 causal research features; NO broker/order dependencies.

Input M1 bars are stamped at minute OPEN UTC. H1/H4 signals are computed at
the completed timeframe close; execution proxy enters next M1 OPEN.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from research.zone_rebound.h1h4_direction_r1 import validate_m1, completed_bars

MINUTE=60_000_000_000
FEATURES=[
    'tf_atr','tf_rsi','tf_adx','tf_di','tf_body','tf_upper_wick','tf_lower_wick',
    'tf_close_location','tf_vol_ratio','tf_ema20_dev','tf_ema50_dev',
    'tf_ema20_slope','tf_ema50_slope','tf_prior_high','tf_prior_low',
    'tf_return1','tf_return2','tf_return3','tf_return6','tf_return12',
    'h1_rsi','h1_adx','h1_di','h1_body','h1_upper_wick','h1_lower_wick',
    'h1_ema20_dev','h1_ema20_slope','h1_return1','h1_return3','h1_return6',
    'h4_rsi','h4_adx','h4_di','h4_ema20_dev','h4_ema20_slope',
    'h4_return1','h4_return3','h4_return6','h4_prior_high','h4_prior_low',
    'session_sin','session_cos','dow_sin','dow_cos',
]
META=['timestamp','year','timeframe','complete','gross_forward_usd','source_close_utc']
SOURCE='HISTDATA_PUBLIC_M1_NOT_FP_MARKETS_EXECUTABLE'
EXECUTION_AUTHORITY=False
EXECUTION_INFLUENCE=False

def _rsi(close:pd.Series,n:int=14)->pd.Series:
    delta=close.diff()
    up=delta.clip(lower=0).ewm(alpha=1/n,adjust=False,min_periods=n).mean()
    down=(-delta.clip(upper=0)).ewm(alpha=1/n,adjust=False,min_periods=n).mean()
    return (100-100/(1+up/down)).where((up+down)!=0,50)

def _features_for(f:pd.DataFrame)->pd.DataFrame:
    c=f.close;h=f.high;l=f.low;o=f.open;prev=c.shift(1)
    tr=pd.concat([h-l,(h-prev).abs(),(l-prev).abs()],axis=1).max(axis=1)
    atr=tr.ewm(alpha=1/14,adjust=False,min_periods=14).mean()
    up=h.diff();down=-l.diff()
    plus=up.where((up>down)&(up>0),0.).ewm(alpha=1/14,adjust=False,min_periods=14).mean()/atr
    minus=down.where((down>up)&(down>0),0.).ewm(alpha=1/14,adjust=False,min_periods=14).mean()/atr
    dx=(100*(plus-minus).abs()/(plus+minus)).where((plus+minus)!=0,0)
    adx=dx.ewm(alpha=1/14,adjust=False,min_periods=14).mean()
    ema20=c.ewm(span=20,adjust=False,min_periods=20).mean()
    ema50=c.ewm(span=50,adjust=False,min_periods=50).mean()
    denom=atr.replace(0,np.nan)
    rng=(h-l).replace(0,np.nan)
    out=pd.DataFrame(index=f.index)
    out['atr']=atr
    out['rsi']=_rsi(c)/100
    out['adx']=adx/100
    out['di']=(plus-minus)*100
    out['body']=(c-o)/denom
    out['upper_wick']=(h-pd.concat([o,c],axis=1).max(axis=1))/denom
    out['lower_wick']=(pd.concat([o,c],axis=1).min(axis=1)-l)/denom
    out['close_location']=(c-l)/rng
    out['vol_ratio']=atr/atr.rolling(100,min_periods=60).median().replace(0,np.nan)
    out['ema20_dev']=(c-ema20)/denom
    out['ema50_dev']=(c-ema50)/denom
    out['ema20_slope']=(ema20-ema20.shift(3))/denom
    out['ema50_slope']=(ema50-ema50.shift(3))/denom
    out['prior_high']=(c-h.shift(1).rolling(20,min_periods=20).max())/denom
    out['prior_low']=(c-l.shift(1).rolling(20,min_periods=20).min())/denom
    for k in (1,2,3,6,12):
        out[f'return{k}']=(c-c.shift(k))/denom
    return out.replace([np.inf,-np.inf],np.nan)

def _join_asof(src:pd.DataFrame,idx:pd.DatetimeIndex,prefix:str,max_age_hours:float)->pd.DataFrame:
    vals=src.reindex(idx,method='ffill').copy()
    times=pd.Series(src.index,index=src.index).reindex(idx,method='ffill')
    ages=(pd.Series(idx,index=idx)-times).dt.total_seconds()/3600
    vals=vals.where(ages.le(max_age_hours),np.nan)
    vals.index=idx
    return vals.add_prefix(prefix+'_')

def make_features(m1:pd.DataFrame,year:int,timeframe:int)->pd.DataFrame:
    if timeframe not in (60,240):raise ValueError('ONLY_H1_H4')
    d=validate_m1(m1);h1=completed_bars(d,60);h4=completed_bars(d,240)
    tf=h1 if timeframe==60 else h4
    idx=tf.index[tf.index.year==year]
    a=_features_for(tf).reindex(idx)
    b=_join_asof(_features_for(h1),idx,'h1',2)
    c=_join_asof(_features_for(h4),idx,'h4',8)
    cols={}
    for k in ('atr','rsi','adx','di','body','upper_wick','lower_wick','close_location',
              'vol_ratio','ema20_dev','ema50_dev','ema20_slope','ema50_slope','prior_high',
              'prior_low','return1','return2','return3','return6','return12'):
        cols['tf_'+k]=a[k]
    for k in ('rsi','adx','di','body','upper_wick','lower_wick','ema20_dev',
              'ema20_slope','return1','return3','return6'):
        cols['h1_'+k]=b['h1_'+k]
    for k in ('rsi','adx','di','ema20_dev','ema20_slope','return1','return3',
              'return6','prior_high','prior_low'):
        cols['h4_'+k]=c['h4_'+k]
    loc=idx.tz_convert('Asia/Jakarta')
    minutes=loc.hour.to_numpy()*60+loc.minute.to_numpy()
    day=loc.dayofweek.to_numpy()
    cols['session_sin']=np.sin(2*np.pi*minutes/1440)
    cols['session_cos']=np.cos(2*np.pi*minutes/1440)
    cols['dow_sin']=np.sin(2*np.pi*day/7)
    cols['dow_cos']=np.cos(2*np.pi*day/7)
    features=pd.DataFrame(cols,index=idx)
    assert set(features.columns)==set(FEATURES)
    # A signal at t is only possible at the M1 open of t. No future bar is a feature.
    timestamps=d.index.asi8
    locs=np.searchsorted(timestamps,idx.asi8)
    valid_start=locs<len(timestamps)
    safe=np.minimum(locs,len(timestamps)-1)
    valid_start &= timestamps[safe]==idx.asi8
    end=locs+timeframe-1
    valid_end=end<len(timestamps)
    safe_end=np.minimum(end,len(timestamps)-1)
    valid_end &= timestamps[safe_end]==idx.asi8+(timeframe-1)*MINUTE
    gaps=np.r_[0,np.cumsum(np.diff(timestamps)!=MINUTE)]
    complete=valid_start & valid_end & (gaps[safe_end]-gaps[safe]==0)
    entry=d.open.to_numpy()[safe]
    exit_=d.close.to_numpy()[safe_end]
    gross=np.where(complete,exit_-entry,np.nan)
    # Require stable and sufficiently complete past features, but never future outcomes.
    # Not all features need be finite; the trained models have an imputer.
    ready=np.isfinite(features['tf_atr'])&np.isfinite(features['h4_rsi'])
    ready &= np.isfinite(features['h1_rsi']) & (features['tf_atr']>0)
    features=features.loc[ready].copy()
    features.insert(0,'timestamp',features.index.astype('int64')//MINUTE)
    features.insert(1,'year',year)
    features.insert(2,'timeframe',timeframe)
    features.insert(3,'complete',complete[ready])
    features.insert(4,'gross_forward_usd',gross[ready])
    features.insert(5,'source_close_utc',features.index.strftime('%Y-%m-%dT%H:%M:%SZ'))
    return features.reset_index(drop=True)

def synthetic_tape(n:int=60*240)->pd.DataFrame:
    t=pd.date_range('2024-01-01',periods=n,freq='min',tz='UTC')
    x=2000+np.arange(n)*.006+1.8*np.sin(np.arange(n)/90)
    return pd.DataFrame({'open':x,'high':x+.2,'low':x-.2,'close':x},index=t)

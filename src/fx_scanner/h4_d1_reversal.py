"""Causal H4 zones/D1 regimes for scanner-only reversal research."""
from __future__ import annotations
import math
import numpy as np
import pandas as pd
from .reversal_zones import closed_features
from .daily_reversal import COSTS,MIN_RR,MIN_ADR_FRACTION
CONTRACT='RIZAN_XAU_H4_D1_REVERSAL_20M_V1'
GRID={'side':[1,-1],'zone_source':['H4_OB_3','H4_OB_6','H4_OB_12','H4_PIVOT_2','H4_PIVOT_3','H4_PIVOT_5','H4_RANGE_6','H4_RANGE_12','H4_RANGE_24','D1_PREVIOUS'],
'padding_atr4':[0.,.025,.05,.1,.2],'stop_extension_atr':[.05,.1,.2,.35,.5],
 'target_adr_fraction':[.25,.35,.5,.75,1.],'horizon_minutes':[120,240,360,480],
 'wick_fraction':[0.,.2,.35,.5,.65],'regime':['ANY','ALIGNED','OPPOSED','FLAT'],
 'max_age_hours':[12,24,48,96,192],'confirmation':['TOUCH','M5_RECLAIM','M15_RECLAIM','M5_SWEEP','M15_SWEEP'],
 'session_utc':[0,6,12,18]}
SHAPE=tuple(len(v) for v in GRID.values());CONFIGURATIONS=math.prod(SHAPE)
LOCAL_SHAPE=(SHAPE[0],1)+SHAPE[2:]


def h4_zones(h4):
    """OB known only on displacement/BOS close; pivots known right-bars later."""
    out=h4.copy();prev=out.close.shift()
    out['atr4']=pd.concat([out.high-out.low,(out.high-prev).abs(),(out.low-prev).abs()],axis=1).max(axis=1).rolling(14).mean()
    arr=out[['open','high','low','close','atr4']].to_numpy();hours=out.index.asi8/3.6e12
    for side in [1,-1]:
        for source in GRID['zone_source'][:-1]:
            lo=np.full(len(out),np.nan);hi=lo.copy();formed=lo.copy();active=None
            for i,(op,high,low,cl,atr) in enumerate(arr):
                if active is not None and side*(cl-(active[0] if side==1 else active[1]))<0:active=None
                fresh=None
                if source.startswith('H4_OB_'):
                    n=int(source.split('_')[-1])
                    if i>=max(n,3) and np.isfinite(atr):
                        bos=cl>arr[i-3:i,1].max() if side==1 else cl<arr[i-3:i,2].min()
                        if bos and side*(cl-op)>=.8*atr:
                            for j in range(i-1,max(-1,i-n-1),-1):
                                if side*(arr[j,3]-arr[j,0])<0:
                                    fresh=(arr[j,2],max(arr[j,0],arr[j,3]),hours[i]) if side==1 else (min(arr[j,0],arr[j,3]),arr[j,1],hours[i]);break
                elif source.startswith('H4_PIVOT_'):
                    n=int(source.split('_')[-1]);j=i-n
                    if j>=n:
                        series=arr[j-n:i+1,2 if side==1 else 1]
                        extreme=arr[j,2 if side==1 else 1]
                        pivot=extreme== (series.min() if side==1 else series.max()) and np.sum(series==extreme)==1
                        if pivot:fresh=(extreme,extreme,hours[i])
                elif source.startswith('H4_RANGE_'):
                    n=int(source.split('_')[-1])
                    if i>=n-1:
                        extreme=arr[i-n+1:i+1,2].min() if side==1 else arr[i-n+1:i+1,1].max()
                        # Formation is the latest actual equal extreme, not reset every bar.
                        vals=arr[i-n+1:i+1,2 if side==1 else 1];j=i-n+1+np.flatnonzero(vals==extreme)[-1]
                        fresh=(extreme,extreme,hours[j])
                if fresh is not None:
                    distal=fresh[0] if side==1 else fresh[1]
                    if side*(cl-distal)>=0:active=fresh
                if active is not None:lo[i],hi[i],formed[i]=active
            for suffix,values in [('low',lo),('high',hi),('formed',formed)]:out[f'z_{side}_{source}_{suffix}']=values
    return out


def features(m1):
    f=closed_features(m1);agg={'open':'first','high':'max','low':'min','close':'last'}
    h4=m1.resample('4h',label='right',closed='left').agg(agg)
    h4=h4.loc[m1.close.resample('4h',label='right',closed='left').count()>=180]
    hz=h4_zones(h4)
    daily=m1.resample('1D',label='right',closed='left').agg(agg)
    daily=daily.loc[m1.close.resample('1D',label='right',closed='left').count()>=900].copy()
    daily['adr20']=(daily.high-daily.low).rolling(20).mean()
    ema20=daily.close.ewm(span=20,adjust=False,min_periods=20).mean();ema50=daily.close.ewm(span=50,adjust=False,min_periods=50).mean()
    daily['d1_regime']=np.where((daily.close>ema50)&(ema20>ema20.shift(3)),1,np.where((daily.close<ema50)&(ema20<ema20.shift(3)),-1,0))
    daily.loc[ema50.isna(),'d1_regime']=np.nan
    for side,col in [(1,'low'),(-1,'high')]:
        daily[f'z_{side}_D1_PREVIOUS_low']=daily[col];daily[f'z_{side}_D1_PREVIOUS_high']=daily[col];daily[f'z_{side}_D1_PREVIOUS_formed']=daily.index.asi8/3.6e12
    keys=pd.DataFrame({'key':f.index-pd.Timedelta(minutes=5)},index=f.index)
    for frame,cols in [(hz,['atr4']+[c for c in hz if c.startswith('z_')]),(daily,['adr20','d1_regime']+[c for c in daily if c.startswith('z_')])]:
        mapped=pd.merge_asof(keys.reset_index(),frame[cols].reset_index().rename(columns={'timestamp':'key'}),on='key',direction='backward').set_index('timestamp')
        f=pd.concat([f,mapped[cols]],axis=1)
    m15=m1.resample('15min',label='right',closed='left').agg(agg)
    m15=m15.loc[m1.close.resample('15min',label='right',closed='left').count()==15]
    for c in agg:f['m15_'+c]=m15[c].reindex(f.index)
    # Last 15 minutes structural extreme, known at signal close for all modes.
    f['recent_low']=m1.low.rolling('15min',min_periods=15).min().reindex(f.index-pd.Timedelta(minutes=1)).to_numpy()
    f['recent_high']=m1.high.rolling('15min',min_periods=15).max().reindex(f.index-pd.Timedelta(minutes=1)).to_numpy()
    return f


def events(f,side,source,padding):
    low=f[f'z_{side}_{source}_low']-padding*f.atr4;high=f[f'z_{side}_{source}_high']+padding*f.atr4
    formed=f[f'z_{side}_{source}_formed'];age=f.index.asi8/3.6e12-formed
    touch=(f.low<=high)&(f.high>=low)
    proximal=high if side==1 else low;distal=low if side==1 else high
    reclaim=touch&(side*(f.close-proximal)>=0)&(side*(f.close-f.open)>0)
    m15_touch=(f.m15_low<=high)&(f.m15_high>=low)&(formed<=f.index.asi8/3.6e12-.25)
    m15_reclaim=m15_touch&(side*(f.m15_close-proximal)>=0)&(side*(f.m15_close-f.m15_open)>0)
    sweep=reclaim&((f.low<low) if side==1 else (f.high>high))
    m15_sweep=m15_reclaim&((f.m15_low<low) if side==1 else (f.m15_high>high))
    remaining=20*60+55-(f.index.hour*60+f.index.minute)
    mask=(age>=0)&(age<=192)&(f.atr>0)&(f.atr4>0)&(f.adr20>0)&f.d1_regime.notna()&(remaining>=120)&(touch|m15_reclaim)
    e=f.loc[mask,['close','atr','adr20','year','session']].copy()
    e['level']=np.minimum(low,f.recent_low)[mask] if side==1 else np.maximum(high,f.recent_high)[mask]
    e['zone_low']=low[mask];e['zone_high']=high[mask];e['age']=age[mask]
    e['age_bin']=np.searchsorted(GRID['max_age_hours'],e.age,side='left')
    e['regime_bin']=np.where(side*f.d1_regime[mask]>0,0,np.where(side*f.d1_regime[mask]<0,1,2))
    for i,c in enumerate([touch,reclaim,m15_reclaim,sweep,m15_sweep]):e['confirm_'+str(i)]=c[mask].astype(bool)
    def wick(o,h,l,c):
        span=(h-l).replace(0,np.nan)
        return (np.minimum(o,c)-l)/span if side==1 else (h-np.maximum(o,c))/span
    w5=wick(f.open,f.high,f.low,f.close);w15=wick(f.m15_open,f.m15_high,f.m15_low,f.m15_close)
    for i,w in enumerate([w5,w5,w15,w5,w15]):e['wick_'+str(i)]=np.clip(np.searchsorted(GRID['wick_fraction'],w[mask],side='right')-1,0,4)
    return e.loc[e.level.notna()]


def config(idx):return {k:v[i] for (k,v),i in zip(GRID.items(),idx)}


def filter_events(rows,cfg):
    c=GRID['confirmation'].index(cfg['confirmation']);reg=GRID['regime'].index(cfg['regime'])
    return (rows['confirm_'+str(c)])&(rows['wick_'+str(c)]>=GRID['wick_fraction'].index(cfg['wick_fraction']))&(rows.age<=cfg['max_age_hours'])&(rows.session==cfg['session_utc']//6)&((rows.regime_bin==reg-1) if reg else True)

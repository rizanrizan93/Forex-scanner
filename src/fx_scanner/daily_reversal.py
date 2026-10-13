"""Independent scanner research: daily/session liquidity sweep and reclaim."""
from __future__ import annotations
import math
import numpy as np
import pandas as pd
from .reversal_zones import closed_features

CONTRACT="RIZAN_XAU_DAILY_ANCHOR_REVERSAL_NET_V1"
GRID={
    "side":[1,-1],
    "zone_source":["PREV_D1","PREV_2D","ASIA_00_06","EUROPE_06_12","H4_RANGE_6"],
    "sweep_depth_atr":[0.,.025,.05,.1,.2],
    "stop_extension_atr":[.05,.1,.2,.35,.5],
    "target_adr_fraction":[.25,.35,.5,.75,1.],
    "horizon_minutes":[120,240,360,480],
    "wick_fraction":[0.,.2,.35,.5,.65],
    "trend":["ANY","ALIGNED","OPPOSED","FLAT"],
    "approach_atr":[0.,.25,.5,1.,1.5],
    "min_net_rr":[1.5,2.,2.5,3.,4.],
    "session_utc":[0,6,12,18],
}
SHAPE=tuple(len(v) for v in GRID.values())
CONFIGURATIONS=math.prod(SHAPE)
COSTS=[{"name":"reference","spread":.25,"slippage_per_side":.05},
       {"name":"cautious","spread":.5,"slippage_per_side":.1},
       {"name":"stress","spread":1.,"slippage_per_side":.2}]
MIN_RR=1.5
MIN_ADR_FRACTION=.25


def features(m1):
    out=closed_features(m1)
    agg={"open":"first","high":"max","low":"min","close":"last"}
    daily=m1.resample('1D',label='right',closed='left').agg(agg)
    daily=daily[m1.close.resample('1D',label='right',closed='left').count()>=900].copy()
    daily['adr20']=(daily.high-daily.low).rolling(20).mean()
    for side,col,op in [(1,'low','min'),(-1,'high','max')]:
        daily[f'anchor_{side}_PREV_D1']=daily[col]
        daily[f'anchor_{side}_PREV_2D']=getattr(daily[col].rolling(2),op)()
    daily['formed']=daily.index.asi8/3.6e12
    h4=m1.resample('4h',label='right',closed='left').agg(agg)
    h4=h4[m1.close.resample('4h',label='right',closed='left').count()>=180].copy()
    for side,col,op in [(1,'low','min'),(-1,'high','max')]:
        h4[f'anchor_{side}_H4_RANGE_6']=getattr(h4[col].rolling(6),op)()
    h4['formed']=h4.index.asi8/3.6e12
    # Anchor must already exist at M5 open, not be learned during its sweep.
    keys=pd.DataFrame({'key':out.index-pd.Timedelta(minutes=5)},index=out.index)
    for known,cols,sources in [
        (daily,['adr20','anchor_1_PREV_D1','anchor_-1_PREV_D1','anchor_1_PREV_2D','anchor_-1_PREV_2D','formed'],['PREV_D1','PREV_2D']),
        (h4,['anchor_1_H4_RANGE_6','anchor_-1_H4_RANGE_6','formed'],['H4_RANGE_6'])]:
        aligned=pd.merge_asof(keys.reset_index(),known[cols].reset_index().rename(columns={'timestamp':'key'}),
                              on='key',direction='backward').set_index('timestamp')
        for col in cols:
            if col!='formed':out[col]=aligned[col]
        for source in sources:out['formed_'+source]=aligned.formed
    for source,start,end in [('ASIA_00_06',0,6),('EUROPE_06_12',6,12)]:
        selected=m1.loc[(m1.index.hour>=start)&(m1.index.hour<end)]
        bounds=selected.resample('1D').agg(agg)
        count=selected.close.resample('1D').count()
        bounds=bounds.loc[count>=300].copy()
        bounds.index=bounds.index+pd.Timedelta(hours=end)
        bounds['formed']=bounds.index.asi8/3.6e12
        aligned=pd.merge_asof(keys.reset_index(),bounds[['low','high','formed']].reset_index().rename(columns={'timestamp':'key'}),
                              on='key',direction='backward').set_index('timestamp')
        # Never use yesterday's session as today's anchor before it completes.
        same_day=(pd.to_datetime(aligned.formed*3.6e12,utc=True).dt.normalize().to_numpy()==out.index.normalize().to_numpy())
        out[f'anchor_1_{source}']=aligned.low.where(same_day)
        out[f'anchor_-1_{source}']=aligned.high.where(same_day)
        out['formed_'+source]=aligned.formed.where(same_day)
    return out


def events(frame,side,source,depth):
    f=frame
    anchor=f[f'anchor_{side}_{source}']
    extreme=f.low if side==1 else f.high
    swept=side*(anchor-extreme)/f.atr
    reclaimed=side*(f.close-anchor)
    span=(f.high-f.low).replace(0,np.nan)
    wick=((np.minimum(f.open,f.close)-f.low) if side==1 else (f.high-np.maximum(f.open,f.close)))/span
    approach=((f.approach_high-anchor) if side==1 else (anchor-f.approach_low))/f.atr
    age=f.index.asi8/3.6e12-f['formed_'+source]
    remaining=20*60+55-(f.index.hour*60+f.index.minute)
    mask=(swept>depth)&(reclaimed>=.025*f.atr)&(side*(f.close-f.open)>0)&(f.atr>0)&(f.adr20>0)&(approach>=0)&(age>=0)&(age<=96)&(remaining>=120)&f.slope.notna()
    out=f.loc[mask,['close','atr','adr20','year','session']].copy()
    out['anchor']=anchor[mask]
    # Structural invalidation beyond the observed sweep extreme, not a distant old level.
    out['level']=extreme[mask]
    out['sweep_depth']=swept[mask]
    out['wick_bin']=np.clip(np.searchsorted(GRID['wick_fraction'],wick[mask],side='right')-1,0,4)
    out['approach_bin']=np.clip(np.searchsorted(GRID['approach_atr'],approach[mask],side='right')-1,0,4)
    slope=side*f.slope[mask]
    out['trend_bin']=np.where(slope>.05,0,np.where(slope<-.05,1,2))
    return out


def config(index):
    return {name:values[i] for (name,values),i in zip(GRID.items(),index)}


def filter_events(rows,cfg):
    trend=cfg['trend']
    return ((rows.wick_bin>=GRID['wick_fraction'].index(cfg['wick_fraction'])) &
        (rows.approach_bin>=GRID['approach_atr'].index(cfg['approach_atr'])) &
        (rows.session==cfg['session_utc']//6) &
        ((rows.trend_bin==['ALIGNED','OPPOSED','FLAT'].index(trend)) if trend!='ANY' else True))

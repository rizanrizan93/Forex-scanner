"""Scanner-only daily reversal research; no broker/order/execution imports."""
from __future__ import annotations
import math
import numpy as np
import pandas as pd
from .reversal_zones import closed_features, base_events

CONTRACT = "RIZAN_XAU_MAJOR_DAILY_REVERSAL_NET_V3"
GRID = {
    "side":[1,-1], "zone_source":["D1_PREVIOUS","H1_6","H1_12","H1_24","M15_CHANNEL_48"],
    "half_width_atr":[0.,.1,.2,.35,.5],
    "invalidation_atr":[.5,.75,1.,1.5,2.],
    "reaction_atr":[1.5,2.,3.,4.,6.], "horizon_minutes":[120,240,360,480],
    "wick_fraction":[0.,.1,.2,.3,.4], "trend":["ANY","ALIGNED","OPPOSED","FLAT"],
    "approach_atr":[0.,.5,1.,1.5,2.], "max_age_hours":[6,12,24,48,96],
    "session_utc":[0,6,12,18],
}
SHAPE=tuple(len(v) for v in GRID.values())
CONFIGURATIONS=math.prod(SHAPE)
COSTS=[{"name":"reference","spread":.25,"slippage_per_side":.05},
       {"name":"cautious","spread":.50,"slippage_per_side":.10},
       {"name":"stress","spread":1.,"slippage_per_side":.20}]
MIN_RR=1.5
MIN_ADR_FRACTION=.25


def features(m1):
    out=closed_features(m1)
    agg={"open":"first","high":"max","low":"min","close":"last"}
    daily=m1.resample('1D',label='right',closed='left').agg(agg)
    daily=daily[m1.close.resample('1D',label='right',closed='left').count()>=900]
    daily['adr20']=(daily.high-daily.low).rolling(20).mean()
    m15=m1.resample('15min',label='right',closed='left').agg(agg)
    m15=m15[m1.close.resample('15min',label='right',closed='left').count()>=12]
    m15['m15_body']=m15.close-m15.open
    m15['m15_location']=(m15.close-m15.low)/(m15.high-m15.low).replace(0,np.nan)
    m15['m15_low']=m15.low;m15['m15_high']=m15.high
    mean=m15.close.rolling(48).mean()
    centered=np.arange(48)-23.5;varx=(48**2-1)/12
    slope=m15.close.rolling(48).apply(lambda a:np.dot(a,centered)/48/varx,raw=True)
    residual=np.maximum((m15.close*m15.close).rolling(48).mean()-mean*mean-slope*slope*varx,0)
    fitted=mean+slope*23.5
    m15['channel_low']=fitted-1.5*np.sqrt(residual)
    m15['channel_high']=fitted+1.5*np.sqrt(residual)
    m15['channel_formed']=m15.index.asi8/3.6e12
    daily['d1_low']=daily.low;daily['d1_high']=daily.high
    daily['d1_formed']=daily.index.asi8/3.6e12
    for frame,cols in [(daily,['adr20','d1_low','d1_high','d1_formed']),
                       (m15,['m15_body','m15_location','m15_low','m15_high','channel_low','channel_high','channel_formed'])]:
        keys=pd.DataFrame({'key':out.index-pd.Timedelta(minutes=5)},index=out.index)
        mapped=pd.merge_asof(keys.reset_index(),frame[cols].reset_index().rename(columns={'timestamp':'key'}),on='key',direction='backward').set_index('timestamp')
        for col in cols: out[col]=mapped[col]
    for side,col in [(1,'low'),(-1,'high')]:
        for h in [6,12,24]:
            out[f'level_{side}_H1_{h}']=out[f'level_{side}_{h}']
            out[f'formed_{side}_H1_{h}']=out[f'formed_{side}_{h}']
        out[f'level_{side}_D1_PREVIOUS']=out[f'd1_{col}']
        out[f'formed_{side}_D1_PREVIOUS']=out.d1_formed
        out[f'level_{side}_M15_CHANNEL_48']=out[f'channel_{col}']
        out[f'formed_{side}_M15_CHANNEL_48']=out.channel_formed
    return out


def events(frame, side, lookback, width):
    result=base_events(frame,side,lookback,width)
    # M5 must reclaim the completed M15 range, rather than requiring the prior
    # M15 body to have turned before the first reversal touch even occurred.
    mask=(result.close>=frame.loc[result.index,'m15_low']) if side==1 else (result.close<=frame.loc[result.index,'m15_high'])
    result=result.loc[mask].copy()
    result['adr20']=frame.loc[result.index,'adr20']
    # Exit before the earliest NY rollover (21:00 UTC); no swap assumptions.
    remaining=20*60+55-(result.index.hour*60+result.index.minute)
    result=result.loc[(remaining>=120)&(result.adr20>0)]
    # One base observation per 8h; maximum horizon cannot overlap.
    keep=[];last=-(2**63)
    for i, stamp in enumerate(result.index.asi8):
        if int(stamp)-last>=480*60*10**9: keep.append(i);last=int(stamp)
    return result.iloc[keep]


def config(index):
    return {name:values[i] for (name,values),i in zip(GRID.items(),index)}


def filter_events(rows,cfg):
    trend=cfg['trend']
    return ((rows.wick_bin>=GRID['wick_fraction'].index(cfg['wick_fraction'])) &
        (rows.approach_bin>=GRID['approach_atr'].index(cfg['approach_atr'])) &
        (rows.age_bin<=GRID['max_age_hours'].index(cfg['max_age_hours'])) &
        (rows.session==cfg['session_utc']//6) &
        ((rows.trend_bin==['ALIGNED','OPPOSED','FLAT'].index(trend)) if trend!='ANY' else True))

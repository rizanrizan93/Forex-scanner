"""Scanner-only: M15 anchor sweep then M5 displacement within 30 minutes."""
from __future__ import annotations
import math
import numpy as np
import pandas as pd
from .daily_reversal import features as anchor_features, COSTS, MIN_RR, MIN_ADR_FRACTION
CONTRACT="RIZAN_XAU_M15_M5_ANCHOR_REVERSAL_1M_V1"
GRID={"side":[1,-1],"zone_source":["PREV_D1","PREV_2D","ASIA_00_06","EUROPE_06_12","H4_RANGE_6"],
"sweep_depth_atr":[0.,.025,.05,.1,.2],"stop_extension_atr":[.05,.1,.2,.35,.5],
"target_adr_fraction":[.25,.35,.5,.75,1.],"horizon_minutes":[120,240,360,480],
"wick_fraction":[0.,.2,.35,.5,.65],"trend":["ANY","ALIGNED"],"approach_atr":[0.],
"min_net_rr":[1.5,2.,2.5,3.,4.],"session_utc":[0,6,12,18]}
SHAPE=tuple(len(v) for v in GRID.values());CONFIGURATIONS=math.prod(SHAPE)

def features(m1):
    f=anchor_features(m1)
    m15=m1.resample('15min',label='right',closed='left').agg({"open":"first","high":"max","low":"min","close":"last"})
    m15=m15.loc[m1.close.resample('15min',label='right',closed='left').count()==15]
    # M5 anchor at close-10 has key close-15: known when the M15 seed opens.
    known=f.reindex(m15.index-pd.Timedelta(minutes=10)).copy();known.index=m15.index
    for name in ['open','high','low','close']:
        f['seed_'+name]=m15[name].reindex(f.index)
    for name in ['atr','adr20','slope']+[f'anchor_{s}_{z}' for s in [1,-1] for z in GRID['zone_source']]:
        f['seed_'+name]=known[name].reindex(f.index)
    return f

def events(f,side,source,depth):
    records=[];seed=None
    for stamp,row in f.iterrows():
        if seed is not None:
            age=(stamp-seed['seed_time']).total_seconds()
            if age>1800:seed=None
            elif age>0 and side*(row.close-seed['break_level'])>.025*seed['atr'] and side*(row.close-row.open)>0:
                remaining=20*60+55-(stamp.hour*60+stamp.minute)
                if remaining>=120:
                    record={**seed,'timestamp':stamp,'close':row.close,'year':stamp.year,'session':stamp.hour//6}
                    records.append(record)
                seed=None
        anchor=row['seed_anchor_'+str(side)+'_'+source]
        atr=row.seed_atr;adr=row.seed_adr20
        if not (np.isfinite(anchor) and np.isfinite(atr) and atr>0 and np.isfinite(adr) and adr>0 and np.isfinite(row.seed_slope)):continue
        extreme=row.seed_low if side==1 else row.seed_high
        span=row.seed_high-row.seed_low
        if span<=0:continue
        if side*(anchor-extreme)/atr<=depth or side*(row.seed_close-anchor)<.025*atr or side*(row.seed_close-row.seed_open)<=0:continue
        wick=(min(row.seed_open,row.seed_close)-row.seed_low)/span if side==1 else (row.seed_high-max(row.seed_open,row.seed_close))/span
        slope=side*row.seed_slope
        seed={'seed_time':stamp,'anchor':anchor,'level':extreme,'break_level':row.seed_high if side==1 else row.seed_low,
              'atr':atr,'adr20':adr,'wick_bin':int(np.clip(np.searchsorted(GRID['wick_fraction'],wick,side='right')-1,0,4)),
              'approach_bin':0,'trend_bin':0 if slope>.05 else 1 if slope<-.05 else 2}
    cols=['timestamp','close','year','session','seed_time','anchor','level','break_level','atr','adr20','wick_bin','approach_bin','trend_bin']
    out=pd.DataFrame(records,columns=cols).set_index('timestamp').rename_axis('timestamp')
    out.index=pd.DatetimeIndex(out.index,tz='UTC') if out.empty else pd.DatetimeIndex(out.index)
    for name in ["close","anchor","level","break_level","atr","adr20"]:out[name]=out[name].astype(float)
    for name in ["year","session","wick_bin","approach_bin","trend_bin"]:out[name]=out[name].astype(int)
    return out

def config(index):return {k:v[i] for (k,v),i in zip(GRID.items(),index)}

def filter_events(rows,cfg):
    return (rows.wick_bin>=GRID['wick_fraction'].index(cfg['wick_fraction'])) & (rows.session==cfg['session_utc']//6) & ((rows.trend_bin==0) if cfg['trend']=='ALIGNED' else True)

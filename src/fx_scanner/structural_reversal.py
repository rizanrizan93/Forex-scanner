"""Scanner research: confirmed M5 reaction, structural ATR-M5 stop, R targets."""
from __future__ import annotations
import math
import numpy as np
import pandas as pd
from .major_reversal import features as channel_features, events as channel_events, filter_events

CONTRACT="RIZAN_XAU_STRUCTURAL_M5_REVERSAL_NET_V1"
GRID={
    "side":[1,-1],
    "zone_source":["M5_CHANNEL_24","M5_CHANNEL_32","M5_CHANNEL_48","M5_CHANNEL_64","M5_SWEEP_24"],
    "half_width_atr":[0.,.1,.2,.35,.5],
    "stop_atr5_multiple":[1.,1.65,2.15,2.65,3.25],
    "target_r":[1.5,2.,3.,4.,6.6],
    "horizon_minutes":[120,240,360,480],
    "wick_fraction":[0.,.1,.2,.3,.4],
    "trend":["ANY","ALIGNED","OPPOSED","FLAT"],
    "approach_atr":[0.,.5,1.,1.5,2.],
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
    f=channel_features(m1)
    tr=pd.concat([f.high-f.low,(f.high-f.close.shift()).abs(),(f.low-f.close.shift()).abs()],axis=1).max(axis=1)
    f['atr5']=tr.rolling(14).mean()
    return f


def events(frame,side,source,width):
    e=channel_events(frame,side,source,width).copy()
    e['zone_anchor']=e.level
    if source!='M5_SWEEP_24':
        e['level']=frame.loc[e.index,'low' if side==1 else 'high']
    # Sweep source already carries seed extreme known before confirmation.
    e['atr5']=frame.loc[e.index,'atr5']
    return e.loc[e.atr5>0]


def config(index):
    return {name:values[i] for (name,values),i in zip(GRID.items(),index)}


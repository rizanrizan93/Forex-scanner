"""Scanner research: structural M5 reversal with known volatility/cost floor."""
from __future__ import annotations
import math
from .structural_reversal import features, events as structural_events, filter_events, COSTS, MIN_RR, MIN_ADR_FRACTION

CONTRACT="RIZAN_XAU_VOLATILITY_COST_REVERSAL_NET_V1"
GRID={
    "side":[1,-1],
    "zone_source":["M5_CHANNEL_24","M5_CHANNEL_32","M5_CHANNEL_48","M5_CHANNEL_64","M5_SWEEP_24"],
    "min_atr5_cost_ratio":[0.,.5,1.,1.5,2.],
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


def events(frame,side,source,ratio):
    # Broad geometry admits confirmed sources. Floor uses completed trigger ATR,
    # not future realized range or the outcome of any trade.
    e=structural_events(frame,side,source,.5)
    return e.loc[e.atr5>=ratio*.5]


def config(index):
    return {name:values[i] for (name,values),i in zip(GRID.items(),index)}


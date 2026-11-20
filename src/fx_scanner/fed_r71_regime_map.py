"""R7.1 causal price-regime detection, using only completed past XAU sessions.

BULLISH/BEARISH = observable trend-state proxies, not future direction.
LIQUIDITY_STRESS = volatility/displacement *proxy*; no claim of actual
margin liquidation, resting stop orders, order book or institutional flow.
NEUTRAL/UNKNOWN prevent forcing a bull/bear interpretation.
"""
from __future__ import annotations
import numpy as np
import pandas as pd

CONTRACT="RIZAN_R71_DAILY_XAU_PRICE_REGIME_V1"
STATES=("BULLISH","BEARISH","LIQUIDITY_STRESS","NEUTRAL","UNKNOWN")
BASIS="OHLC_PRICE_VOLATILITY_PROXY_NOT_LIVE_MARKET_LIQUIDITY"


def map_regimes(frame: pd.DataFrame):
    required={"open","high","low","close"}
    if (not isinstance(frame,pd.DataFrame) or
        not required.issubset(frame.columns) or
        not isinstance(frame.index,pd.DatetimeIndex) or
        frame.index.tz is None or
        frame.index.has_duplicates or
        not frame.index.is_monotonic_increasing):
        raise ValueError("R71_UTC_SORTED_DAILY_OHLC_REQUIRED")
    x=frame[list(required)].copy()
    x.index=x.index.tz_convert("UTC")
    if ((~np.isfinite(x.to_numpy(dtype=float))).any() or
        (x.low<=0).any() or
        (x.high<x[["open","close"]].max(axis=1)).any() or
        (x.low>x[["open","close"]].min(axis=1)).any()):
        raise ValueError("INVALID_DAILY_PRICE_OR_RANGE")
    close=x.close
    r=close.pct_change()
    ema=close.ewm(span=63,adjust=False,min_periods=63).mean()
    mom21=close/close.shift(21)-1
    true_range=pd.concat([
        x.high-x.low,(x.high-close.shift()).abs(),
        (x.low-close.shift()).abs()],axis=1).max(axis=1)
    atr=true_range.rolling(14,min_periods=14).mean()
    vol21=r.rolling(21,min_periods=21).std()
    # Rolling 252-session 85th percentile of *strictly earlier*
    # observed vol values. Today's price is permitted to update vol
    # but cannot reset its stress threshold after the fact.
    threshold=vol21.shift(1).rolling(252,min_periods=126).quantile(.85)
    large_displacement=(true_range/atr.shift(1)>2.5)
    macro_gap=pd.Series(x.index,index=x.index).diff()>pd.Timedelta(days=7)
    age_since_gap=(~macro_gap).astype(int).groupby(macro_gap.cumsum()).cumsum()
    valid=(ema.notna()&atr.notna()&mom21.notna()&
           threshold.notna()&(age_since_gap>=21))
    stress=valid & ((vol21>threshold)&(r.abs()>1.2*vol21)) | (
        valid & large_displacement)
    bull=valid & (close>ema) & (ema>ema.shift(5)) & (mom21>0)
    bear=valid & (close<ema) & (ema<ema.shift(5)) & (mom21<0)
    s=pd.Series("NEUTRAL",index=x.index,name="regime",dtype="object")
    s.loc[~valid]="UNKNOWN"
    s.loc[bull & ~stress]="BULLISH"
    s.loc[bear & ~stress]="BEARISH"
    s.loc[stress]="LIQUIDITY_STRESS"
    return s


def diagnose_regimes(frame: pd.DataFrame):
    s=map_regimes(frame)
    return {
        "contract":CONTRACT,"basis":BASIS,
        "states":{str(k):int(v) for k,v in s.value_counts().items()},
        "as_of_first":s.index[0].isoformat(),
        "as_of_last":s.index[-1].isoformat(),
        "n":len(s),"future_bars_read":False,
        "liquidation_confirmed":False,
        "order_authority":False,
    }

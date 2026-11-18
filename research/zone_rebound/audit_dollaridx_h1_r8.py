"""R8: audit actual Dukascopy DOLLAR.IDX/USD H1 data and causal timestamps.

No trades or model fit. The instrument catalog lists H1/H4 and tick but NOT M1.
H1 bars can inform a 5-minute XAU entry only AFTER their close + delay.
"""
from __future__ import annotations
import hashlib, json, sys
from pathlib import Path
import numpy as np
import pandas as pd

def audit_h1(path:Path, *,availability_lag_minutes=2):
    raw=path.read_bytes()
    sha=hashlib.sha256(raw).hexdigest()
    d=pd.read_csv(path)
    required={'timestamp','open','high','low','close'}
    if not required.issubset(d.columns):raise ValueError('missing CSV columns')
    if len(d)<3:raise ValueError('insufficient H1 observations')
    t=pd.to_datetime(pd.to_numeric(d.timestamp,errors='raise'),unit='ms',utc=True)
    if t.isna().any() or t.duplicated().any() or not t.is_monotonic_increasing:
        raise ValueError('timestamp duplicates, NA or nonmonotonic')
    if (t.astype('int64')%(3600*10**9)!=0).any():
        raise ValueError('not hourly UTC bar opens')
    p=d[['open','high','low','close']].apply(pd.to_numeric,errors='raise')
    if not np.isfinite(p.to_numpy()).all() or (p.low<=0).any() or (
        (p.low>p[['open','close']].min(axis=1)) |
        (p.high<p[['open','close']].max(axis=1)) |
        (p.high<p.low)).any():
        raise ValueError('invalid prices')
    gaps=(t.diff().dt.total_seconds().dropna()/3600)
    # No synthetic H1 interpolation across weekend / market closure.
    # Each observation is available at close of H1 + delay, not at its open.
    available=t+pd.Timedelta(minutes=60+availability_lag_minutes)
    return {'instrument':'DOLLAR.IDX/USD','source_kind':'BROKER_INDEX_CFD_PROXY_NOT_ICE_DXY',
            'timeframe':'H1','rows':len(d),'sha256':sha,
            'first_open_utc':t.iloc[0].isoformat(),'last_open_utc':t.iloc[-1].isoformat(),
            'largest_gap_hours':float(gaps.max()),'gaps_gt_1h':int((gaps>1).sum()),
            'earliest_first_bar_available_utc':available.iloc[0].isoformat(),
            'min_close':float(p.close.min()),'max_close':float(p.close.max()),
            'is_official_ice_dxy':False,'is_intraday_cash_treasury_yield':False}

if __name__=='__main__':
    if len(sys.argv)!=2:raise SystemExit('Usage: python audit_dollaridx_h1.py file.csv')
    print(json.dumps(audit_h1(Path(sys.argv[1])),indent=2))

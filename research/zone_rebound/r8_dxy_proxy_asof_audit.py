"""R8: fail-closed point-in-time DXY M1 data provenance and conditional feature audit.

No network fetching, no live integration. CSV timestamps must be UTC bar OPEN.
Dukascopy DOLLAR.IDX/USD is a DXY proxy, NOT official ICE DXY.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import pandas as pd

def inspect_dxy_csv(path, *, observed_at, source_url, sha256=None, max_quote_age_seconds=300):
    p=Path(path)
    raw=p.read_bytes()
    digest=hashlib.sha256(raw).hexdigest()
    if sha256 is not None and digest.lower()!=sha256.lower():
        raise ValueError('SHA256 mismatch: source bytes cannot be trusted')
    if not source_url.startswith('https://'):
        raise ValueError('HTTPS provenance URL required')
    d=pd.read_csv(p)
    required={'timestamp','open','high','low','close'}
    if not required.issubset(d.columns):
        raise ValueError('Missing M1 OHLC columns')
    if len(d)<120:
        raise ValueError('Insufficient M1 DXY proxy history')
    if not d.timestamp.astype(str).str.contains(r'(?:Z|[+-]00:00)$',regex=True).all():
        raise ValueError('Explicit UTC timestamps required')
    t=pd.to_datetime(d.timestamp,utc=True,errors='raise')
    if t.isna().any() or t.duplicated().any() or not t.is_monotonic_increasing:
        raise ValueError('Non-monotonic/duplicate timestamps')
    for c in ('open','high','low','close'):
        d[c]=pd.to_numeric(d[c],errors='raise')
    if d[list(('open','high','low','close'))].isna().any().any():
        raise ValueError('NaN price')
    if ((d.high<d[['open','close']].max(axis=1)) |
        (d.low>d[['open','close']].min(axis=1)) |
        (d.low<=0)).any():
        raise ValueError('Invalid OHLC')
    observed=pd.Timestamp(observed_at)
    if observed.tzinfo is None:
        raise ValueError('observed_at needs timezone')
    observed=observed.tz_convert('UTC')
    if t.iloc[-1]+pd.Timedelta(minutes=1)>observed:
        raise ValueError('Last bar not yet closed at observation')
    age=(observed-(t.iloc[-1]+pd.Timedelta(minutes=1))).total_seconds()
    if age<0 or age>max_quote_age_seconds:
        raise ValueError('Quote age invalid/stale')
    gaps=(t.diff().dropna()!=pd.Timedelta(minutes=1)).sum()
    d.index=t
    d=d.drop(columns='timestamp')
    # Strictly complete bars. At event t, only features from bars closed <= t.
    features={}
    for minutes in (5,15,60):
        g=d.resample(f'{minutes}min',label='right',closed='left')
        candles=g.agg({'open':'first','high':'max','low':'min','close':'last'})
        counts=g.close.count()
        candles=candles[(counts==minutes)&(candles.index<=observed)]
        features[minutes]=candles
    report={'contract':'R8_DUKASCOPY_DOLLARIDXUSD_AUDIT_V1',
            'instrument':'DOLLAR.IDX/USD','proxy_not_ice_dxy':True,
            'source_url':source_url,'sha256':digest,'observed_at':observed.isoformat(),
            'first_m1_open':t.iloc[0].isoformat(),'last_m1_close':(t.iloc[-1]+pd.Timedelta(minutes=1)).isoformat(),
            'quote_age_seconds':age,'rows':len(d),'non_contiguous_m1_intervals':int(gaps),
            'complete_bars':{str(k):len(v) for k,v in features.items()},
            'real_market_accuracy_tested':False}
    return report,features

def event_direction(events, dxy_features, *, horizon_minutes=60):
    """Point-in-time directional DXY features; events must carry UTC event timestamp.

    For each event, select last completed 5/15/60m candle <= event timestamp.
    No outcome label is computed, and no trading accuracy is claimed.
    """
    if not 0<horizon_minutes<=240:raise ValueError('Bad horizon')
    result=[]
    for event in events:
        at=pd.Timestamp(event['timestamp'])
        if at.tzinfo is None:raise ValueError('Event timestamp needs timezone')
        at=at.tz_convert('UTC')
        row={'timestamp':at.isoformat(),'event_side':event['side']}
        if event['side'] not in ('BUY','SELL'):raise ValueError('Invalid side')
        for tf in (5,15,60):
            f=dxy_features[tf]
            history=f.loc[f.index<=at]
            # Two fully completed candles needed; stale features rejected.
            if len(history)<2 or at-history.index[-1]>pd.Timedelta(minutes=tf+5):
                row[f'dxy_{tf}m']='UNAVAILABLE'
            else:
                delta=float(history.close.iloc[-1]-history.close.iloc[-2])
                row[f'dxy_{tf}m']='UP' if delta>0 else 'DOWN' if delta<0 else 'FLAT'
                row[f'dxy_{tf}m_asof']=history.index[-1].isoformat()
        result.append(row)
    return result

"""R7 cross-market point-in-time feature gate for RESEARCH ONLY.

Never substitute a vendor's USD index CFD for official ICE DXY.
Never substitute futures prices for actual cash Treasury yields.
All bar timestamps are UTC *open* minute; a bar can be used only after its
end plus an explicit conservative availability delay. No order hooks.
"""
from __future__ import annotations
import numpy as np
import pandas as pd

EXECUTION_AUTHORITY=False
EXECUTION_INFLUENCE=False
DXY_PROXY_SOURCE='DUKASCOPY_DOLLARIDXUSD_M1_NOT_ICE_DXY'
FUTURES_PROXY_SOURCES={'CME_ZT_FUTURES_M1_NOT_CASH_2Y_YIELD',
                       'CME_ZN_FUTURES_M1_NOT_CASH_10Y_YIELD'}
MINUTE_NS=60_000_000_000

def normalize_quote_m1(source:pd.DataFrame,source_id:str)->pd.DataFrame:
    """Fail closed if time zone, source, OHLC, ordering or bar shape is invalid."""
    if source_id != DXY_PROXY_SOURCE and source_id not in FUTURES_PROXY_SOURCES:
        raise ValueError('UNAPPROVED_MACRO_SOURCE')
    cols={'timestamp','open','high','low','close'}
    if not cols.issubset(source.columns):
        raise ValueError('MACRO_M1_REQUIRED_COLUMNS')
    x=source[list(('timestamp','open','high','low','close'))].copy()
    if x.empty:raise ValueError('EMPTY_MACRO_M1')
    # A timezone-less date is not an as-of historical quote. Reject rather than
    # silently assign UTC (or worse, local workstation time).
    txt=x.timestamp.astype(str)
    if not txt.str.contains(r'(?:Z|[+-][0-9]{2}:?[0-9]{2}),regex=True).all():
        raise ValueError('MACRO_TIMESTAMP_MUST_HAVE_UTC_OFFSET')
    t=pd.to_datetime(x.timestamp,utc=True,errors='coerce')
    if t.isna().any():raise ValueError('INVALID_MACRO_TIMESTAMP')
    if (t.astype('int64')%MINUTE_NS!=0).any():raise ValueError('UNALIGNED_MACRO_MINUTES')
    for c in ('open','high','low','close'):
        x[c]=pd.to_numeric(x[c],errors='coerce')
    if not np.isfinite(x[['open','high','low','close']].to_numpy()).all():
        raise ValueError('INVALID_MACRO_PRICES')
    if ((x.low<=0)|(x.low>x[['open','close']].min(axis=1))|
        (x.high<x[['open','close']].max(axis=1))|(x.high<x.low)).any():
        raise ValueError('INCONSISTENT_MACRO_OHLC')
    x.index=pd.DatetimeIndex(t,name='open_utc')
    x=x.drop(columns='timestamp')
    if x.index.has_duplicates:raise ValueError('DUPLICATE_MACRO_MINUTES')
    return x.sort_index()

def _known_returns(m1:pd.DataFrame,periods=(5,15,60))->pd.DataFrame:
    out=pd.DataFrame(index=m1.index)
    times=m1.index.asi8
    # Count gaps; a window must contain every minute, not be created across
    # weekends, vendor outages or instrument trading-session breaks.
    gaps=np.r_[0,np.cumsum(np.diff(times)!=MINUTE_NS)]
    for minutes in periods:
        start=np.arange(len(m1))-minutes
        prev=m1.close.shift(minutes)
        enough=start>=0
        contiguous=np.zeros(len(m1),dtype=bool)
        idx=np.flatnonzero(enough)
        contiguous[idx]=gaps[idx]==gaps[start[idx]]
        out[f'return_{minutes}m_pct']=((m1.close/prev)-1.0).mul(100).where(contiguous)
    return out

def asof_proxy_features(m1_quotes:pd.DataFrame,events:pd.DataFrame,
                        *,source_id:str=DXY_PROXY_SOURCE,
                        availability_delay_minutes:int=1,
                        max_age_minutes:int=5)->pd.DataFrame:
    """Add observed historical proxy returns at each UTC entry decision instant.

    If any required span is stale or missing, the signal remains WAIT.
    The returned eligibility flag explicitly means DATA READY, *not* 60%
    accuracy or a recommendation to trade.
    """
    if availability_delay_minutes<0 or availability_delay_minutes>30:
        raise ValueError('INVALID_AVAILABILITY_DELAY')
    if max_age_minutes<0 or max_age_minutes>60:
        raise ValueError('INVALID_DATA_AGE')
    if 'entry_ns' not in events.columns:raise ValueError('EVENT_TIMESTAMP_REQUIRED')
    if events.entry_ns.isna().any():raise ValueError('INVALID_EVENT_NS')
    if events.entry_ns.duplicated().any():
        # Multiple opposite outcomes at same instant are not a unique decision.
        raise ValueError('NON_UNIQUE_EVENT_TIMESTAMP')
    ev=events.copy()
    if ev.empty:
        ev['macro_ready']=pd.Series([],dtype=bool)
        return ev
    m=normalize_quote_m1(m1_quotes,source_id)
    rt=_known_returns(m)
    # Source M1 timestamp is OPEN. Its CLOSE becomes available no earlier than
    # the next M1 start PLUS explicit publication/delivery buffer.
    rt['quote_available_ns']=m.index.asi8+(1+availability_delay_minutes)*MINUTE_NS
    rt['last_quote_open_ns']=m.index.asi8
    rt=rt.sort_values('quote_available_ns').reset_index(drop=True)
    left=ev.sort_values('entry_ns').copy()
    joined=pd.merge_asof(left,rt,left_on='entry_ns',right_on='quote_available_ns',
                         direction='backward',allow_exact_matches=True)
    age=(joined.entry_ns-joined.quote_available_ns)/MINUTE_NS
    ready=(age>=0)&(age<=max_age_minutes)
    ready &= joined[[f'return_{i}m_pct' for i in (5,15,60)]].notna().all(axis=1)
    for col in ('return_5m_pct','return_15m_pct','return_60m_pct'):
        joined[source_id+'_'+col]=joined[col].where(ready)
    joined['macro_ready']=ready.fillna(False)
    joined['macro_proxy_source']=source_id
    joined['macro_source_kind']='INDEX_CFD_PROXY' if source_id==DXY_PROXY_SOURCE else 'TREASURY_FUTURES_PRICE_PROXY'
    joined['is_official_ice_dxy']=False
    joined['is_cash_treasury_yield']=False
    joined=joined.drop(columns=[c for c in ['return_5m_pct','return_15m_pct',
                                           'return_60m_pct','quote_available_ns',
                                           'last_quote_open_ns'] if c in joined.columns])
    return joined.sort_index().reset_index(drop=True)
,regex=True).all():
        raise ValueError('MACRO_TIMESTAMP_MUST_HAVE_UTC_OFFSET')
    t=pd.to_datetime(x.timestamp,utc=True,errors='coerce')
    if t.isna().any():raise ValueError('INVALID_MACRO_TIMESTAMP')
    if (t.astype('int64')%MINUTE_NS!=0).any():raise ValueError('UNALIGNED_MACRO_MINUTES')
    for c in ('open','high','low','close'):
        x[c]=pd.to_numeric(x[c],errors='coerce')
    if not np.isfinite(x[['open','high','low','close']].to_numpy()).all():
        raise ValueError('INVALID_MACRO_PRICES')
    if ((x.low<=0)|(x.low>x[['open','close']].min(axis=1))|
        (x.high<x[['open','close']].max(axis=1))|(x.high<x.low)).any():
        raise ValueError('INCONSISTENT_MACRO_OHLC')
    x.index=pd.DatetimeIndex(t,name='open_utc')
    x=x.drop(columns='timestamp')
    if x.index.has_duplicates:raise ValueError('DUPLICATE_MACRO_MINUTES')
    return x.sort_index()

def _known_returns(m1:pd.DataFrame,periods=(5,15,60))->pd.DataFrame:
    out=pd.DataFrame(index=m1.index)
    times=m1.index.asi8
    # Count gaps; a window must contain every minute, not be created across
    # weekends, vendor outages or instrument trading-session breaks.
    gaps=np.r_[0,np.cumsum(np.diff(times)!=MINUTE_NS)]
    for minutes in periods:
        start=np.arange(len(m1))-minutes
        prev=m1.close.shift(minutes)
        enough=start>=0
        contiguous=np.zeros(len(m1),dtype=bool)
        idx=np.flatnonzero(enough)
        contiguous[idx]=gaps[idx]==gaps[start[idx]]
        out[f'return_{minutes}m_pct']=((m1.close/prev)-1.0).mul(100).where(contiguous)
    return out

def asof_proxy_features(m1_quotes:pd.DataFrame,events:pd.DataFrame,
                        *,source_id:str=DXY_PROXY_SOURCE,
                        availability_delay_minutes:int=1,
                        max_age_minutes:int=5)->pd.DataFrame:
    """Add observed historical proxy returns at each UTC entry decision instant.

    If any required span is stale or missing, the signal remains WAIT.
    The returned eligibility flag explicitly means DATA READY, *not* 60%
    accuracy or a recommendation to trade.
    """
    if availability_delay_minutes<0 or availability_delay_minutes>30:
        raise ValueError('INVALID_AVAILABILITY_DELAY')
    if max_age_minutes<0 or max_age_minutes>60:
        raise ValueError('INVALID_DATA_AGE')
    if 'entry_ns' not in events.columns:raise ValueError('EVENT_TIMESTAMP_REQUIRED')
    if events.entry_ns.isna().any():raise ValueError('INVALID_EVENT_NS')
    if events.entry_ns.duplicated().any():
        # Multiple opposite outcomes at same instant are not a unique decision.
        raise ValueError('NON_UNIQUE_EVENT_TIMESTAMP')
    ev=events.copy()
    if ev.empty:
        ev['macro_ready']=pd.Series([],dtype=bool)
        return ev
    m=normalize_quote_m1(m1_quotes,source_id)
    rt=_known_returns(m)
    # Source M1 timestamp is OPEN. Its CLOSE becomes available no earlier than
    # the next M1 start PLUS explicit publication/delivery buffer.
    rt['quote_available_ns']=m.index.asi8+(1+availability_delay_minutes)*MINUTE_NS
    rt['last_quote_open_ns']=m.index.asi8
    rt=rt.sort_values('quote_available_ns').reset_index(drop=True)
    left=ev.sort_values('entry_ns').copy()
    joined=pd.merge_asof(left,rt,left_on='entry_ns',right_on='quote_available_ns',
                         direction='backward',allow_exact_matches=True)
    age=(joined.entry_ns-joined.quote_available_ns)/MINUTE_NS
    ready=(age>=0)&(age<=max_age_minutes)
    ready &= joined[[f'return_{i}m_pct' for i in (5,15,60)]].notna().all(axis=1)
    for col in ('return_5m_pct','return_15m_pct','return_60m_pct'):
        joined[source_id+'_'+col]=joined[col].where(ready)
    joined['macro_ready']=ready.fillna(False)
    joined['macro_proxy_source']=source_id
    joined['macro_source_kind']='INDEX_CFD_PROXY' if source_id==DXY_PROXY_SOURCE else 'TREASURY_FUTURES_PRICE_PROXY'
    joined['is_official_ice_dxy']=False
    joined['is_cash_treasury_yield']=False
    joined=joined.drop(columns=[c for c in ['return_5m_pct','return_15m_pct',
                                           'return_60m_pct','quote_available_ns',
                                           'last_quote_open_ns'] if c in joined.columns])
    return joined.sort_index().reset_index(drop=True)

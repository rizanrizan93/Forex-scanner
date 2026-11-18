"""Unit tests for R7 macro as-of timeline; no external market data implied."""
import numpy as np
import pandas as pd
import pytest
from research.zone_rebound.xau_r7_macro_asof import (
    DXY_PROXY_SOURCE,EXECUTION_AUTHORITY,EXECUTION_INFLUENCE,
    normalize_quote_m1,asof_proxy_features)

def quotes():
    ts=pd.date_range('2025-06-02T00:00:00Z',periods=220,freq='min')
    x=100.0+np.arange(len(ts))*.01
    return pd.DataFrame({'timestamp':ts.strftime('%Y-%m-%dT%H:%M:%S%z'),
                         'open':x,'high':x+.02,'low':x-.02,'close':x})

def event(t):
    return pd.DataFrame({'entry_ns':[pd.Timestamp(t).value]})

def test_reject_non_timestamp_and_unsupported_instrument():
    d=quotes()
    with pytest.raises(ValueError,match='UNAPPROVED_MACRO_SOURCE'):
        normalize_quote_m1(d,'OFFICIAL_DXY')
    d['timestamp']=d.timestamp.str.slice(0,19)
    with pytest.raises(ValueError,match='UTC_OFFSET'):
        normalize_quote_m1(d,DXY_PROXY_SOURCE)

def test_asof_uses_only_closed_plus_delay_m1():
    d=quotes()
    t=pd.Timestamp('2025-06-02T02:00:00Z')
    left=asof_proxy_features(d,event(t),availability_delay_minutes=1)
    assert bool(left.macro_ready.iloc[0])
    edited=d.copy()
    m=edited.timestamp.str.contains('01:59:00')
    edited.loc[m,['open','high','low','close']]=[200,201,199,200]
    same=asof_proxy_features(edited,event(t),availability_delay_minutes=1)
    column=DXY_PROXY_SOURCE+'_return_5m_pct'
    assert left[column].iloc[0]==same[column].iloc[0]
    # 01:59-02:00 bar is not eligible until 02:01 with 1m lag:
    later=asof_proxy_features(edited,event(t+pd.Timedelta(minutes=1)),availability_delay_minutes=1)
    assert later[column].iloc[0]!=left[column].iloc[0]

def test_gapped_input_fails_closed():
    d=quotes()
    d=d.loc[~d.timestamp.str.contains('01:40:00')]
    x=asof_proxy_features(d,event('2025-06-02T02:00:00Z'))
    assert not bool(x.macro_ready.iloc[0])
    assert np.isnan(x[DXY_PROXY_SOURCE+'_return_60m_pct'].iloc[0])

def test_stale_fails_closed():
    d=quotes().iloc[:130]
    x=asof_proxy_features(d,event('2025-06-02T03:00:00Z'))
    assert not bool(x.macro_ready.iloc[0])

def test_never_labels_as_ice_dxy_or_cash_yield():
    x=asof_proxy_features(quotes(),event('2025-06-02T02:00:00Z'))
    assert not bool(x.is_official_ice_dxy.iloc[0])
    assert not bool(x.is_cash_treasury_yield.iloc[0])
    assert EXECUTION_AUTHORITY is False and EXECUTION_INFLUENCE is False

def test_reject_duplicate_event_and_non_monotonic_delay():
    e=event('2025-06-02T02:00:00Z')
    with pytest.raises(ValueError,match='NON_UNIQUE_EVENT'):
        asof_proxy_features(quotes(),pd.concat([e,e],ignore_index=True))
    with pytest.raises(ValueError,match='AVAILABILITY_DELAY'):
        asof_proxy_features(quotes(),e,availability_delay_minutes=-1)

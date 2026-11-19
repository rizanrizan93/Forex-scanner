"""Deterministic synthetic tests only, NOT trading accuracy/replay."""
import numpy as np
import pandas as pd
import pytest
from fx_scanner.rejection_v2_research import completed, calculate

def mock_m1(size=12000, side=1, end='2026-11-19 03:15:00+00:00'):
    close_at=pd.Timestamp(end)
    ix=pd.date_range(end=close_at-pd.Timedelta(minutes=1),periods=size,freq='min',tz='UTC')
    base=4000+side*np.arange(size)*.006+.06*np.sin(np.arange(size)*.12)
    op=base-.01*side
    return pd.DataFrame(dict(open=op,close=base,high=np.maximum(op,base)+.04,
                             low=np.minimum(op,base)-.04),index=ix)

def test_complete_bar_excludes_partial_and_missing():
    d=mock_m1(500,end='2026-11-19 03:13:00+00:00')
    m=completed(d,5,pd.Timestamp('2026-11-19 03:13+00:00'))
    assert m.index[-1]==pd.Timestamp('2026-11-19 03:10+00:00')
    one=d.drop(pd.Timestamp('2026-11-19 03:07+00:00'))
    m2=completed(one,5,pd.Timestamp('2026-11-19 03:13+00:00'))
    assert pd.Timestamp('2026-11-19 03:10+00:00') not in m2.index

@pytest.mark.parametrize('side,expected',[(1,'BUY'),(-1,'SELL')])
def test_bias_and_both_side_levels(side,expected):
    d=mock_m1(side=side)
    r=calculate(d,now='2026-11-19 03:15+00:00',
                bid=float(d.close.iloc[-1])-.05,ask=float(d.close.iloc[-1])+.05,
                quote_at='2026-11-19 03:15+00:00')
    assert r['h1_bias']==r['h4_bias']==r['bias']==expected
    assert {z['side'] for z in r['zones']}=={'BUY','SELL'}
    assert len(r['zones'])==6 and r['quote_valid']

def test_forming_candle_rejected():
    with pytest.raises(ValueError,match='Forming'):
        calculate(mock_m1(),now='2026-11-19 03:14:30+00:00')

def test_stale_and_timezone_guard():
    d=mock_m1()
    with pytest.raises(ValueError,match='stale'):
        calculate(d,now='2026-11-19 03:18:00+00:00')
    d.index=d.index.tz_localize(None)
    with pytest.raises(ValueError,match='timezone'):
        calculate(d,now='2026-11-19 03:15:00+00:00')

@pytest.mark.parametrize('side,expected',[(1,'BUY'),(-1,'SELL')])
def test_early_rejection_before_m5_close(side,expected):
    d=mock_m1(side=side,end='2026-11-19 03:13:00+00:00')
    r0=calculate(d,now='2026-11-19 03:13+00:00')
    level=next(z['price'] for z in r0['zones'] if z['side']==expected and z['name']=='M5 EMA20')
    if side==1:
        d.loc[d.index[-1],['open','high','low','close']]=[level+.03,level+.20,level-.40,level+.15]
        bid,ask=level+.14,level+.16
    else:
        d.loc[d.index[-1],['open','high','low','close']]=[level-.03,level+.40,level-.20,level-.15]
        bid,ask=level-.16,level-.14
    r=calculate(d,now='2026-11-19 03:13+00:00',bid=bid,ask=ask,
                quote_at='2026-11-19 03:13+00:00')
    assert r['last_closed_m5']=='2026-11-19T03:10:00+00:00'
    assert any(z['stage']=='EARLY REJECTION' for z in r['zones'] if z['side']==expected)

def test_no_quote_never_entry_candidate():
    r=calculate(mock_m1(),now='2026-11-19 03:15+00:00')
    assert not r['quote_valid']
    assert all(z['entry']!='EARLY ENTRY CANDIDATE' for z in r['zones'])

def test_incomplete_h4_is_unknown_not_imagined():
    d=mock_m1(3000)
    r=calculate(d,now='2026-11-19 03:15+00:00')
    assert r['h4_bias']=='UNAVAILABLE'
    assert r['bias']=='WAIT'

def test_old_quote_never_entry_candidate():
    d=mock_m1()
    r=calculate(d,now='2026-11-19 03:15+00:00',
                bid=float(d.close.iloc[-1])-.05,ask=float(d.close.iloc[-1])+.05,
                quote_at='2026-11-19 03:14:00+00:00')
    assert not r['quote_valid']
    assert all(z['entry']!='EARLY ENTRY CANDIDATE' for z in r['zones'])

@pytest.mark.parametrize('side,expected',[(1,'BUY'),(-1,'SELL')])
def test_early_entry_candidate_before_m5_close(side,expected):
    d=mock_m1(side=side,end='2026-11-19 03:13:00+00:00')
    r0=calculate(d,now='2026-11-19 03:13+00:00')
    level=next(z['price'] for z in r0['zones'] if z['side']==expected and z['name']=='M5 EMA20')
    if side==1:
        d.loc[d.index[-1],['open','high','low','close']]=[level+.01,level+.055,level-.08,level+.025]
        bid,ask=level+.018,level+.028
    else:
        d.loc[d.index[-1],['open','high','low','close']]=[level-.01,level+.08,level-.055,level-.025]
        bid,ask=level-.028,level-.018
    r=calculate(d,now='2026-11-19 03:13+00:00',bid=bid,ask=ask,
                quote_at='2026-11-19 03:13+00:00')
    assert r['last_closed_m5']=='2026-11-19T03:10:00+00:00'
    assert any(z['entry']=='EARLY ENTRY CANDIDATE' for z in r['zones'] if z['side']==expected)

@pytest.mark.parametrize('side,expected',[(1,'BUY'),(-1,'SELL')])
def test_optional_retest_after_early_rejection(side,expected):
    d=mock_m1(side=side,end='2026-11-19 03:13+00:00')
    r0=calculate(d,now='2026-11-19 03:13+00:00')
    level=next(z['price'] for z in r0['zones'] if z['side']==expected and z['name']=='M5 EMA20')
    if side==1:
        d.loc[d.index[-2],['open','high','low','close']]=[level+.015,level+.060,level-.08,level+.03]
        d.loc[d.index[-1],['open','high','low','close']]=[level+.015,level+.080,level-.005,level+.045]
        bid,ask=level+.030,level+.040
    else:
        d.loc[d.index[-2],['open','high','low','close']]=[level-.015,level+.08,level-.060,level-.03]
        d.loc[d.index[-1],['open','high','low','close']]=[level-.015,level+.005,level-.080,level-.045]
        bid,ask=level-.040,level-.030
    r=calculate(d,now='2026-11-19 03:13+00:00',bid=bid,ask=ask,
                quote_at='2026-11-19 03:13+00:00')
    assert any(z['entry']=='RETEST RECLAIM CANDIDATE' for z in r['zones'] if z['side']==expected)

def test_structural_and_ema_watch_levels_both_directions():
    r=calculate(mock_m1(),now='2026-11-19 03:15+00:00')
    for side in ('BUY','SELL'):
        names=[z['name'] for z in r['zones'] if z['side']==side]
        assert any('EMA' in name for name in names)
        assert any('SUPPORT' in name or 'RESISTANCE' in name for name in names)

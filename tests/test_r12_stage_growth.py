"""Meaningful causality and symmetric execution checks for research R12 only."""
from pathlib import Path
import importlib.util
import numpy as np
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('r12_growth',ROOT/'research/r12_stage_growth/engine.py')
r12=importlib.util.module_from_spec(spec);spec.loader.exec_module(r12)

def fixture(day='2024-01-02',side=1):
    ix=pd.date_range(pd.Timestamp(day,tz='UTC')-pd.Timedelta(days=1),periods=600,freq='5min')
    m=pd.DataFrame(dict(o=100.,h=101.,l=99.,c=100.,atr=1.,n=5,trend=float(side),h1=float(side),q_o=100.,q_h=101.,q_l=99.,q_c=100.,q_n=15,q_ema=100.),index=ix)
    localstart=pd.Timestamp(day+' 08:00',tz='Europe/London').tz_convert('UTC')
    j=m.index.get_loc(localstart+pd.Timedelta('35min'))
    candles=np.array([[100,102.2,100,102],[102,102.5,101.5,102],[101,102,100.9,101.8]])
    if side==-1:
        candles=200-candles; candles[:,[1,2]]=candles[:,[2,1]]
    m.iloc[j:j+3,m.columns.get_indexer(['o','h','l','c'])]=candles
    return m,j

def test_buy_sell_symmetry_and_delayed_retest():
    for side in (1,-1):
        m,j=fixture(side=side)
        e=r12.events(m,'OR30_LONDON_H4',side,12,12)
        assert len(e)==1 and e[0][0]==j+2
        assert r12.events(m.iloc[:j+2],'OR30_LONDON_H4',side,12,12)==[]
        assert r12.events(m,'OR30_LONDON_BOTH',-side,12,12)==[]

def test_london_dst_and_incomplete_opening_range():
    m,j=fixture(day='2024-07-02')
    assert m.index[j].hour==7  # 08:35 BST, not UTC 08:35
    assert r12.events(m,'OR30_LONDON_H4',1,12,12)[0][0]==j+2
    m.iloc[j-4,m.columns.get_loc('n')]=4
    assert not r12.events(m,'OR30_LONDON_H4',1,12,12)

def test_features_cannot_read_future_m1():
    n=40000;ix=pd.date_range('2024-01-01',periods=n,freq='min',tz='UTC')
    rng=np.random.default_rng(19);c=2000+np.cumsum(rng.normal(0,.2,n))
    d=pd.DataFrame(dict(bo=c,bh=c+.3,bl=c-.3,bc=c,ao=c+.2,ah=c+.5,al=c-.1,ac=c+.2),index=ix)
    cut=30000
    full=r12.features(d);prefix=r12.features(d.iloc[:cut]);at=prefix.index[prefix.index<=d.index[cut]]
    pd.testing.assert_frame_equal(prefix.loc[at],full.loc[at],check_exact=False,atol=1e-10)

def test_sizing_never_rounds_up_to_minimum_or_ignores_margin():
    row=dict(entry_minute=1,exit_minute=2,exit_utc='2024-01-01T00:02Z',risk_per_oz=2.,commission_usd=.12,slippage_per_side=.1,entry=2000.,net_usd_1oz=10.)
    assert r12.wallet([row])['ending_cash']==130
    assert r12.wallet([row],125)['ending_cash']==135
    assert r12.wallet([{**row,'risk_per_oz':10.}])['filled']==0
    assert r12.wallet([{**row,'entry':30000.}])['filled']==0

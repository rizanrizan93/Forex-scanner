"""R32L source-timeframe failed breakout + liquidity sweep contracts.

SYNTHETIC test fixtures only. These tests are not historical strategy results.
"""
from pathlib import Path
import sys
import numpy as np
import pandas as pd

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import research_r32l_source_tf_sweep as r32
import research_r31_high_coverage_precision as r31


def sample(n=420):
    idx=pd.date_range("2017-01-02",periods=n,freq="h",tz="UTC")
    c=np.full(n,100.2)
    a=pd.DataFrame({"o":np.full(n,100.1),"h":np.full(n,101.),
                    "l":np.full(n,99.),"c":c},index=idx)
    for i in (120,170,220,270):
        a.iloc[i,a.columns.get_loc("l")]=97.7
        a.iloc[i,a.columns.get_loc("c")]=100.5
        a.iloc[i,a.columns.get_loc("o")]=99.9
        a.iloc[i+1,a.columns.get_loc("c")]=101.4
        a.iloc[i+1,a.columns.get_loc("h")]=101.6
    return a


def test_sweep_is_causal_source_tf_not_m5():
    d=sample()
    feat=r31.r30.prepare(d)
    events=r32.liquidity_sweep_events(d,feat,"H1")
    assert events
    assert all(x["signal_index"]>=x["formation"] for x in events)
    assert all(x["entry_index"]>x["signal_index"] for x in events)
    assert all(x["stop"]<x["entry"] if x["side"]==1
               else x["stop"]>x["entry"] for x in events)
    assert any(x["confirmation"]=="CLOSED_SWEEP_RECLAIM" for x in events)
    assert r32.CONFIGS==4096 and r32.MODELS==256 and r32.EXIT==8


def test_no_liquidity_sweep_gives_no_trade():
    idx=pd.date_range("2018-01-01",periods=320,freq="h",tz="UTC")
    d=pd.DataFrame({"o":100.,"h":101.,"l":99.,"c":100.},index=idx)
    assert r32.liquidity_sweep_events(d,r31.r30.prepare(d),"H1")==[]


def test_gap_open_beyond_stop_gets_worse_open_price():
    d=sample()
    events=[{"entry_index":100,"entry":100.,"side":1,
             "stop":99.,"risk":1.,"signal_index":99}]
    d.iloc[100,d.columns.get_loc("o")]=98.5
    p,idx=r32.liquidity_outcomes(d,events)
    assert p[0,0]==(-1.5-r31.BASE_COST)
    assert idx[0,0]==100


def test_six_axes_and_256_proxy_voters():
    d=sample()
    f=r31.r30.prepare(d)
    e=r32.liquidity_sweep_events(d,f,"H1")
    assert len(r32.liquidity_axes(e))==6
    assert all(len(x)==4 for x in r32.liquidity_axes(e))
    assert len(r31.direction_votes(d,f,e))==256
    assert all(row["sweep_lookback"] in (4,8,16) for row in e)

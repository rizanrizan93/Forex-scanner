"""R31 validation: deterministic causal backtest and zero order authority.

Fixtures are SYNTHETIC; no reported numbers from these tests are market alpha.
"""
from pathlib import Path
import sys
import numpy as np
import pandas as pd
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import research_r31_high_coverage_precision as r31


def sample_frame(n=480):
    ix=pd.date_range("2018-01-01",periods=n,freq="h",tz="UTC")
    x=np.arange(n)
    c=1700+x*.08+np.sin(x/8)
    return pd.DataFrame({"o":c-.04,"h":c+.5,"l":c-.6,"c":c},index=ix)


def test_256_direction_models_and_4096_zones_eight_exit_policies():
    d=sample_frame()
    f=r31.r30.prepare(d)
    events=[{"signal_index":i,"side":1 if i%2 else -1,
             "base":1+i%3,"displacement":.8,"body":.4,
             "bos":.25,"width":1.2,"vol":.6,
             "retest_lag":3,"rejection":.1}
            for i in range(85,170)]
    m=r31.direction_votes(d,f,events)
    axes=r31.zone_axes(events)
    assert len(m)==256 and all(v.dtype==np.bool_ for v in m)
    assert len(axes)==6 and all(len(x)==4 for x in axes)
    assert r31.ZONE_CONFIGS==4096 and r31.EXIT_VARIANTS==8
    assert 4*r31.DIRECTION_MODELS*r31.ZONE_CONFIGS*r31.EXIT_VARIANTS==33554432


def test_fully_closed_prefix_indicators_are_not_future_looking():
    d=sample_frame()
    a=r31.r30.prepare(d)
    modified=d.copy()
    modified.loc[modified.index[310]:,["o","h","l","c"]]+=150
    b=r31.r30.prepare(modified)
    i=270
    assert a["rsi"][i]==pytest.approx(b["rsi"][i])
    assert a["atr"][i]==pytest.approx(b["atr"][i])
    assert a["ema"][21][i]==pytest.approx(b["ema"][21][i])


def test_stop_first_tie_and_costs_are_conservative():
    ix=pd.date_range("2024-01-01",periods=60,freq="h",tz="UTC")
    d=pd.DataFrame({"o":100.,"h":100.3,"l":99.7,"c":100.},index=ix)
    d.loc[ix[25],"h"]=104.
    d.loc[ix[25],"l"]=96.
    e=[{"entry_index":25,"year":2024,"side":1,"stop":98.,"risk":2.,
        "entry":100.,"signal_index":24}]
    pnl,ex=r31.outcome_matrix(d,e)
    np.testing.assert_allclose(pnl[:,0],-2.-r31.BASE_COST)
    assert np.all(ex[:,0]==25)


def test_metrics_no_overlap_and_year_purge():
    ix=pd.date_range("2020-12-28",periods=100,freq="D",tz="UTC")
    d=pd.DataFrame({"o":100.,"h":101.,"l":99.,"c":100.},index=ix)
    ev=[{"entry_index":2,"signal_index":1,"side":1},
        {"entry_index":4,"signal_index":3,"side":1},
        {"entry_index":5,"signal_index":4,"side":1}]
    pnl=np.zeros((8,3));pnl[0]=[100.,2.,-1.]
    exits=np.zeros((8,3),dtype=int);exits[:]=[5,7,8]
    m=r31.report_metrics(ev,np.ones(3,bool),"H1",d,pnl,exits,0,2020,2020)
    assert m["n"]==0  # all exits mature in 2021
    m=r31.report_metrics(ev,np.ones(3,bool),"H1",d,pnl,exits,0,2021,2021)
    assert m["n"]==1  # only the first 2021 trade survives overlap guard


def test_candidate_floor_requires_positive_expectancy_pf_and_annual_support():
    annual={str(y):{"n":30,"net_usd_oz":2.,"win_rate":.60}
            for y in range(2021,2024)}
    ok={"n":90,"win_rate":.59,"wilson_lower95":.5,"net_usd_oz":10.,
        "expectancy_usd_oz":.11,"profit_factor":1.3,"annual":annual}
    assert r31._passes(ok,"H1",.55)
    assert not r31._passes(ok,"H1",.60)
    assert not r31._passes({**ok,"profit_factor":.99},"H1",.55)
    assert not r31._passes({**ok,"expectancy_usd_oz":-.2},"H1",.55)
    assert not r31._passes({**ok,"n":5},"H1",.55)


def test_small_synthetic_sweep_never_claims_live_or_frozen_model_parity(tmp_path,monkeypatch):
    d=sample_frame(1000)
    d.index=pd.date_range("2012-01-01",periods=len(d),freq="6D",tz="UTC")
    events=[]
    for i in range(85,985,5):
        events.append({
            "formation":i-2,"signal_index":i-1,"entry_index":i,
            "year":d.index[i].year,"side":1,"base":1,
            "displacement":1.2,"body":.6,"bos":.4,"width":.5,
            "vol":.6,"retest_lag":2,"rejection":.2,
            "entry":100.,"stop":99.,"risk":1.})
    monkeypatch.setattr(r31.r30,"load",lambda tf:(d,{"2012":"test-only"}))
    monkeypatch.setattr(r31.r30,"prepare",lambda d:{"test":True})
    monkeypatch.setattr(r31,"events_from_closed_ohlc",lambda d,f,tf:events)
    monkeypatch.setattr(r31,"direction_votes",lambda d,f,e:[
        np.ones(len(e),dtype=bool)]*256)
    monkeypatch.setattr(r31,"zone_axes",lambda e:[
        [np.ones(len(e),dtype=bool)]*4 for _ in range(6)])
    def fake_outcomes(d,e):
        n=len(e)
        p=np.tile(np.where(np.arange(n)%3==0,-1.,2.),(8,1))
        ix=np.tile([x["entry_index"]+1 for x in e],(8,1))
        return p,ix
    monkeypatch.setattr(r31,"outcome_matrix",fake_outcomes)
    monkeypatch.setattr(r31,"OUT",tmp_path)
    result=r31.sweep("H1",model_start=0,models=2,caps=4)
    assert result["actual_evaluations"]==64
    assert result["execution_authority"] is False
    assert result["frozen_model_parity"] is False
    assert result["source_tf_retest_events"]==len(events)
    assert (tmp_path/"r31-H1-models-0.json").exists()

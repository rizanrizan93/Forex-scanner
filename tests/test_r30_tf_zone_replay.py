"""Isolated causal sanity tests; synthetic candles are NEVER market results."""
from __future__ import annotations
from pathlib import Path
import sys
import numpy as np
import pandas as pd
import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
import research_tf_zone_direction_mega as r30


def candles(n=300):
    idx=pd.date_range("2021-01-01",periods=n,freq="1h",tz="UTC")
    x=np.arange(n)
    c=1700+x*.1+np.sin(x/5)
    return pd.DataFrame({"o":c-.1,"h":c+.6,"l":c-.7,"c":c},index=idx)


def test_128_direction_variants_and_16384_zone_configs():
    d=candles()
    f=r30.prepare(d)
    ev=[{"formation":i,"side":1 if i%2 else -1,"base":1+(i%3),
         "displacement":.9,"body":.55,"bos":.2,"width":.7,
         "vol":.6,"retest_lag":3} for i in range(90,180)]
    assert len(r30.model_votes(d,f,ev))==128
    axes=r30.zone_axes(ev)
    assert len(axes)==7 and all(len(axis)==4 for axis in axes)
    assert r30.MODEL_COUNT*r30.ZONE_COUNT==2097152
    assert all(v.dtype==np.bool_ for v in r30.model_votes(d,f,ev))


def test_price_features_are_strict_prefix_causal():
    d=candles(250)
    q=d.copy()
    q.loc[q.index[190]:,"c"]+=100
    q.loc[q.index[190]:,"h"]+=100
    q.loc[q.index[190]:,"o"]+=100
    q.loc[q.index[190]:,"l"]+=100
    a=r30.prepare(d);b=r30.prepare(q)
    i=170
    assert a["atr"][i]==pytest.approx(b["atr"][i])
    assert a["rsi"][i]==pytest.approx(b["rsi"][i])
    assert a["ema"][8][i]==pytest.approx(b["ema"][8][i])
    assert a["mom"][13][i]==pytest.approx(b["mom"][13][i])


def test_selection_purges_outcomes_crossing_year_boundary():
    events=[{"year":2020,"exit_year":2021,"entry_index":12,
             "exit_index":15,"net":100},
            {"year":2020,"exit_year":2020,"entry_index":16,
             "exit_index":17,"net":-2},
            {"year":2021,"exit_year":2021,"entry_index":22,
             "exit_index":23,"net":4}]
    m=r30.metrics(events,np.ones(3,bool),2012,2020)
    assert m["n"]==1 and m["net_usd_oz"]==-2


def test_overlap_guard_and_cost_stress_are_explicit():
    ev=[{"year":2025,"exit_year":2025,
         "entry_index":1,"exit_index":4,"net":3},
        {"year":2025,"exit_year":2025,
         "entry_index":2,"exit_index":3,"net":5},
        {"year":2025,"exit_year":2025,
         "entry_index":5,"exit_index":8,"net":-1}]
    x=r30.metrics(ev,np.ones(3,bool),2024,2026,overlap_guard=True,
                  cost_extra=.8)
    assert x["n"]==2
    assert x["net_usd_oz"]==pytest.approx(.4)
    assert x["max_additive_drawdown_usd_oz"]>=0


def test_small_synthetic_sweep_is_marked_research_only(monkeypatch,tmp_path):
    from datetime import datetime
    # Synthetic 18 events over 2012-2026, never emitted as market evidence.
    d=candles(300)
    d.index=pd.date_range("2012-01-01",periods=len(d),freq="W",tz="UTC")
    yy=list(range(2012,2027))
    events=[]
    for year in yy:
        for q in range(3):
            i=(year-2012)*3+q+60
            events.append({
                "formation":i,"entry_index":i+1,"exit_index":i+2,
                "year":year,"side":1 if q%2 else -1,
                "base":1+q,"displacement":1.1,"body":.6,
                "bos":.3,"width":.5,"vol":.7,"retest_lag":1,
                "net":2 if q%2 else -1,"risk":5.,
            })
    monkeypatch.setattr(r30,"load",lambda tf:(d,{str(y):"synthetic" for y in yy}))
    monkeypatch.setattr(r30,"raw_events",lambda d,f,tf:events)
    monkeypatch.setattr(r30,"model_votes",lambda d,f,e:[np.ones(len(e),bool)]*128)
    monkeypatch.setattr(r30,"OUT",tmp_path)
    result=r30.sweep("W1",cap=4,models=2,model_start=0)
    assert result["parameter_combinations_actually_evaluated"]==8
    assert result["direction_model_variants"]==2
    assert result["execution_authority"] is False
    assert result["not_original_frozen_model_parity"] is True


def test_missing_history_fails_instead_of_filling_synthetic_2012(monkeypatch):
    monkeypatch.setattr(r30.glob,"glob",lambda p:[])
    with pytest.raises(RuntimeError,match="INCOMPLETE_2012_2026_SHARDS"):
        r30.load("H1")

"""R29.5 risk-tail and conservative-lag exploratory macro safety gates."""
import numpy as np
import pandas as pd
import pytest

import r295_tailrisk_macro as r295
import r29_direction60_walkforward as base
import r292_magnitude_regime_expansion as r292
from r10_million import ohlc_indicators


def candles(n=220,freq="h"):
    rng=np.random.default_rng(295)
    c=3500+np.cumsum(rng.normal(0,4,n))
    o=np.r_[c[0],c[:-1]]
    hi=np.maximum(c,o)+rng.uniform(.5,1.5,n)
    lo=np.minimum(c,o)-rng.uniform(.5,1.5,n)
    idx=pd.date_range("2026-01-01",periods=n,freq=freq,tz="UTC")
    d=pd.DataFrame({"o":o,"h":hi,"l":lo,"c":c},index=idx)
    return d,ohlc_indicators(d)


def test_loss_tail_changes_selection_without_using_test_fold():
    r295.MODE="tail_guard"
    r292.PRESET="precision"
    y=np.array([1]*7+[0]*5,dtype=np.int8)
    mask=np.array([True]*7+[False]*5)
    delta=np.array([2.,2.,2.,2.,2.,2.,-1.,-3.,-2.,-2.,-3.,-3.])
    half=np.array([1]*4+[2]*8)
    q=r295.valuation(y,mask,"BUY",delta,half,6)
    assert q["n"]==7
    assert q["validation_half_year_supported"] is True
    assert q["average_losing_signal_net_usd_oz"]<0
    assert q["expected_shortfall20_usd_oz"]<0
    assert r295.rank(q) is not None


def test_sided_bos_and_session_gates_are_causal_shapes():
    d,z=candles()
    times=d.index+pd.Timedelta(hours=1)
    for side in ("BUY","SELL"):
        q=r295.gates("1h",z,times,side)
        for n in ("trend_clv","sweep_and_structure","ny_open_displacement"):
            assert n in q
            assert q[n].shape==(len(d),)
            assert q[n].dtype==bool


def test_macro_features_only_after_lagged_release(monkeypatch):
    d,z=candles(220,freq="D")
    idx=d.index+pd.Timedelta(days=1)
    source=pd.DataFrame({"DGS2_5":np.linspace(1,0,len(d)),
                         "DGS10_5":np.linspace(.5,0,len(d)),
                         "DTWEXBGS_5":np.linspace(0,1,len(d))},index=idx)
    monkeypatch.setattr(r295,"daily_macro",lambda:([source],{"source":"test-pit-proxy"}))
    r295.MACRO=None
    try:
        groups=r295.feature_groups("1D",d,z)
        assert "lagged_macro" in groups
        assert groups["lagged_macro"].index.equals(d.index)
        assert groups["lagged_macro"].iloc[-1]["DGS2_5"]==pytest.approx(0)
        gate=r295.gates("1D",z,idx,"BUY")
        assert "yield_2y10y_confluence" in gate
        assert "broad_dollar_confluence" in gate
        assert gate["yield_2y10y_confluence"].dtype==bool
    finally:
        r295.MACRO=None
        r295.MACRO_MANIFEST=None


def test_research_runner_preserves_original_baselines(monkeypatch,tmp_path):
    monkeypatch.setattr(base,"ROOT",tmp_path)
    old=(base.feature_groups,base.gates,base.fold,
         base.MINVAL,base.CUTS,base.ENGINES,base.STRATEGY,
         r292.valuation,r292.policy_rank,r292.PRESET)
    def stub(tf):
        assert base.feature_groups is r295.feature_groups
        assert base.gates is r295.gates
        assert base.fold is r292.fold
        return {"passes_all_predeclared_gates":False,
                "coverage":0,"aggregate":{"BUY":{},"SELL":{}},
                "limitations":[]}
    monkeypatch.setattr(base,"run",stub)
    for mode in ("tail_guard","coverage_guard"):
        v=r295.run("4h",mode)
        assert v["variant"]=="R29.5 "+mode
        assert (tmp_path/f"r295-{mode}-4h.json").exists()
        now=(base.feature_groups,base.gates,base.fold,
             base.MINVAL,base.CUTS,base.ENGINES,base.STRATEGY,
             r292.valuation,r292.policy_rank,r292.PRESET)
        assert now==old


def test_no_orders_and_no_false_pit_claim():
    from pathlib import Path
    s=(Path(__file__).resolve().parents[1]/
       "scripts/r295_tailrisk_macro.py").read_text()
    assert "NOT a verified point-in-time" in s
    assert "base.fold=r292.fold" in s
    for forbidden in ("place_order(","execute_market_order(",
                      "bridge/order","streamlit","git push"):
        assert forbidden not in s

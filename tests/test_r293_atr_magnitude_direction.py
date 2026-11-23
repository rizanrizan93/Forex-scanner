"""R29.3 magnitude-regression research safety and determinism checks."""
from pathlib import Path
import numpy as np
import pandas as pd
import pytest

import r293_atr_magnitude_direction as r293
import r29_direction60_walkforward as base
from r10_million import ohlc_indicators


def candles():
    rng=np.random.default_rng(293)
    c=3600+np.cumsum(rng.normal(0,3,240))
    o=np.r_[c[0],c[:-1]]
    h=np.maximum(c,o)+rng.uniform(.5,1.5,len(c))
    l=np.minimum(c,o)-rng.uniform(.5,1.5,len(c))
    idx=pd.date_range("2026-07-01",periods=len(c),freq="h",tz="UTC")
    d=pd.DataFrame({"o":o,"h":h,"l":l,"c":c},index=idx)
    return d,ohlc_indicators(d)


def test_training_target_never_reads_unclosed_or_future_bar_for_a_feature():
    d,z=candles()
    label=r293.training_target(d,z)
    assert np.isnan(label[-1])
    assert np.isfinite(label[:-1]).all()
    for i in (90,160,220):
        sub=d.iloc[:i]
        q=ohlc_indicators(sub)
        lab=r293.training_target(sub,q)
        np.testing.assert_allclose(label[:i-1],lab[:-1],
                                   rtol=1e-10,atol=1e-10,equal_nan=True)
        assert np.isnan(lab[-1])


def test_half_year_support_prevents_single_session_overfit():
    r293.VARIANT="precision"
    y=np.array([1]*10+[0]*10,dtype=np.int8)
    early=np.array([1]*10+[2]*10)
    delta=np.array([3.]*10+[-2.]*10)
    onlyfirst=np.array([True]*9+[False]*11)
    metric=r293.val_stats(y,onlyfirst,"BUY",delta,early,8)
    assert metric["accuracy"]==1.
    assert metric["half_year_supported"] is False
    assert metric["validation_mean_net_usd_oz"]>0


def test_precision_ranking_prefers_positive_payoff_with_support():
    r293.VARIANT="precision"
    a={"accuracy":.62,"half_year_supported":True,
       "validation_mean_net_usd_oz":.7,
       "validation_p10_net_usd_oz":-1.2,"wilson_lower95":.53,"coverage":.09}
    b={**a,"accuracy":.9,"validation_mean_net_usd_oz":-2.0,
       "wilson_lower95":.75}
    assert r293.ranking(a)>r293.ranking(b)


def test_fixed_variants_restore_prior_research(monkeypatch,tmp_path):
    monkeypatch.setattr(base,"ROOT",tmp_path)
    old=(base.feature_groups,base.gates,base.fold,
         base.MINVAL,base.ENGINES,base.CUTS,base.STRATEGY)
    def fake(tf):
        assert base.fold is r293.fold
        assert base.feature_groups is r293.r292.feature_groups
        assert base.gates is r293.r292.gates
        return {"passes_all_predeclared_gates":False,
                "coverage":0,"aggregate":{"BUY":{},"SELL":{}},
                "limitations":[]}
    monkeypatch.setattr(base,"run",fake)
    for variant in ("precision","coverage"):
        a=r293.run("4h",variant)
        assert a["variant"]=="R29.3 "+variant
        assert (tmp_path/f"r293-{variant}-4h.json").exists()
        now=(base.feature_groups,base.gates,base.fold,
             base.MINVAL,base.ENGINES,base.CUTS,base.STRATEGY)
        assert now==old


def test_research_never_touches_cbot_or_order_execution():
    s=(Path(__file__).resolve().parents[1]/
       "scripts/r293_atr_magnitude_direction.py").read_text()
    assert "base.split_masks(times,valid,year)" in s
    for token in ("place_order(", "execute_market_order(", "streamlit",
                  "git push", "bootstrap125/order"):
        assert token not in s

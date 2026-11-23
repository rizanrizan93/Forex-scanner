"""R29.2 validation-only improvement and no-lookahead safety contracts."""
import numpy as np
import pandas as pd
import pytest

import r292_magnitude_regime_expansion as r292
import r29_direction60_walkforward as base
from r10_million import ohlc_indicators


def sample(n=220):
    rng=np.random.default_rng(292)
    c=3600+np.cumsum(rng.normal(0,3,n))
    o=np.r_[c[0],c[:-1]]
    h=np.maximum(c,o)+rng.uniform(.4,2,n)
    l=np.minimum(c,o)-rng.uniform(.4,2,n)
    idx=pd.date_range("2026-07-01",periods=n,freq="h",tz="UTC")
    d=pd.DataFrame({"o":o,"h":h,"l":l,"c":c},index=idx)
    return d,ohlc_indicators(d)


def test_causal_features_identical_on_completed_prefixes():
    d,z=sample()
    full=r292.feature_groups("4h",d,z)
    for n in (120,180,220):
        q=d.iloc[:n]
        original=ohlc_indicators(q)
        prefix=r292.feature_groups("4h",q,original)
        assert set(full)==set(prefix)
        for key in full:
            np.testing.assert_allclose(
                full[key].iloc[n-1].to_numpy(float),
                prefix[key].iloc[-1].to_numpy(float),
                equal_nan=True,atol=1e-10,rtol=1e-10,
            )


def test_all_event_gates_are_completed_bar_only_and_sided():
    d,z=sample()
    for tf in ("1h","4h","1D"):
        times=d.index+pd.Timedelta(hours=4 if tf=="4h" else 1)
        for side in ("BUY","SELL"):
            g=r292.gates(tf,z,times,side)
            for name in ("trend_strong","trend_compress","break_hold",
                         "counter_reversal","high_vol_trend"):
                assert name in g and len(g[name])==len(d)
                assert g[name].dtype==bool


def test_validation_precision_cannot_be_substituted_by_tiny_samples():
    r292.PRESET="precision"
    y=np.array([1]*7+[0]*5,dtype=np.int8)
    mask=np.array([True]*7+[False]*5)
    valid_delta=np.array([2.]*7+[-2.]*5)
    halves=np.array([1]*4+[2]*8)
    assert r292.valuation(y,mask,"BUY",valid_delta,halves,8) is None
    metric=r292.valuation(y,mask,"BUY",valid_delta,halves,6)
    assert metric["accuracy"]==1.
    assert metric["validation_half_year_supported"] is True
    assert metric["val_net_usd_oz"]==pytest.approx(1.3,rel=1e-3)


def test_negative_net_cannot_be_ranked_top_in_precision_preset():
    r292.PRESET="precision"
    good={"accuracy":.61,"validation_half_year_supported":True,
          "val_net_usd_oz":1.0,"wilson_lower95":.50,"coverage":.1}
    bad={**good,"accuracy":.90,"val_net_usd_oz":-2.0,
         "wilson_lower95":.80}
    assert r292.policy_rank(good)>r292.policy_rank(bad)


def test_two_fixed_variants_restore_old_implementation_after_research(monkeypatch,tmp_path):
    monkeypatch.setattr(base,"ROOT",tmp_path)
    previous=(base.feature_groups,base.gates,base.fold,base.MINVAL,
              base.CUTS,base.ENGINES,base.STRATEGY)
    def fake_replay(tf):
        assert base.gates is r292.gates
        assert base.fold is r292.fold
        assert base.feature_groups is r292.feature_groups
        assert base.STRATEGY.startswith("R29_2_")
        return {"passes_all_predeclared_gates":False,
                "coverage":.0,"aggregate":{"BUY":{},"SELL":{}},
                "limitations":[]}
    monkeypatch.setattr(base,"run",fake_replay)
    for variant in ("precision","balanced"):
        result=r292.run("4h",variant)
        assert result["variant"]=="R29.2 "+variant
        assert (tmp_path/f"r292-{variant}-4h.json").exists()
        assert (base.feature_groups,base.gates,base.fold,
                base.MINVAL,base.CUTS,base.ENGINES,base.STRATEGY)==previous


def test_no_live_order_or_model_replacement_in_research_code():
    from pathlib import Path
    s=(Path(__file__).resolve().parents[1]/
       "scripts/r292_magnitude_regime_expansion.py").read_text()
    assert "R29.2" in s
    assert "base.split_masks(times,valid,year)" in s
    for token in ("place_order(", "execute_market_order(", "streamlit",
                  "bridge/order", "git push", "cTrader LIVE"):
        assert token not in s

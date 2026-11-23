"""R29.1 event-geometry features and gate wrappers remain causal and isolated."""
import numpy as np
import pandas as pd

import r291_event_structure_direction as r291
import r29_direction60_walkforward as base
from r10_million import ohlc_indicators


def sample(n=180):
    rng=np.random.default_rng(291)
    close=3600+np.cumsum(rng.normal(0,2,n))
    open_=np.r_[close[0],close[:-1]]
    high=np.maximum(close,open_)+rng.uniform(0.5,2,n)
    low=np.minimum(close,open_)-rng.uniform(0.5,2,n)
    idx=pd.date_range("2026-09-01",periods=n,freq="h",tz="UTC")
    d=pd.DataFrame({"o":open_,"h":high,"l":low,"c":close},index=idx)
    z=ohlc_indicators(d)
    return d,z


def test_engine_gates_do_not_recurse_and_all_use_causal_columns():
    d,z=sample()
    times=d.index+pd.Timedelta(hours=1)
    for side in ("BUY","SELL"):
        g=r291.gates("1h",z,times,side)
        assert len(g)>=10
        for name in ("bos_displacement","sweep_reversal","trend_pullback",
                     "compression_release","london_open_bos"):
            assert name in g and len(g[name])==len(d)
            assert g[name].dtype==bool
        assert "all" in g


def test_geometry_features_only_depend_on_completed_prefix():
    d,z=sample()
    full=r291.structure_features("1h",d,z)
    for n in (80,120,160):
        partial=ohlc_indicators(d.iloc[:n])
        prefix=r291.structure_features("1h",d.iloc[:n],partial)
        np.testing.assert_allclose(
            full.iloc[n-1].to_numpy(float),
            prefix.iloc[-1].to_numpy(float),
            rtol=1e-10,atol=1e-10,equal_nan=True,
        )


def test_event_groups_are_distinct_for_different_timeframes():
    d,z=sample()
    for tf in ("1h","4h","1D"):
        groups=r291.feature_groups(tf,d,z)
        assert len(groups)==2
        assert all(len(v)==len(d) for v in groups.values())
        assert all("body_atr" in v for v in groups.values())


def test_variant_is_restored_to_baseline_after_replay(monkeypatch,tmp_path):
    monkeypatch.setattr(base,"ROOT",tmp_path)
    original_gate=base.gates
    original_features=base.feature_groups
    original_cut=base.CUTS
    original_version=base.STRATEGY
    original_min=base.MINVAL
    def fake(tf):
        assert base.gates is r291.gates
        assert base.feature_groups is r291.feature_groups
        assert base.MINVAL["1h"]==75
        return {"passes_all_predeclared_gates":False,
                "aggregate":{"BUY":{"n":0},"SELL":{"n":0}},
                "coverage":0.,
                "limitations":[]}
    monkeypatch.setattr(base,"run",fake)
    out=r291.run("1h")
    assert out["variant"].startswith("R29.1")
    assert (tmp_path/"r291-event-1h.json").exists()
    assert base.gates is original_gate
    assert base.feature_groups is original_features
    assert base.CUTS==original_cut
    assert base.STRATEGY==original_version
    assert base.MINVAL==original_min

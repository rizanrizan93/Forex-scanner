"""R29 research-only contracts. Synthetic tests do not imply 60% achieved."""
from datetime import UTC
from pathlib import Path
import numpy as np
import pandas as pd
import pytest

import r29_direction60_walkforward as r29


def test_predeclared_horizon_side_support_and_cost_gates():
    assert set(r29.TESTYEARS)=={"1h","4h","1D","1W"}
    assert r29.MINEVAL["1h"] >= 100
    assert r29.MINEVAL["4h"] >= 50
    assert r29.MINEVAL["1D"] >= 30
    assert r29.COST_USD_OZ > 0
    assert all(c>=0.5 for c in r29.CUTS)
    assert r29.STRATEGY.startswith("R29")


def test_label_maturity_embargo_excludes_cross_year_future():
    ix=pd.date_range("2022-01-01", "2024-02-01",freq="D",tz="UTC")
    valid=np.ones(len(ix),bool)
    tr,va,te=r29.split_masks(ix,valid,2024)
    # Dec 31 2022 label matures Jan 1 2023, NOT in training.
    d22=int(np.flatnonzero(ix==pd.Timestamp("2022-12-31",tz="UTC"))[0])
    d23=int(np.flatnonzero(ix==pd.Timestamp("2023-12-31",tz="UTC"))[0])
    assert not tr[d22]
    assert not va[d23]
    assert te[int(np.flatnonzero(ix==pd.Timestamp("2024-01-01",tz="UTC"))[0])]
    assert not np.any(tr&va) and not np.any(va&te) and not np.any(tr&te)
    assert not np.any(tr & (ix>=pd.Timestamp("2023-01-01",tz="UTC")))


def test_wilson_penalizes_tiny_high_accuracy_samples():
    y=np.array([1,1,1,1,1,1,1,1,0,0,0,0],dtype=np.int8)
    p=np.array([.91]*4+[.65]*4+[.1]*4)
    v={"all":np.ones(len(y),bool),"few":np.array([1]*4+[0]*8,bool)}
    chosen=r29.select_side(y,p,v,5,"BUY")
    assert chosen is not None
    assert chosen[1]["validation"]["n"]>=5
    # High 100% four-sample rule must be rejected below support floor.
    assert chosen[1]["gate"]=="all"


def test_directional_cost_and_mfe_are_separate_from_precision():
    y=np.array([1,1,0],dtype=np.int8)
    mask=np.array([True,True,False])
    base={"reference_close":np.array([3600.,3610.,3620.]),
          "next_close":np.array([3602.,3612.,3610.]),
          "next_high":np.array([3611.,3613.,3621.]),
          "next_low":np.array([3599.,3605.,3609.])}
    stats=r29.stats(y,mask,"BUY",base)
    assert stats["n"]==2 and stats["correct"]==2
    assert stats["accuracy"]==1.0
    assert stats["net_mean_after_assumed_cost_usd_oz"]==1.3
    assert stats["mfe_ge_10_usd_fraction"]==.5


def test_partial_or_empty_side_has_no_fake_60pct():
    x=r29.stats(np.array([1,0,1]),np.zeros(3,bool),"SELL")
    assert x["n"]==0 and x["accuracy"] is None
    assert x["coverage"]==0


def test_no_live_changes_or_order_authority_in_r29_source():
    source=(Path(__file__).resolve().parents[1]/
           "scripts/r29_direction60_walkforward.py").read_text()
    assert "execution_authority\":False" in source
    assert '"research_only":True' in source
    for disallowed in ("place_order(", "execute_market_order(", "cBot",
                       "streamlit", "supabase.create", "git push"):
        assert disallowed not in source

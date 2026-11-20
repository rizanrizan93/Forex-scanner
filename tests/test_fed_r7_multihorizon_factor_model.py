"""R7 unit fixtures are synthetic, NOT actual gold forecast evidence."""
import numpy as np
import pandas as pd
import pytest
from fx_scanner.fed_r7_multihorizon_factor_model import (
    CONTRACT,FEATURES,HORIZONS,fit_asof,audit_walk_forward)


def synthetic(n=650, names=("dxy_change_pct","real_yield_10y_change_bps")):
    t=pd.date_range("2020-01-01",periods=n,freq="B",tz="UTC")
    rng=np.random.default_rng(121)
    a=rng.standard_normal(n)
    b=rng.standard_normal(n)
    changes=np.zeros(n)
    changes[1:]=.0015*a[:-1]-.0005*b[:-1]+.0002*rng.standard_normal(n-1)
    price=2000*np.exp(np.cumsum(changes))
    d=pd.DataFrame(index=t)
    d["gold_close"]=price
    d["gold_close_received_at"]=t
    d["vintage_verified"]=True
    for name in names:
        d[name]=a if name=="dxy_change_pct" else b
        d[name+"_received_at"]=t-pd.Timedelta(seconds=1)
    return d


def test_weight_learning_produces_horizon_score_without_auto_order():
    x=fit_asof(synthetic(),horizon="D1",
               feature_names=("dxy_change_pct","real_yield_10y_change_bps"),
               min_train_rows=100)
    assert x["contract"]==CONTRACT
    assert x["status"]=="RESEARCH_ESTIMATE"
    assert x["search_side"] in ("RESEARCH_SEARCH_BUY","RESEARCH_SEARCH_SELL","WAIT")
    assert x["point_in_time_history_verified"] is True
    assert x["out_of_sample_validated"] is False
    assert x["calibrated_probability"] is None
    assert x["execution_authority"] is False
    assert x["frozen_v1_influence"] is False
    assert x["weights_are_causal_effects"] is False
    assert sum(x["feature_weight_pct"].values())==pytest.approx(100,abs=.01)
    assert x["feature_weight_pct"]["dxy_change_pct"]>x["feature_weight_pct"]["real_yield_10y_change_bps"]
    assert x["full_factor_universe"] is False


def test_data_from_future_arrival_is_rejected_without_lookahead():
    d=synthetic()
    d.loc[d.index[-1],"dxy_change_pct_received_at"]=(
        d.index[-1]+pd.Timedelta(minutes=2))
    with pytest.raises(ValueError,match="LOOKAHEAD_SOURCE_RECEIPT"):
        fit_asof(d,horizon="D1",
                 feature_names=("dxy_change_pct","real_yield_10y_change_bps"))


def test_vintage_revisions_without_original_source_are_blocked():
    d=synthetic()
    d.loc[d.index[100],"vintage_verified"]=False
    with pytest.raises(ValueError,match="UNVERIFIED_DATA_VINTAGE"):
        fit_asof(d,horizon="D1",
                 feature_names=("dxy_change_pct","real_yield_10y_change_bps"))


def test_annual_horizon_requires_deep_effective_history():
    d=synthetic(650,names=("dxy_change_pct","real_yield_10y_change_bps"))
    r=fit_asof(d,horizon="Y1",
               feature_names=("dxy_change_pct","real_yield_10y_change_bps"))
    assert r["status"]=="WAIT"
    assert r["search_side"]=="WAIT"
    assert r["estimated_return_pct"] is None
    assert r["trading_sessions"]==252


def test_walk_forward_outcomes_evaluated_at_future_completed_close_only():
    d=synthetic(670)
    x=audit_walk_forward(
        d,horizon="W1",
        feature_names=("dxy_change_pct","real_yield_10y_change_bps"),
        first_test_at=d.index[-120],min_train_rows=100,min_edge_pct=0.0)
    assert x["contract"]=="RIZAN_XAU_R7_WALK_FORWARD_AUDIT_V1"
    assert x["horizon_sessions"]==5
    assert x["n_tested_nonoverlap"]<=24
    assert x["production_validated"] is False
    assert x["model_calibrated_probability"] is None
    assert x["execution_authority"] is False
    assert all(pd.Timestamp(z["horizon_end"])>pd.Timestamp(z["at"])
               for z in x["events"])
    assert x["status"]=="INSUFFICIENT_EFFECTIVE_OOS_SAMPLES"


def test_future_residuals_cannot_change_asof_fit_weights_or_direction():
    d=synthetic(620)
    a=fit_asof(d.iloc[:500],horizon="D1",
               feature_names=("dxy_change_pct","real_yield_10y_change_bps"),
               min_train_rows=100)
    future=d.copy()
    future.loc[future.index[500:],"gold_close"]*=1.3
    b=fit_asof(future.iloc[:500],horizon="D1",
               feature_names=("dxy_change_pct","real_yield_10y_change_bps"),
               min_train_rows=100)
    assert a["feature_weight_pct"]==b["feature_weight_pct"]
    assert a["estimated_return_pct"]==b["estimated_return_pct"]


def test_missing_feature_cannot_be_replaced_with_guessed_source():
    d=synthetic()
    with pytest.raises(ValueError,match="MISSING_POINT_IN_TIME_FEATURES"):
        fit_asof(d,horizon="D1")


def test_all_horizon_definitions_are_distinct():
    assert HORIZONS=={"D1":1,"W1":5,"M1":21,"Y1":252}
    assert set(FEATURES)==set(HORIZONS)
    assert "central_bank_net_tonnes" in FEATURES["Y1"]
    assert "futures_orderflow_z" in FEATURES["D1"]
    assert "futures_orderflow_z" not in FEATURES["Y1"]

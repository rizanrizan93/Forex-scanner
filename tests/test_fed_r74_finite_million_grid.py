"""Synthetic ONLY tests for R7.4 finite six-million+ causal grid."""
import json
import numpy as np
import pandas as pd
import pytest
from fx_scanner.fed_r73_nested_matched_ablation import ALL_FEATURES
from fx_scanner.fed_r74_finite_million_grid import (
    weights_full,configured_count,finite_nested_search,AXES,
    WEIGHT_VALUES,THRESHOLDS,POLICIES,HORIZON_LIST,CONTRACT,
    _wilson_lower,_exact_p)


def make_synthetic_gold():
    idx=pd.date_range("2018-01-01","2026-11-20",freq="B",tz="UTC")
    rng=np.random.default_rng(74)
    n=len(idx)
    close=1250*np.exp(np.cumsum(rng.normal(.0003,.006,n)))
    op=np.r_[close[0],close[:-1]]
    d=pd.DataFrame({
        "open":op,"high":np.maximum(op,close)+1.5,
        "low":np.minimum(op,close)-1.5,"close":close},index=idx)
    d["xau_mom5_pct"]=100*(d.close/d.close.shift(5)-1)
    d["xau_mom21_pct"]=100*(d.close/d.close.shift(21)-1)
    d["xau_rvol21_pct"]=100*d.close.pct_change().rolling(21).std()
    d["xau_range5_pct"]=100*((d.high-d.low)/d.close).rolling(5).mean()
    for j,feature in enumerate(ALL_FEATURES):
        if feature not in d:
            d[feature]=(rng.standard_normal(n)*(j%3+1)) + (
                .15*np.sin(np.arange(n)/37+j))
    return d


def test_exact_grid_preregistered_count_and_distinct_weight_patterns():
    w=weights_full()
    assert len(AXES)==8
    assert w.shape==(390624,8)
    assert np.any(w==0)
    assert np.all(np.any(w!=0,axis=1))
    assert np.unique(w,axis=0).shape[0]==len(w)
    assert configured_count()==9_374_976
    assert len(THRESHOLDS)==4
    assert len(POLICIES)==2
    assert len(HORIZON_LIST)==3
    assert len(WEIGHT_VALUES)==5


def test_wilson_penalizes_one_small_side_and_exact_p_pairing():
    wins=np.array([12,12,12]);n=np.array([12,30,60])
    lower=_wilson_lower(wins,n)
    assert lower[0]>lower[1]>lower[2]
    assert _exact_p(0,0)==1.
    assert _exact_p(2,2)==1.
    assert _exact_p(15,0)<.01


def test_grid_does_not_read_2025_26_including_volatility_factors():
    d=make_synthetic_gold()
    kwargs={
        "horizon":"W1","outer_years":(2023,),
        "weight_values":(-1,0,1),
        "thresholds":(0.0,.2),
        "policies":("GLOBAL","REGIME_GATED"),
        "batch_size":1024,
    }
    a=finite_nested_search(d,**kwargs)
    assert a["contract"]==CONTRACT
    assert a["all_2025_2026_rows_removed_before_any_model_fit_or_label"]
    assert a["unique_configs_each_horizon"]==(3**8-1)*2*2
    assert a["total_fold_config_scoring_evaluations"]==(3**8-1)*2*2
    assert a["intended_total_full_design_all_three_horizons"]==9_374_976
    assert a["previously_exposed_2023_24_outer_is_not_untouched_holdout"]
    assert a["source_publication_lags_are_assumptions"]
    assert a["production_promotion_status"]=="REJECTED_UNTIL_FUTURE_SHADOW"
    # Mutating EVERY 2025+ input must not affect a single nested metric.
    changed=d.copy()
    after=changed.index.year>=2025
    for key in ("open","high","low","close"):
        changed.loc[after,key]*=5.
    for key in ALL_FEATURES:
        changed.loc[after,key]=changed.loc[after,key]*123+999
    b=finite_nested_search(changed,**kwargs)
    assert a==b


def test_unavailable_or_untrusted_features_fail_closed():
    d=make_synthetic_gold()
    with pytest.raises(ValueError,match="15_REAL_FEATURES"):
        finite_nested_search(
            d.drop(columns=["fed_path_spread_proxy_bp"]),horizon="D1",
            weight_values=(-1,0,1),thresholds=(0.,),
            policies=("GLOBAL",))
    with pytest.raises(ValueError,match="2025_2026"):
        finite_nested_search(d,horizon="D1",outer_years=(2025,),
                             weight_values=(-1,0,1))


def test_annual_prediction_fails_closed_before_any_search():
    with pytest.raises(ValueError,match="NO_Y1"):
        finite_nested_search(make_synthetic_gold(),horizon="Y1",
                             weight_values=(-1,0,1))


def test_macro_raw_2025_does_not_get_fit_even_as_regime():
    d=make_synthetic_gold()
    a=finite_nested_search(d,horizon="D1",
        outer_years=(2023,),weight_values=(-1,0,1),
        thresholds=(0.0,),policies=("GLOBAL",),batch_size=1024)
    for fold in a["outer_development_folds"]:
        assert fold.get("outer_year",fold.get("year"))<=2024
        assert fold["searched_unique_configs"] in (0,(3**8-1))
        if "model_results" in fold:
            assert fold["model_results"]["R74_SELECTED"]["matched_n"]==(
                fold["model_results"]["R72_PRICE_ONLY_FIXED_RIDGE_500"]["matched_n"])
            assert fold["comparisons"]["R73_FULL_MACRO_FIXED_RIDGE_500"]["paired_dates_n"]==fold["outer_evaluation_n"]

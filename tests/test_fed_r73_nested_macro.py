"""Synthetic R7.3 anti-leakage/paired-date tests, NOT empirical success."""
import numpy as np
import pandas as pd
import pytest
from fx_scanner.fed_r73_nested_matched_ablation import (
    run_nested_matched_ablation,ALL_FEATURES,MODELS)
from fx_scanner.fed_r73_fomc_surprise_gate import calculate_research_surprise
from fx_scanner.fed_r73_official_policy_cot_panel import _align_asof,FEATURES


def synthetic_ohlc():
    idx=pd.date_range("2018-01-01","2026-11-20",freq="B",tz="UTC")
    r=np.random.default_rng(73)
    close=1250*np.exp(np.cumsum(r.normal(.0002,.006,len(idx))))
    op=np.r_[close[0],close[:-1]]
    d=pd.DataFrame({
        "open":op,"high":np.maximum(op,close)+1.0,
        "low":np.minimum(op,close)-1.0,
        "close":close},index=idx)
    d["xau_range5_pct"]=100*((d.high-d.low)/d.close).rolling(5).mean()
    d["xau_mom5_pct"]=100*(d.close/d.close.shift(5)-1)
    d["xau_mom21_pct"]=100*(d.close/d.close.shift(21)-1)
    d["xau_rvol21_pct"]=100*d.close.pct_change().rolling(21).std()
    for j,z in enumerate(ALL_FEATURES):
        if z not in d:
            d[z]=r.normal(0,1,len(d))+(j+1)*.001
    return d


def test_cme_hawkish_rate_surprise_is_not_gold_sell_signal_without_receipts():
    rec={
        "expectation_provider":"CME_FEDWATCH",
        "fomc_statement_published_at":"2024-09-18T18:00:00Z",
        "expectations_quote_observed_at":"2024-09-18T17:00:00Z",
        "expectations_quote_received_at":"2024-09-18T17:00:01Z",
        "premeeting_probability_distribution":[
            {"probability":.75,"fed_target_midpoint_bps":487.5},
            {"probability":.25,"fed_target_midpoint_bps":512.5}],
        "actual_fomc_target_midpoint_bps":512.5,
    }
    out=calculate_research_surprise(rec)
    assert out["conditional_formula_computed"]
    assert out["conditional_policy_surprise_bps"]==18.75
    assert out["conditional_policy_interpretation"]=="MORE_RESTRICTIVE_THAN_EXPECTED"
    assert out["eligible_as_pit_factor"] is False
    assert out["fomc_directional_claim"] is None
    assert out["execution_authority"] is False


def test_no_fedwatch_historical_archive_means_wait_not_proxy_probability():
    out=calculate_research_surprise({
        "expectation_provider":"FRED_DFEDTARU",
        "actual_fomc_target_midpoint_bps":500})
    assert out["status"]=="WAIT_WRONG_OR_UNLICENSED_EXPECTATION_PROVIDER"
    assert not out["conditional_formula_computed"]


def test_cme_expectation_timestamp_after_fomc_is_invalid():
    out=calculate_research_surprise({
        "expectation_provider":"CME_FEDWATCH",
        "fomc_statement_published_at":"2023-05-03T18:00:00Z",
        "expectations_quote_observed_at":"2023-05-03T18:01:00Z",
        "expectations_quote_received_at":"2023-05-03T18:01:01Z",
        "premeeting_probability_distribution":[
            {"probability":1,"fed_target_midpoint_bps":512.5}],
        "actual_fomc_target_midpoint_bps":512.5})
    assert out["status"]=="WAIT_EXPECTATION_NOT_KNOWN_BEFORE_FOMC_RELEASE"


def test_assumed_release_lag_does_not_expose_unpublished_source():
    source=pd.Series([100.,150.],
        index=pd.DatetimeIndex(["2023-01-03","2023-01-10"],tz="UTC"))
    decisions=pd.DatetimeIndex([
        "2023-01-03T23:00Z","2023-01-04T01:00Z",
        "2023-01-06T12:00Z","2023-01-19T01:00Z"])
    aligned=_align_asof(decisions,source,lag_days=3,max_age_days=10)
    assert np.isnan(aligned[0])
    assert np.isnan(aligned[1])
    assert aligned[2]==100
    assert aligned[3]==150


def test_nested_2025_2026_quarantine_and_matched_n():
    x=synthetic_ohlc()
    a=run_nested_matched_ablation(x,horizon="W1",outer_years=(2022,2023))
    assert not a["used_2025_2026_market_features_or_labels"]
    assert not a["score_is_fresh_untouched_holdout"]
    assert a["comparison_paired_n_same_for_every_model"]
    assert a["status"].startswith("NESTED_PAIRED")
    assert set(a["summary"])==set(MODELS)
    ns={r["matched_evaluation_n"] for r in a["summary"].values()}
    assert len(ns)==1
    modified=x.copy()
    after=modified.index.year>=2025
    for k in ("open","high","low","close"):
        modified.loc[after,k]*=1.33
    for k in ALL_FEATURES:
        modified.loc[after,k]=modified.loc[after,k]*100-1000
    b=run_nested_matched_ablation(modified,horizon="W1",
                                 outer_years=(2022,2023))
    assert a==b


def test_no_annual_claim_and_no_2025_outer_fold():
    x=synthetic_ohlc()
    assert run_nested_matched_ablation(
        x,horizon="Y1")["status"]=="Y1_NOT_ENOUGH_INDEPENDENT_CYCLES"
    with pytest.raises(ValueError,match="PRE_2025"):
        run_nested_matched_ablation(x,horizon="D1",outer_years=(2025,))


def test_missing_fed_or_cot_columns_fails_closed_not_fill_zero():
    d=synthetic_ohlc().drop(columns=["cot_gold_open_interest_week_pct"])
    with pytest.raises(ValueError,match="MISSING_R73_REAL_FACTOR_SOURCE"):
        run_nested_matched_ablation(d,horizon="D1")


def test_all_historical_features_are_not_fomc_surprise_label():
    assert len(ALL_FEATURES)>=13
    assert all("fomc_surprise" not in x.lower() for x in ALL_FEATURES)
    assert "fed_path_spread_proxy_bp" in ALL_FEATURES
    assert "cot_gold_open_interest_week_pct" in ALL_FEATURES

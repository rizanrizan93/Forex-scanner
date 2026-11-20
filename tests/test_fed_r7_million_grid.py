"""Synthetic fixture tests for R7 million-grid runner; NO market alpha claims."""
import numpy as np
import pandas as pd
import pytest
from fx_scanner.fed_r7_million_grid import (
    FEATURES,GRID_PER_HORIZON,HORIZONS,search_one_horizon,_weights_from_ids,_segment)
from fx_scanner.fed_r7_fred_proxy_panel import align_retrospective_proxies,SERIES


def fixture_panel():
    idx=pd.date_range("2019-01-01","2026-09-30",freq="B",tz="UTC")
    rng=np.random.default_rng(731)
    close=1250*np.exp(np.cumsum(rng.normal(.0003,.01,len(idx))))
    out=pd.DataFrame({"open":close*.9998,"close":close},index=idx)
    for k,f in enumerate(FEATURES):
        out[f]=rng.normal(0,1,len(idx))+(k+1)*.005*np.sin(np.arange(len(idx))/13)
    return out


def test_default_grid_count_is_one_million_per_horizon():
    assert len(FEATURES)==8
    assert GRID_PER_HORIZON==1_048_576
    assert HORIZONS=={"D1":1,"W1":5,"M1":21,"Y1":252}
    assert _weights_from_ids(np.arange(65_536)).shape==(65_536,8)


def test_test_grid_reports_exact_evaluated_count_not_full_million_claim():
    p=fixture_panel()
    r=search_one_horizon(p,horizon="D1",
                         max_weight_vectors=128,batch_weights=64)
    assert r["trial_count_evaluated"]==128*16
    assert r["total_available_grid"]==1_048_576
    assert r["macro_provenance"].endswith("NOT_PIT")
    assert r["production_alpha_validated"] is False
    assert r["execution_authority"] is False


def test_selection_is_independent_of_2025_2026_holdout_price_outcomes():
    p=fixture_panel()
    first=search_one_horizon(
        p,horizon="D1",max_weight_vectors=128,batch_weights=64)
    p2=p.copy()
    q=p2.index>="2025-01-01"
    p2.loc[q,"close"]=p2.loc[q,"close"]*1.12
    p2.loc[q,"open"]=p2.loc[q,"open"]*1.03
    second=search_one_horizon(
        p2,horizon="D1",max_weight_vectors=128,batch_weights=64)
    assert first["status"]==second["status"]
    assert first.get("selected_weight_id")==second.get("selected_weight_id")
    assert first.get("selected_threshold")==second.get("selected_threshold")


def test_y1_rejects_weak_nonoverlap_holdout_not_80_percent_claim():
    r=search_one_horizon(fixture_panel(),horizon="Y1",
                         max_weight_vectors=128,batch_weights=64)
    assert r["status"]=="WAIT_INSUFFICIENT_NONOVERLAPPING_YEARLY_OBSERVATIONS"
    assert r["trial_count_evaluated"]==0
    assert r["production_alpha_validated"] is False


def test_gap_crossing_session_horizon_is_censored():
    p=fixture_panel()
    no_gap=_segment(p,5,"2023-01-01","2025-01-01")
    p=p.drop(p.loc["2023-09-01":"2023-10-30"].index)
    with_gap=_segment(p,5,"2023-01-01","2025-01-01")
    assert len(with_gap)<len(no_gap)
    assert all((p.index[with_gap+5]-p.index[with_gap]).days<=75)


def test_latest_vintage_fred_lag_keeps_future_observation_hidden():
    ix=pd.date_range("2025-01-01",periods=100,freq="B",tz="UTC")
    d=pd.DataFrame({"open":2000.,"close":2000.+np.arange(len(ix))},index=ix)
    source={}
    for key in SERIES:
        source[key]=pd.Series(np.arange(len(ix))+10.,index=ix)
    panel=align_retrospective_proxies(d,source)
    assert panel.attrs["historical_original_vintage_verified"] is False
    # Macro observed on day 15 cannot become known on observation day.
    # BDay(3) minimum, plus 5 observations to compute delta.
    assert np.isnan(panel["real10_delta_5_bps"].iloc[5])
    assert np.isfinite(panel["real10_delta_5_bps"].iloc[10])
    # Trade-weighted broad USD is released with 10-business-day lag.
    assert np.isnan(panel["broad_usd_ret5_pct"].iloc[13])
    assert np.isfinite(panel["broad_usd_ret5_pct"].iloc[20])


def test_missing_real_macro_columns_fail_closed_not_imputed():
    p=fixture_panel().drop(columns=["real10_delta_5_bps"])
    with pytest.raises(ValueError,match="MISSING_MACRO_PRICE"):
        search_one_horizon(p,horizon="D1",
                           max_weight_vectors=64,batch_weights=64)

"""Synthetic regression tests only: point-in-time contracts and regimes."""
from hashlib import sha256
import pandas as pd
import numpy as np
import pytest
from fx_scanner.fed_r71_pit_provenance import (
    verify_record,classify_dataset_provenance,CONTRACT)
from fx_scanner.fed_r71_regime_map import map_regimes,diagnose_regimes
from fx_scanner.fed_r71_nested_regime import (
    nested_regime_walk_forward,GRID,PRICE_FEATURES,CONTRACT as NESTED)


def synthetic_daily():
    idx=pd.date_range("2018-01-01","2026-11-20",freq="B",tz="UTC")
    rng=np.random.default_rng(71)
    trend=np.where(np.arange(len(idx))%250<130,0.0015,-0.0012)
    shock=rng.standard_normal(len(idx))*.004
    shock[::75]-=.04
    logprice=np.cumsum(trend+shock)
    c=1250*np.exp(logprice)
    o=np.r_[c[0],c[:-1]]
    highs=np.maximum(o,c)+2.
    lows=np.minimum(o,c)-2.
    d=pd.DataFrame({"open":o,"high":highs,"low":lows,"close":c},index=idx)
    d["xau_range5_pct"]=(100*(d.high-d.low)/d.close).rolling(5).mean()
    d["xau_mom5_pct"]=100*(d.close/d.close.shift(5)-1)
    d["xau_mom21_pct"]=100*(d.close/d.close.shift(21)-1)
    d["xau_rvol21_pct"]=100*d.close.pct_change().rolling(21).std()
    for j,f in enumerate((
        "real10_delta_5_bps","nom2_delta_5_bps",
        "nom10_delta_5_bps","broad_usd_ret5_pct")):
        d[f]=rng.standard_normal(len(d))*(j+1)
    return d


def test_original_ice_dxy_archival_capture_cannot_arrive_after_decision():
    h="a"*64
    base={
        "symbol":"DXY","source_class":"ICE_DXY_INDEX","value":99.4,
        "observed_at":"2023-06-01T10:00:00Z",
        "published_at":"2023-06-01T10:00:01Z",
        "original_captured_at":"2023-06-01T10:00:03Z",
        "source_sha256":h,
        "proof_method":"EXCHANGE_TIMESTAMP_WITH_ARCHIVE_RECEIPT"}
    good=verify_record(base,decision_at="2023-06-01T10:02:00Z")
    assert good["contract"]==CONTRACT
    assert good["status"]=="TEMPORAL_ORDER_PASS_MANIFEST_UNVERIFIED"
    assert good["claimed_receipt_order_consistent"] is True
    assert good["intraday_point_in_time_verified"] is False
    assert good["dxy_ice_verified"] is False
    assert good["causal_model_input_permitted"] is False
    bad=verify_record(base,decision_at="2023-06-01T10:00:02Z")
    assert bad["status"]=="REJECT"
    assert bad["reason"]=="PUBLICATION_OR_CAPTURE_AFTER_DECISION"


def test_alfred_vintage_day_is_not_exact_intraday_release():
    r={
        "symbol":"DFII10","source_class":"ALFRED_VINTAGE",
        "value":1.65,"observed_at":"2023-05-11T00:00:00Z",
        "vintage_date":"2023-05-12",
        "source_sha256":"b"*64,"proof_method":"ALFRED_VINTAGE_DATE_ONLY"}
    p=verify_record(r,decision_at="2023-05-13T01:00:00Z")
    assert p["status"]=="PASS_DAILY_VINTAGE_ONLY"
    assert p["daily_vintage_consistent"] is True
    assert p["intraday_point_in_time_verified"] is False
    assert p["causal_model_input_permitted"] is False
    assert verify_record(r,decision_at="2023-05-12T15:00:00Z")["status"]=="REJECT"


def test_broad_usd_cannot_become_ice_dxy_by_relabeling():
    p={
        "symbol":"DXY","source_class":"TRADE_WEIGHTED_BROAD_USD","value":101.,
        "observed_at":"2023-07-01T00:00:00Z","published_at":"2023-07-03T00:00:00Z",
        "original_captured_at":"2023-07-03T00:00:05Z",
        "source_sha256":"c"*64,
        "proof_method":"ORIGINAL_RELEASE_TIMESTAMP_WITH_ARCHIVE_RECEIPT"}
    assert verify_record(p,decision_at="2023-07-04T12:00:00Z")["reason"]=="NON_ICE_INDEX_MISLABELED_AS_DXY"


def test_regime_has_each_state_and_is_not_future_or_liquidation_claim():
    d=synthetic_daily()
    series=map_regimes(d)
    assert set(series.unique()).issubset({"UNKNOWN","NEUTRAL","BULLISH","BEARISH","LIQUIDITY_STRESS"})
    assert (series=="LIQUIDITY_STRESS").any()
    assert (series=="BULLISH").any()
    assert (series=="BEARISH").any()
    a=map_regimes(d.iloc[:1000])
    assert series.iloc[:1000].equals(a)
    assert diagnose_regimes(d)["liquidation_confirmed"] is False


def test_nested_cv_never_opens_2025_2026_even_if_shock_changes():
    d=synthetic_daily()
    a=nested_regime_walk_forward(d,horizon="D1",outer_years=(2022,2023))
    assert a["contract"]==NESTED
    assert a["selection_2025_or_2026_used"] is False
    assert a["new_untouched_holdout_available"] is False
    assert a["oos_market_skill_claim"] is False
    assert a["quarantined_2025_2026_rows_not_read"]>0
    assert all((q.get("status")!="NESTED_DEVELOPMENT_FOLD" or
                q["train_last_target_before_outer_year"])
               for q in a["folds"])
    changed=d.copy()
    changed.loc[changed.index.year>=2025,"close"]*=1.7
    changed.loc[changed.index.year>=2025,"open"]*=1.7
    changed.loc[changed.index.year>=2025,"high"]*=1.7
    changed.loc[changed.index.year>=2025,"low"]*=1.7
    b=nested_regime_walk_forward(changed,horizon="D1",outer_years=(2022,2023))
    assert a==b


def test_missing_macro_cannot_be_imputed_as_proven_factor():
    d=synthetic_daily()
    assert len(GRID)==27
    with pytest.raises(ValueError,match="MISSING_PRICE_OR_FEATURES"):
        nested_regime_walk_forward(d.drop(columns=["nom2_delta_5_bps"]),
            horizon="W1",include_retrospective_macro=True,outer_years=(2023,))


def test_annual_abstains_without_new_independent_holdout():
    d=synthetic_daily()
    r=nested_regime_walk_forward(d,horizon="Y1")
    assert r["status"]=="Y1_INDEPENDENT_FOLDS_INSUFFICIENT_WAIT"
    assert r["folds"]==[]
    assert r["execution_authority"] is False


def test_forbid_arbitrary_outer_validation_using_seen_2025_2026():
    d=synthetic_daily()
    with pytest.raises(ValueError,match="PRE_2025"):
        nested_regime_walk_forward(d,horizon="D1",outer_years=(2025,))


def test_fabricated_source_sha_and_original_timestamp_cannot_certify_pit():
    record={
        "symbol":"DXY","source_class":"ICE_DXY_INDEX","value":104.5,
        "observed_at":"2023-06-01T10:00:00Z",
        "published_at":"2023-06-01T10:00:01Z",
        "original_captured_at":"2023-06-01T10:00:02Z",
        "source_sha256":"0"*64,
        "proof_method":"EXCHANGE_TIMESTAMP_WITH_ARCHIVE_RECEIPT"}
    got=verify_record(record,decision_at="2023-06-02T00:00:00Z")
    assert got["claimed_receipt_order_consistent"]
    assert not got["independent_capture_attestation_verified"]
    assert not got["intraday_point_in_time_verified"]
    assert not got["causal_model_input_permitted"]


def test_vintage_datetime_instead_of_day_is_rejected():
    record={
        "symbol":"DFII10","source_class":"ALFRED_VINTAGE","value":1.4,
        "observed_at":"2023-06-01T00:00:00Z",
        "vintage_date":"2023-06-02T12:00:00",
        "source_sha256":"f"*64,
        "proof_method":"ALFRED_VINTAGE_DATE_ONLY"}
    got=verify_record(record,decision_at="2023-06-04T00:00:00Z")
    assert got["status"]=="REJECT"
    assert got["reason"]=="ALFRED_VINTAGE_MUST_BE_DATE_ONLY"

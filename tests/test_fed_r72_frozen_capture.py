"""R7.2 frozen source integrity and prospective receipt tests (synthetic only)."""
import json
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
from fx_scanner.fed_r72_frozen_candidate import (
    CONTRACT,_hash,price_features,predict_from_frozen)
from fx_scanner.fed_r72_capture_forward import build_capture

ROOT=Path(__file__).resolve().parents[1]
FROZEN=ROOT/"research/frozen/r72_d1_price_only_v1.json"


def _model():
    model=json.loads(FROZEN.read_text())
    assert model["frozen_payload_sha256"]==_hash({
        k:v for k,v in model.items() if k!="frozen_payload_sha256"})
    return model


def _bars():
    dt=pd.date_range("2026-06-01","2026-11-20 23:00:00",
                     freq="h",tz="UTC")
    rng=np.random.default_rng(72)
    close=3900+np.cumsum(rng.normal(.003,1.5,len(dt)))
    op=np.r_[close[0],close[:-1]]
    d=pd.DataFrame({
        "timestamp":dt.asi8//1_000_000,
        "open":op,"high":np.maximum(op,close)+.3,
        "low":np.minimum(op,close)-.3,"close":close})
    return d


def test_hard_frozen_payload_cannot_change_or_be_retrained():
    model=_model()
    assert model["model_contract"]==CONTRACT
    assert model["training_rows"]==1622
    assert model["trained_2025_2026_outcomes"] is False
    assert model["params"]["regime_blend"]==0.0
    assert model["params"]["horizon"]=="D1"
    assert model["params"]["cBot_execution_authority"] is False
    modified=json.loads(json.dumps(model))
    modified["fitted_beta_log_return_per_standardized_feature"][0]*=2
    with pytest.raises(ValueError,match="FROZEN_PARAMETER_HASH_MISMATCH"):
        predict_from_frozen(modified,pd.DataFrame())


def test_forward_input_is_not_used_to_update_model_weights():
    model=_model()
    b=_bars()
    b.timestamp=pd.to_datetime(b.timestamp,unit="ms",utc=True)
    b["utc_day"]=b.timestamp.dt.floor("D")
    days=b.groupby("utc_day").agg(open=("open","first"),high=("high","max"),
                                   low=("low","min"),close=("close","last"))
    days=days[days.index.dayofweek<5]
    a=predict_from_frozen(model,days)
    assert a["research_search_side"] in ("SEARCH_BUY","SEARCH_SELL","WAIT")
    assert a["historical_2025_2026_used_for_recalibration"] is False
    assert a["new_unseen_forward_accuracy_known"] is False
    assert a["order_authority"] is False
    assert a["frozen_payload_sha256"]==model["frozen_payload_sha256"]


def test_raw_source_sha_and_receive_clock_are_recorded_pre_next_session(tmp_path,monkeypatch):
    raw=tmp_path/"quote_h1.csv"
    _bars().to_csv(raw,index=False)
    # Frozen 2026-11-20T23:11:24Z is hardcoded in audited source
    a=build_capture(
        raw_h1_path=raw,model_path=FROZEN,
        source_started_at="2026-11-21T00:03:00Z",
        source_received_at="2026-11-21T00:04:00Z",
        output_dir=tmp_path/"out",
        declared_model_commit="9e6a426c2ee6b586d8ba6d7acc40a1a8711b454e",
        github_run_id="synthetic",github_run_attempt="1",
        now="2026-11-21T00:05:00Z")
    assert a["signal_status"]=="SHADOW_SEARCH_ONLY"
    assert a["source_original_venue"].startswith("DUKASCOPY")
    assert a["source_observation_timestamp_is_not_receipt_timestamp"]
    assert a["newly_completed_post_freeze_d1_outcomes"]==0
    assert a["real_order_submitted"] is False
    assert (tmp_path/"out"/"r72-source-receipt-manifest.json").is_file()


def test_once_next_market_session_started_before_receipt_it_must_wait(tmp_path,monkeypatch):
    raw=tmp_path/"raw.csv"
    q=_bars()
    q.loc[len(q)]=q.iloc[-1].copy()
    q.loc[len(q)-1,"timestamp"]=pd.Timestamp(
        "2026-11-21T01:00:00Z").value//1_000_000
    q.to_csv(raw,index=False)
    # Frozen 2026-11-20T23:11:24Z is hardcoded in audited source
    a=build_capture(
        raw_h1_path=raw,model_path=FROZEN,
        source_started_at="2026-11-21T02:00:00Z",
        source_received_at="2026-11-21T02:01:00Z",
        output_dir=tmp_path/"out2",
        declared_model_commit="9e6a426c2ee6b586d8ba6d7acc40a1a8711b454e",
        now="2026-11-21T02:02:00Z")
    assert a["signal_status"]=="WAIT"
    assert a["newly_completed_post_freeze_d1_outcomes"]==0


def test_capture_before_commit_is_not_prospective(tmp_path,monkeypatch):
    raw=tmp_path/"raw.csv"
    _bars().to_csv(raw,index=False)
    # The precommit datetime is immutable; create a pre-freeze receipt instead.
    a=build_capture(
        raw_h1_path=raw,model_path=FROZEN,
        source_started_at="2026-11-20T23:05:00Z",
        source_received_at="2026-11-20T23:06:00Z",
        output_dir=tmp_path/"out3",
        declared_model_commit="9e6a426c2ee6b586d8ba6d7acc40a1a8711b454e",
        now="2026-11-20T23:07:00Z")
    assert a["reason"]=="WAIT_ONLY_WEEKEND_PRE_NEXT_SESSION_D1_PILOT"
    assert a["prediction"] is None

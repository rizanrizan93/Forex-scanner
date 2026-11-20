"""Forward scoring synthetic fixtures; never imply actual market returns."""
import json
import numpy as np
import pandas as pd
from fx_scanner.fed_r72_forward_evaluation import (
    CONTRACT,audit_future_outcomes)
from fx_scanner.fed_r72_capture_forward import HARD_FREEZE_COMMIT
from fx_scanner.fed_r72_frozen_candidate import CONTRACT as MODEL


def _raw(tmp_path,end="2026-11-28 00:00:00"):
    dt=pd.date_range("2026-07-01",end,freq="h",tz="UTC")
    rng=np.random.default_rng(72)
    close=4000+np.cumsum(rng.normal(0,.6,len(dt)))
    prev=np.r_[close[0],close[:-1]]
    f=tmp_path/"xau-h1.csv"
    pd.DataFrame({"timestamp":dt.asi8//1_000_000,
        "open":prev,"high":np.maximum(prev,close)+.3,
        "low":np.minimum(prev,close)-.3,
        "close":close}).to_csv(f,index=False)
    return f


def _manifest(tmp_path,*,decision="2026-11-21T00:20:00Z",
              last_session="2026-11-20T00:00:00Z",
              side="SEARCH_BUY"):
    d=tmp_path/"ledger";d.mkdir(exist_ok=True)
    x={
        "signal_status":"SHADOW_SEARCH_ONLY",
        "prospective_event_id":"a"*64,
        "pinned_frozen_model_commit":HARD_FREEZE_COMMIT,
        "decision_at":decision,
        "h1_quote_receipt_at":"2026-11-21T00:18:00Z",
        "prediction":{
            "source_last_completed_session_utc":last_session,
            "research_search_side":side,
            "training_model_contract":MODEL}}
    (d/"event.json").write_text(json.dumps(x))
    return d


def test_lookahead_horizon_is_checked_against_later_source_receipt(tmp_path):
    raw=_raw(tmp_path)
    ledger=_manifest(tmp_path)
    out=audit_future_outcomes(
        raw_h1_path=raw,old_manifests_dir=ledger,
        future_market_received_at="2026-11-28T01:00:00Z",
        now="2026-11-28T01:05:00Z")
    assert out["contract"]==CONTRACT
    assert out["observed_post_freeze_complete_outcomes"]==1
    e=out["events"][0]
    assert e["original_decision_at"].startswith("2026-11-21")
    assert e["new_outcome_session_utc"].startswith("2026-11-23")
    assert e["outcome_market_capture_at"].startswith("2026-11-28")
    assert out["production_approval"] is False
    assert out["cBot_trade_permission"] is False
    assert out["calibrated_probability"] is None


def test_pre_freeze_2025_decision_is_not_allowed_as_untouched(tmp_path):
    raw=_raw(tmp_path)
    ledger=_manifest(tmp_path,decision="2025-11-21T00:20:00Z",
                     last_session="2025-11-20T00:00:00Z")
    out=audit_future_outcomes(
        raw_h1_path=raw,old_manifests_dir=ledger,
        future_market_received_at="2026-11-28T01:00:00Z",
        now="2026-11-28T01:05:00Z")
    assert out["observed_post_freeze_complete_outcomes"]==0
    assert out["rejected"][0]["reason"]=="PRE_FREEZE_OR_NONCAUSAL_DECISION"


def test_missing_new_complete_session_waits_without_fabricating_result(tmp_path):
    raw=_raw(tmp_path,"2026-12-05 23:00:00")
    ledger=_manifest(tmp_path,decision="2026-12-05T00:20:00Z",
                     last_session="2026-12-04T00:00:00Z")
    out=audit_future_outcomes(
        raw_h1_path=raw,old_manifests_dir=ledger,
        future_market_received_at="2026-12-05T23:30:00Z",
        now="2026-12-05T23:40:00Z")
    assert out["observed_post_freeze_complete_outcomes"]==0
    assert out["status"]=="WAIT_GENUINELY_FUTURE_COMPLETED_SESSIONS"

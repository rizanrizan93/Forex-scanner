"""R7.2 prospective observation collector: UTC receipt / raw hash evidence.

This job is a READ-ONLY intake of Dukascopy XAUUSD BID H1 candles.
Historical bars have old market timestamps but NEW receipt timestamps.
Claims never conflate the two. Append-only GitHub Actions artifacts are
NOT durable cryptographically immutable storage; retain external copies.

Prediction is only allowed when exact frozen model was committed,
the source is recent and the next full quote session has NOT started.
If we are already inside a trading session, WAIT, do not backdate a call.

No cBot, no execution, no spread from FP Markets. "Correct direction"
is prohibited before a genuinely future full session's audited close.
"""
from __future__ import annotations
from datetime import datetime,timezone,timedelta
from pathlib import Path
import hashlib,json,os,re
import numpy as np
import pandas as pd
from .fed_r72_frozen_candidate import (
    CONTRACT as MODEL_CONTRACT,_hash,predict_from_frozen)

CONTRACT="RIZAN_R72_PUBLIC_PRICE_RECEIPT_LEDGER_V1"


def _clock(value):
    t=pd.Timestamp(value)
    if t.tzinfo is None or pd.isna(t):
        raise ValueError("TZ_AWARE_REAL_UTC_CLOCK_REQUIRED")
    return t.tz_convert("UTC")


def _read_quotes(path):
    p=Path(path)
    raw=p.read_bytes()
    if len(raw)<10000 or len(raw)>100_000_000:
        raise ValueError("RAW_SOURCE_SIZE_UNEXPECTED")
    x=pd.read_csv(p)
    if list(x.columns)!=["timestamp","open","high","low","close"]:
        raise ValueError("DUKASCOPY_ORIGINAL_H1_SCHEMA_CHANGED")
    millis=pd.to_numeric(x.timestamp,errors="raise")
    if ((millis<1_600_000_000_000).any() or
        (millis>1_850_000_000_000).any()):
        raise ValueError("SOURCE_EPOCH_MS_UNEXPECTED")
    x["timestamp"]=pd.to_datetime(millis,unit="ms",utc=True)
    if x.timestamp.has_duplicates or not x.timestamp.is_monotonic_increasing:
        raise ValueError("DUPLICATE_OR_UNSORTED_RAW_H1")
    for k in ("open","high","low","close"):
        x[k]=pd.to_numeric(x[k],errors="raise")
    if (x[["open","high","low","close"]].isna().any().any() or
        not np.isfinite(x[["open","high","low","close"]].to_numpy()).all() or
        (x[["open","high","low","close"]]<=0).any().any() or
        (x.high<x[["open","close"]].max(axis=1)).any() or
        (x.low>x[["open","close"]].min(axis=1)).any()):
        raise ValueError("SOURCE_H1_BAD_PRICES")
    if len(x)<1200:
        raise ValueError("SOURCE_TOO_SHORT_FOR_PRICE_FEATURES")
    return x,hashlib.sha256(raw).hexdigest(),len(raw)


def build_capture(*,raw_h1_path,model_path,source_started_at,
                  source_received_at,output_dir,
                  declared_model_commit,
                  github_run_id=None,github_run_attempt=None,
                  now=None):
    start=_clock(source_started_at)
    received=_clock(source_received_at)
    clock=_clock(now) if now is not None else pd.Timestamp.now(tz="UTC")
    if not (start<=received<=clock):
        raise ValueError("INCONSISTENT_RUNNER_CAPTURE_TIMESTAMPS")
    if received-start>pd.Timedelta(minutes=10):
        raise ValueError("SOURCE_FETCH_TOO_SLOW_FOR_RECEIPT")
    if (clock-received)>pd.Timedelta(minutes=30):
        raise ValueError("STALE_RECEIPT_TIMESTAMP")
    model_raw=Path(model_path).read_bytes()
    model=json.loads(model_raw)
    if model.get("model_contract")!=MODEL_CONTRACT:
        raise ValueError("WRONG_FROZEN_MODEL")
    if len(str(declared_model_commit))!=40 or not re.fullmatch(
        r"[a-f0-9]{40}",str(declared_model_commit)):
        raise ValueError("PINNED_PRE_FROZEN_GIT_COMMIT_REQUIRED")
    if _hash({k:v for k,v in model.items() if k!="frozen_payload_sha256"})!=model["frozen_payload_sha256"]:
        raise ValueError("FROZEN_MODEL_TAMPERED")
    quotes,sha,nbytes=_read_quotes(raw_h1_path)
    if quotes.timestamp.iloc[-1]>clock+pd.Timedelta(minutes=2):
        raise ValueError("RAW_H1_HAS_FUTURE_MARKET_BARS")
    first,last=quotes.timestamp.iloc[0],quotes.timestamp.iloc[-1]
    if (clock-last)>pd.Timedelta(days=5):
        raise ValueError("QUOTE_HISTORY_TOO_STALE_FOR_FORWARD_RESEARCH")
    quotes["utc_day"]=quotes.timestamp.dt.floor("D")
    daily=quotes.groupby("utc_day",sort=True).agg(
        open=("open","first"),high=("high","max"),
        low=("low","min"),close=("close","last"),
        observed_h1=("close","count"),
        last_h1=("timestamp","last"))
    daily=daily[(daily.index.dayofweek<5)&(daily.observed_h1>=18)].copy()
    # The UTC day must have fully ended when fetched. Never use today's
    # as-if-complete candle, or a quote fetched after its target opened.
    daily=daily[daily.index+pd.Timedelta(days=1)<=start]
    outdir=Path(output_dir);outdir.mkdir(parents=True,exist_ok=True)
    capture={
        "contract":CONTRACT,
        "source_instrument":"dukascopy_xauusd_bid_h1",
        "source_original_venue":"DUKASCOPY_PUBLIC_HISTORICAL_QUOTE_FEED",
        "source_history_is_original_PIT_archive":False,
        "source_sha256":sha,"source_bytes":nbytes,
        "raw_source_file":Path(raw_h1_path).name,
        "h1_source_rows":len(quotes),
        "source_first_observation_at":first.isoformat(),
        "source_latest_observation_at":last.isoformat(),
        "acquisition_started_at":start.isoformat(),
        "acquisition_completed_at":received.isoformat(),
        "archive_record_constructed_at":clock.isoformat(),
        "github_actions_run_id":str(github_run_id or "UNSET"),
        "github_actions_run_attempt":str(github_run_attempt or "UNSET"),
        "pinned_frozen_model_commit":declared_model_commit,
        "frozen_model_sha256":model["frozen_payload_sha256"],
        "frozen_params_source":"research/frozen/r72_d1_price_only_v1.json",
        "frozen_fit_includes_2025_2026":False,
        "observed_complete_utc_days":int(len(daily)),
        "source_observation_timestamp_is_not_receipt_timestamp":True,
        "original_receipt_manifest_externally_attested":False,
        "original_exchange_timestamp_for_ICE_DXY":False,
        "broker_fp_markets_spread_verified":False,
        "real_order_submitted":False,
        "newly_completed_post_freeze_d1_outcomes":0,
        "live_execution_authority":False,
        "frozen_v1_modified":False,
        "signal_status":"WAIT",
        "reason":"SESSION_COMPLETENESS_OR_PROSPECTIVE_DECISION_GATE",
        "prediction":None,
    }
    if len(daily)<90:
        capture["reason"]="INSUFFICIENT_FULLY_COMPLETED_PRICE_DAYS"
    else:
        # Strict: issue only while market is between sessions, with no
        # later H1 bars after the most recent fully completed UTC day.
        last_complete=daily.index[-1]
        any_after=(quotes.timestamp>=last_complete+pd.Timedelta(days=1)).any()
        if any_after:
            capture["reason"]="NEXT_UTC_TRADING_SESSION_ALREADY_STARTED"
        elif clock-last_complete>pd.Timedelta(days=5):
            capture["reason"]="LAST_COMPLETE_PRICE_DAY_TOO_OLD"
        else:
            # This deliberately prevents a signal before model was
            # actually committed as a frozen source artifact.
            pinned=_clock(os.environ.get("R72_FREEZE_COMMITTED_AT",
                         "2026-11-21T00:00:00+07:00"))
            if clock<pinned:
                capture["reason"]="MODEL_NOT_FROZEN_WHEN_SIGNAL_CONSTRUCTED"
            else:
                p=predict_from_frozen(model,daily[["open","high","low","close"]])
                capture.update(
                    signal_status="SHADOW_SEARCH_ONLY",
                    reason="PRE_NEXT_UTC_SESSION_FROZEN_SIGNAL",
                    prediction=p,
                    decision_at=clock.isoformat(),
                    h1_quote_receipt_at=received.isoformat(),
                    no_post_decision_outcome_scored=True)
    raw=outdir/"r72-source-receipt-manifest.json"
    raw.write_text(json.dumps(capture,sort_keys=True,indent=2,
                              allow_nan=False)+"\n")
    # Replay evidence includes exact raw H1 bytes in a separate file.
    print("R72_RECEIPT_CAPTURE "+json.dumps({
        "status":capture["signal_status"],"reason":capture["reason"],
        "received_at_utc":capture["acquisition_completed_at"],
        "last_quote_at_utc":capture["source_latest_observation_at"],
        "latest_valid_complete_utc_session":(
            daily.index[-1].isoformat() if len(daily) else None),
        "raw_sha256":sha,"all_h1_rows":len(quotes),
        "prospective_outcomes_evaluated":0,
    },sort_keys=True),flush=True)
    return capture


if __name__=="__main__":
    build_capture(
        raw_h1_path=os.environ["R72_RAW_H1"],
        model_path=os.environ.get("R72_FROZEN_MODEL",
            "research/frozen/r72_d1_price_only_v1.json"),
        source_started_at=os.environ["R72_SRC_FETCH_STARTED_UTC"],
        source_received_at=os.environ["R72_SRC_FETCH_RECEIVED_UTC"],
        output_dir=os.environ.get("R72_RECEIPT_OUTPUT",
                                  "artifacts/r72-receipt"),
        declared_model_commit=os.environ["R72_MODEL_FREEZE_COMMIT"],
        github_run_id=os.environ.get("GITHUB_RUN_ID"),
        github_run_attempt=os.environ.get("GITHUB_RUN_ATTEMPT"))

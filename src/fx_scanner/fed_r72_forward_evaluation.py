"""R7.2 forward-only adjudicator for prior *committed* weekend D1 shadows.

Read immutable-ish GitHub research-ledger event JSON files from
AFTER the hard model freeze, and independently received later H1 raw
market bars. Never evaluate the same-session candle from the
prediction's own source, a backfilled pre-freeze label or an
incomplete UTC day. Study is broker-BID proxy and NOT fill PnL.

A Git branch ledger can be edited unless branch protections enforce
immutability; model does not claim cryptographic trusted vendor time.
"""
from __future__ import annotations
from pathlib import Path
import hashlib,json
import numpy as np
import pandas as pd
from .fed_r72_capture_forward import (
    HARD_FREEZE_COMMIT,HARD_FREEZE_UTC, _read_quotes)
from .fed_r72_frozen_candidate import CONTRACT as FROZEN_CONTRACT

CONTRACT="RIZAN_R72_FUTURE_ONE_SESSION_OUTCOME_RESEARCH_V1"


def audit_future_outcomes(*,raw_h1_path,old_manifests_dir,
                          future_market_received_at,now=None):
    receipt=pd.Timestamp(future_market_received_at)
    if receipt.tzinfo is None:
        raise ValueError("UTC_AWARE_FUTURE_CAPTURE_REQUIRED")
    receipt=receipt.tz_convert("UTC")
    now=pd.Timestamp(now) if now is not None else pd.Timestamp.now(tz="UTC")
    if now.tzinfo is None or now<receipt:
        raise ValueError("PROSPECTIVE_OUTCOME_AUDIT_TIME_INVALID")
    quotes,sha,_=_read_quotes(raw_h1_path)
    quotes["utc_day"]=quotes.timestamp.dt.floor("D")
    daily=quotes.groupby("utc_day").agg(
        open=("open","first"),high=("high","max"),low=("low","min"),
        close=("close","last"),hours=("close","count"))
    daily=daily[(daily.index.dayofweek<5)&(daily.hours>=18)]
    daily=daily[daily.index+pd.Timedelta(days=1)<=receipt]
    seen=set();events=[];rejected=[]
    for p in sorted(Path(old_manifests_dir).rglob("*.json")):
        record=json.loads(p.read_text())
        if record.get("signal_status")!="SHADOW_SEARCH_ONLY":
            continue
        event_id=record.get("prospective_event_id")
        if (not isinstance(event_id,str) or len(event_id)!=64
            or event_id in seen):
            rejected.append({"file":p.name,"reason":"DUPLICATE_OR_INVALID_EVENT"})
            continue
        seen.add(event_id)
        if record.get("pinned_frozen_model_commit")!=HARD_FREEZE_COMMIT:
            rejected.append({"file":p.name,"reason":"DIFFERENT_FROZEN_COMMIT"})
            continue
        decision=pd.Timestamp(record["decision_at"]).tz_convert("UTC")
        old_receipt=pd.Timestamp(record["h1_quote_receipt_at"]).tz_convert("UTC")
        friday=pd.Timestamp(record["prediction"]["source_last_completed_session_utc"]).tz_convert("UTC")
        if (decision<pd.Timestamp(HARD_FREEZE_UTC) or
            old_receipt>decision or
            friday.dayofweek!=4 or
            friday>=decision or
            record["prediction"]["training_model_contract"]!=FROZEN_CONTRACT):
            rejected.append({"file":p.name,"reason":"PRE_FREEZE_OR_NONCAUSAL_DECISION"})
            continue
        future=daily[daily.index>decision.floor("D")]
        # Include only post-decision sessions; any newer Fri/Mon
        # is permitted if verified by the captured source.
        if future.empty:
            events.append({"event_id":event_id,"status":"PENDING_COMPLETE_NEXT_SESSION"})
            continue
        target_day=future.index[0]
        if target_day<=decision:
            rejected.append({"file":p.name,"reason":"FUTURE_SESSION_NOT_AFTER_DECISION"})
            continue
        side=record["prediction"]["research_search_side"]
        if side not in ("SEARCH_BUY","SEARCH_SELL"):
            rejected.append({"file":p.name,"reason":"NON_DIRECTIONAL_SIGNAL"})
            continue
        next_open=float(future.iloc[0]["open"])
        next_close=float(future.iloc[0]["close"])
        if not np.isfinite([next_open,next_close]).all():
            rejected.append({"file":p.name,"reason":"NONFINITE_NEW_MARKET_PRICES"})
            continue
        move=next_close-next_open
        signed=move if side=="SEARCH_BUY" else -move
        events.append({
            "event_id":event_id,
            "status":"PROVISIONAL_RESEARCH_DIRECTION_OBSERVED",
            "original_decision_at":decision.isoformat(),
            "new_outcome_session_utc":target_day.isoformat(),
            "outcome_market_capture_at":receipt.isoformat(),
            "later_source_sha256":sha,
            "side":side,
            "next_session_open_usd_per_oz":round(next_open,5),
            "next_session_close_usd_per_oz":round(next_close,5),
            "signed_move_usd_per_oz":round(signed,5),
            "direction_correct_after_assumed_0_40_usd_cost":bool(signed>0.40),
            "source_is_native_fp_markets_bid_ask":False,
            "independently_verified_vendor_original_publication":False,
            "execution_authority":False,
        })
    complete=[e for e in events if e["status"]=="PROVISIONAL_RESEARCH_DIRECTION_OBSERVED"]
    return {
        "contract":CONTRACT,
        "new_outcome_source_received_at":receipt.isoformat(),
        "source_sha256":sha,
        "observed_post_freeze_complete_outcomes":len(complete),
        "correct_count":sum(x["direction_correct_after_assumed_0_40_usd_cost"]
                            for x in complete),
        "evaluated_buy":sum(x["side"]=="SEARCH_BUY" for x in complete),
        "evaluated_sell":sum(x["side"]=="SEARCH_SELL" for x in complete),
        "status":"FORWARD_RESEARCH_ONLY" if complete
                 else "WAIT_GENUINELY_FUTURE_COMPLETED_SESSIONS",
        "rejected":rejected,
        "events":events,
        "reused_2025_2026_historical_labels_as_untouched":False,
        "calibrated_probability":None,
        "proof_of_profitable_execution":False,
        "production_approval":False,
        "cBot_trade_permission":False,
    }


if __name__=="__main__":
    import os
    r=audit_future_outcomes(
        raw_h1_path=os.environ["R72_RAW_H1"],
        old_manifests_dir=os.environ["R72_PRIOR_LEDGER_ROOT"],
        future_market_received_at=os.environ["R72_SRC_FETCH_RECEIVED_UTC"])
    p=Path(os.environ.get("R72_SCORE_OUTPUT",
                         "artifacts/r72-receipt/r72-forward-outcomes.json"))
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(r,indent=2,sort_keys=True,allow_nan=False)+"\n")
    print("R72_FUTURE_OUTCOME "+json.dumps({
        "status":r["status"],
        "n_observed":r["observed_post_freeze_complete_outcomes"],
        "correct":r["correct_count"],
        "n_buy":r["evaluated_buy"],"n_sell":r["evaluated_sell"],
        "no_live_trades":True},sort_keys=True),flush=True)

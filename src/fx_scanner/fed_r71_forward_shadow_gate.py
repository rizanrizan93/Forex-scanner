"""R7.1 forward-only shadow validation gate, no retrospective holdout reuse.

Results already seen in 2025-2026 (before model freeze) are banned.
Only genuine future signals recorded AFTER strategy freeze can enter a
prospective ledger, with original source observations and received-at
fields. This module does not fabricate observations or trigger orders.

A self-asserted capture timestamp is *not* independently verified. An
external acquisition manifest audit is required before promotion.
"""
from __future__ import annotations
from datetime import datetime,timezone
from math import isfinite
import re
import pandas as pd

CONTRACT="RIZAN_R71_FORWARD_SHADOW_GATE_NO_ORDERS_V1"
START_WIB="2026-11-21T00:00:00+07:00"
HORIZONS={"D1":1,"W1":5,"M1":21,"Y1":252}
MIN_CALLS={"D1":60,"W1":40,"M1":24,"Y1":15}
MIN_PER_SIDE={"D1":15,"W1":10,"M1":8,"Y1":5}


def _utc(v):
    try:
        t=pd.Timestamp(v)
        if t.tzinfo is None or pd.isna(t):
            raise ValueError
        return t.tz_convert("UTC")
    except (TypeError,ValueError,OverflowError):
        raise ValueError("TIMESTAMP_UTC_AWARE_REQUIRED")


def audit_forward_shadow(records,*,horizon,frozen_model_sha,frozen_params_sha,
                         freeze_at,independent_acquisition_manifest_verified=False):
    if horizon not in HORIZONS:
        raise ValueError("HORIZON_INVALID")
    if (not re.fullmatch("[0-9a-f]{40}",str(frozen_model_sha)) or
        not re.fullmatch("[0-9a-f]{64}",str(frozen_params_sha))):
        raise ValueError("MODEL_AND_PARAMS_MUST_BE_CONTENT_HASHES")
    frozen=_utc(freeze_at)
    if frozen<_utc(START_WIB):
        raise ValueError("FREEZE_BEFORE_NEW_HOLDOUT_START_FORBIDDEN")
    if not isinstance(records,list):
        raise ValueError("RECORDS_MUST_BE_LIST")
    results=[]
    discarded=[]
    for index,item in enumerate(records):
        if not isinstance(item,dict):
            discarded.append((index,"INVALID_RECORD"))
            continue
        if item.get("horizon")!=horizon or item.get("side") not in ("BUY","SELL"):
            discarded.append((index,"WRONG_HORIZON_OR_UNDECLARED_DIRECTION"))
            continue
        if item.get("frozen_model_sha")!=frozen_model_sha or (
            item.get("frozen_params_sha")!=frozen_params_sha):
            discarded.append((index,"MODEL_REVISED_AFTER_PRECOMMITMENT"))
            continue
        try:
            made=_utc(item["decision_at"])
            source_observed=_utc(item["source_observed_at"])
            source_received=_utc(item["source_received_at"])
            # Outcome can be absent; then it is pending, NOT a loss
            # or a correctly predicted direction.
            outcome=_utc(item["outcome_at"]) if item.get("outcome_at") else None
        except (KeyError,ValueError):
            discarded.append((index,"MISSING_OR_INVALID_TIMESTAMP"))
            continue
        if made<frozen:
            discarded.append((index,"REUSED_PRE_FREEZE_MARKET_HISTORY"))
            continue
        if not (source_observed<=source_received<=made):
            discarded.append((index,"FUTURE_SOURCE_OR_CAPTURE_TIMESTAMP"))
            continue
        if outcome is None or item.get("entry_price") is None or (
            item.get("outcome_price") is None):
            results.append({"decision_at":made.isoformat(),"side":item["side"],
                            "state":"PENDING_COMPLETED_MARKET_HORIZON"})
            continue
        if outcome<=made:
            discarded.append((index,"NON_FUTURE_OUTCOME"))
            continue
        # A timestamp 1 minute later is not a completed D1/W1/M1/Y1
        # horizon. Require separately recorded count of CLOSED market
        # sessions, plus a receipt at or after the sampled outcome.
        try:
            captured=_utc(item["outcome_captured_at"])
            sessions=item["completed_trading_sessions"]
            if (isinstance(sessions,bool) or not isinstance(sessions,int)
                or sessions < HORIZONS[horizon]):
                discarded.append((index,"HORIZON_TRADING_SESSIONS_INCOMPLETE"))
                continue
            if captured<outcome:
                discarded.append((index,"OUTCOME_CAPTURE_BEFORE_OUTCOME"))
                continue
            entry=float(item["entry_price"])
            close=float(item["outcome_price"])
        except (KeyError,TypeError,ValueError,OverflowError):
            discarded.append((index,"INVALID_OUTCOME_RECEIPT_OR_PRICE"))
            continue
        if not all(isfinite(x) and x>0 for x in (entry,close)):
            discarded.append((index,"INVALID_PRICE"))
            continue
        signed_return=(close-entry)*(1 if item["side"]=="BUY" else -1)
        results.append({
            "decision_at":made.isoformat(),
            "outcome_at":outcome.isoformat(),
            "side":item["side"],"state":"OBSERVED_PROVISIONAL",
            "signed_move_usd_per_oz":round(signed_return,5),
            "correct_after_hypothetical_0_40_spread":signed_return>0.4,
            "outcome_captured_at":captured.isoformat(),
            "completed_trading_sessions_claimed":sessions,
            # A caller-supplied Boolean is NOT independently audited.
            "original_ingestion_manifest_independently_verified":False,
        })
    completed=[x for x in results if x["state"]=="OBSERVED_PROVISIONAL"]
    buy=sum(x["side"]=="BUY" for x in completed)
    sell=len(completed)-buy
    eligible=(len(completed)>=MIN_CALLS[horizon] and
              buy>=MIN_PER_SIDE[horizon] and
              sell>=MIN_PER_SIDE[horizon])
    return {
        "contract":CONTRACT,
        "horizon":horizon,"frozen_at":frozen.isoformat(),
        "source_capture_clocks_are_attested":False,
        "external_manifest_verification_claimed":
            bool(independent_acquisition_manifest_verified),
        "source_manifest_independently_rechecked":False,
        "completed_future_records":len(completed),
        "pending_future_records":sum(x["state"].startswith("PENDING") for x in results),
        "buy_completed":buy,"sell_completed":sell,
        "excluded_reused_or_invalid_records":len(discarded),
        "excluded_reasons":discarded,
        "min_provisional_forward_sample_count_met":bool(eligible),
        "min_independent_forward_evidence_met":False,
        "status":("FORWARD_OBSERVATION_PROVISIONAL" if completed else
                  "WAIT_NEW_POST_FREEZE_MARKET_OUTCOMES"),
        "independent_forward_accuracy_verified":False,
        "producible_probability":None,
        "production_release_approved":False,
        "execution_authority":False,
        "cbot_influence":False,"frozen_v1_influence":False,
        "events":results,
        "caveat":"Even passing sample count is NOT independent provenance proof or profitable trading validation",
    }

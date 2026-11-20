"""RIZAN R5 — macro direction strictly constrains XAU Rejection V4 entries.

READ-ONLY RESEARCH FILTER, NOT A trading entry signal or order route.
Candidates must have passed V4 closed-bar setup and quote gates first;
an independent, fresh, event-matched FOMC R4 macro WATCH can allow ONLY
its own direction. WAIT/missing/stale/conflict -> zero aligned entries.

The 2019–26 USMPD research shock factors are EX-POST and must never be
passed as a historically executable signal. This module cannot make
accuracy claims, change Frozen V1, or call cTrader/bridge.
"""
from __future__ import annotations
from datetime import timedelta
from math import isfinite
from urllib.parse import urlsplit
from research.fed_expectation_r1.engine import utc

EXECUTION_AUTHORITY=False
DEPLOY_AUTHORITY=False
MACRO_MAX_AGE=timedelta(minutes=10)
FOMC_EVENT_MAX_AGE=timedelta(minutes=150)
OFFICIAL_HOSTS=("federalreserve.gov","newyorkfed.org")
EVENT_KINDS=frozenset({"FOMC_STATEMENT","FOMC_PRESS_CONFERENCE","FOMC_MINUTES",
                       "FED_CHAIR_SPEECH","FED_VOTING_MEMBER_SPEECH"})
MACRO_CONTRACT="FED_R4_POLICY_INFORMATION_XAU_READONLY_V1"

def official_fed_origin(url):
    try:
        p=urlsplit(str(url))
        host=(p.hostname or "").lower()
        return p.scheme=="https" and p.username is None and (
            any(host==s or host.endswith("."+s) for s in OFFICIAL_HOSTS))
    except (ValueError,TypeError):
        return False

def _result(now,event,macro_reason,candidates):
    return {
        "contract":"RIZAN_R5_FED_DIRECTION_XAU_ENTRY_ALIGNMENT_RESEARCH",
        "evaluated_at_utc":now.isoformat(),
        "macro_event_id":event.get("event_id") if isinstance(event,dict) else None,
        "macro_direction":"WAIT","macro_stage":"BLOCKED",
        "macro_reason":macro_reason,
        "raw_v4_entry_candidate_n":sum(
            1 for x in candidates if x.get("entry_status")=="ENTRY_CANDIDATE"),
        "aligned_entry_candidate_n":0,
        "research_candidates":[],
        "entry_permission":"NONE_RESEARCH_ONLY",
        "predicted_accuracy_pct":None,
        "target_accuracy_pct":80,
        "historical_two_side_80pct_validated":False,
        "eligible_for_live":False,
        "authority_to_send_orders":False,
        "authority_to_change_frozen_v1":False,
        "authority_to_deploy":False,
    }

def align_macro_v4(v4_candidates, macro, event, *, evaluated_at):
    """Classify per-side candidate alignment without trading.

    Important: signal-side agreement cannot improve the ORIGINAL
    pattern's technical evidence; it can only reduce the candidate set.
    """
    now=utc(evaluated_at)
    if not isinstance(v4_candidates,list) or len(v4_candidates)!=2:
        raise ValueError("V4_EXPECTS_BOTH_SIDE_RECORDS")
    sides=[x.get("side") for x in v4_candidates]
    if sorted(sides)!=["BUY","SELL"]:
        raise ValueError("UNIQUE_SYMMETRIC_V4_SIDES_REQUIRED")
    if any(x.get("entry_status") not in (
            "ENTRY_CANDIDATE","WATCH_ONLY","BLOCKED",
            "BLOCKED_PREVIOUS_FAILED_REJECTION") for x in v4_candidates):
        raise ValueError("UNKNOWN_V4_ENTRY_STATUS")
    if event is None:
        result=_result(now,None,"OFFICIAL_FOMC_EVENT_NOT_CONNECTED",v4_candidates)
        result["research_candidates"]=[
            {"side":x["side"],"setup_type":x.get("setup_type"),
             "v4_stage":x.get("stage"),"original_v4_entry_status":x["entry_status"],
             "macro_alignment_gate":"BLOCKED_NO_FOMC_MARKET_SOURCE",
             "watch_level":x.get("watch_level"),
             "invalidation":x.get("invalidation"),"cannot_execute":True}
            for x in v4_candidates
        ]
        return result
    if not isinstance(event,dict):
        raise ValueError("OFFICIAL_EVENT_REQUIRED")
    if not {"event_id","event_kind","release_at","source_url"}.issubset(event):
        raise ValueError("FOMC_EVENT_INCOMPLETE")
    if event["event_kind"] not in EVENT_KINDS or not official_fed_origin(event["source_url"]):
        raise ValueError("UNVERIFIED_FED_COMMUNICATION_EVENT")
    release=utc(event["release_at"])
    result=_result(now,event,"MACRO_NOT_CAPTURED_OR_MISSING",v4_candidates)
    if now<release:
        result["macro_reason"]="FOMC_NOT_YET_RELEASED"
    elif now-release>FOMC_EVENT_MAX_AGE:
        result["macro_reason"]="FOMC_CONTEXT_EXPIRED_REEVALUATE_FRESH_MACRO"
    elif not isinstance(macro,dict) or macro.get("contract")!=MACRO_CONTRACT:
        result["macro_reason"]="NO_VERIFIED_R4_WATCH"
    elif macro.get("event_id")!=event["event_id"]:
        result["macro_reason"]="MACRO_EVENT_ID_MISMATCH"
    elif (macro.get("authority_to_send_orders") is not False or
          macro.get("authority_to_deploy") is not False or
          macro.get("predicted_probability") is not None or
          macro.get("verified_80pct_both_sides") is not False):
        result["macro_reason"]="UNTRUSTED_MACRO_EXECUTION_OR_ACCURACY_CLAIM"
    elif macro.get("market_data_status")!="VALIDATED_CAPTURED_PRE_POST_INTRADAY":
        result["macro_reason"]="MACRO_MARKET_DATA_NOT_PIT_VERIFIED"
    else:
        macro_at=utc(macro["decision_at"])
        direction=macro.get("direction")
        expected=("SEARCH_SELL_REBOUND" if direction=="SELL" else
                  "SEARCH_BUY_DIP" if direction=="BUY" else "WAIT")
        if macro_at>now or now-macro_at>MACRO_MAX_AGE or macro_at<release:
            result["macro_reason"]="MACRO_DIRECTION_STALE_OR_FUTURE"
        elif direction not in ("BUY","SELL"):
            result["macro_reason"]="MACRO_WAIT_OR_CONFLICT"
        elif (macro.get("watch_bias")!=expected or
              macro.get("policy_information_regime")!="POLICY_LIKE"):
            result["macro_reason"]="POLICY_INFORMATION_CONFLICT"
        else:
            result["macro_stage"]="DIRECTION_CONFIRMED_READ_ONLY"
            result["macro_direction"]=direction
            result["macro_reason"]="MACRO_WATCH_VALID_TECHNICAL_FILTER_REQUIRED"
    for candidate in v4_candidates:
        side=candidate["side"]
        status=candidate["entry_status"]
        raw=status=="ENTRY_CANDIDATE"
        if not raw:
            gate="V4_NO_ENTRY_SETUP"
        elif result["macro_direction"]=="WAIT":
            gate="BLOCKED_NO_VALID_MACRO_DIRECTION"
        elif side!=result["macro_direction"]:
            gate="BLOCKED_OPPOSITE_MACRO_DIRECTION"
        elif (candidate.get("quote_ok") is not True or
              candidate.get("watch_level") is None or
              candidate.get("invalidation") is None):
            gate="BLOCKED_MISSING_V4_QUOTE_OR_STRUCTURAL_INVALIDATION"
        else:
            try:
                invalid=float(candidate["invalidation"])
                level=float(candidate["watch_level"])
                if not all(isfinite(z) for z in (invalid,level)) or level<=0 or invalid<=0:
                    gate="BLOCKED_INVALID_V4_LEVEL"
                elif (side=="BUY" and invalid>=level) or (
                        side=="SELL" and invalid<=level):
                    gate="BLOCKED_V4_INVALIDATION_GEOMETRY"
                else:
                    gate="ALIGNED_RESEARCH_CANDIDATE"
            except (ValueError,TypeError):
                gate="BLOCKED_INVALID_V4_LEVEL"
        result["research_candidates"].append({
            "side":side,
            "setup_type":candidate.get("setup_type"),
            "v4_stage":candidate.get("stage"),
            "original_v4_entry_status":status,
            "macro_alignment_gate":gate,
            "watch_level":candidate.get("watch_level"),
            "invalidation":candidate.get("invalidation"),
            "cannot_execute":True,
        })
    result["aligned_entry_candidate_n"]=sum(
        x["macro_alignment_gate"]=="ALIGNED_RESEARCH_CANDIDATE"
        for x in result["research_candidates"])
    return result

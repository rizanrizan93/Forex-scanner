"""R3 RESEARCH WATCH: cautious Fed + 2Y + 10Y + USD confirmation.

Never trades. All numerical factors must already be captured and
validated as point-in-time. R1 has validated Fed implied-rate, UST2Y,
DXY; this adapter asks for independent UST10Y, same event. Official
R2 communication may contradict and veto. Does NOT claim 80% alpha;
historical ex-post experiments explicitly failed dual-side 80%.
"""
from __future__ import annotations
from datetime import timedelta
from math import isfinite
from urllib.parse import urlsplit
from research.fed_expectation_r1.engine import utc

AUTHORITY_TO_TRADE=False
PRODUCTION_READY=False

def _result(*,reason,decision_at,extra=None):
    out={
        "contract":"FED_MACRO_R3_4FACTOR_WATCH_RESEARCH_ONLY",
        "decision_at":utc(decision_at).isoformat(),
        "direction":"WAIT","watch_bias":"WAIT",
        "event_id":None,"reason_codes":[reason],
        "features":{},"observed_accuracy_pct":None,
        "predicted_probability":None,"accuracy_target_pct":80,
        "research_validation":"FAILED_BOTH_SIDES_80PCT_2019_2026",
        "authority_to_place_order":False,"authority_to_deploy":False,
    }
    if extra:out.update(extra)
    return out

def _official_url(url):
    try:
        x=urlsplit(str(url))
        return x.scheme=="https" and bool(x.hostname) and x.username is None
    except (ValueError,TypeError):
        return False

def four_factor_watch(r1,us10y,r2,*,decision_at):
    now=utc(decision_at)
    out=_result(reason="MISSING_COMPLETE_PIT_CONFIRMATION",decision_at=now)
    if not isinstance(r1,dict) or not isinstance(us10y,dict) or not isinstance(r2,dict):
        return out
    event=r1.get("event_id")
    if not event or us10y.get("event_id")!=event or r2.get("event_id")!=event:
        out["reason_codes"]=["SOURCE_EVENT_MISMATCH"]
        return out
    out["event_id"]=event
    if (r1.get("source_quality")!="CAPTURED_REALTIME" or
        r1.get("data_ready") is not True or
        r1.get("stage")!="POST_EVENT_CONFIRMED"):
        out["reason_codes"]=["MISSING_R1_REALTIME_MARKET_AGREEMENT"]
        return out
    if us10y.get("provenance_mode")!="CAPTURED_REALTIME" or (
            us10y.get("series")!="US10Y_YIELD_BP" or us10y.get("unit")!="BPS"):
        out["reason_codes"]=["US10Y_SOURCE_NOT_GENUINE_INTRADAY_BPS"]
        return out
    if us10y.get("instrument") is None or us10y.get("provider") is None or (
            not _official_url(us10y.get("source_url"))):
        out["reason_codes"]=["US10Y_PROVENANCE_INCOMPLETE"]
        return out
    try:
        release=utc(r1["release_at"])
        r1_at=utc(r1["decision_at"])
        comm_at=utc(r2["at"])
        pre_at=utc(us10y["pre_available_at"])
        post_at=utc(us10y["post_available_at"])
        pre=float(us10y["pre_yield_bp"])
        post=float(us10y["post_yield_bp"])
        fed=float(r1["fed_repricing_bp"])
        yield2=float(r1["us2y_change_bp"])
        dxy=float(r1["dxy_proxy_return_pct"])
        if not all(isfinite(v) for v in (pre,post,fed,yield2,dxy)):
            raise ValueError("NONFINITE")
    except (KeyError,ValueError,TypeError):
        out["reason_codes"]=["INCOMPLETE_OR_NONFINITE_FEATURES"]
        return out
    if not (pre_at<release<=post_at<=r1_at<=now and
            comm_at<=now and
            post_at>=now-timedelta(minutes=10) and
            pre_at>=release-timedelta(minutes=30)):
        out["reason_codes"]=["FUTURE_OR_STALE_US10Y_SNAPSHOT"]
        return out
    y10=post-pre
    out["features"]={
        "fed_policy_path_repricing_bp":round(fed,5),
        "us2y_intraday_move_bp":round(yield2,5),
        "us10y_intraday_move_bp":round(y10,5),
        "dxy_proxy_return_pct":round(dxy,5),
        "us10y_provider":str(us10y["provider"]),
        "us10y_source_url":str(us10y["source_url"]),
        "market_snapshot_at_utc":post_at.isoformat(),
    }
    signs=(
        1 if fed>=2 else -1 if fed<=-2 else 0,
        1 if yield2>=1 else -1 if yield2<=-1 else 0,
        1 if y10>=1 else -1 if y10<=-1 else 0,
        1 if dxy>=.05 else -1 if dxy<=-.05 else 0,
    )
    if signs==(1,1,1,1):direction="SELL"
    elif signs==(-1,-1,-1,-1):direction="BUY"
    else:
        out["reason_codes"]=["POLICY_YIELDS_USD_CONFLICT_OR_TOO_SMALL"]
        return out
    if r1.get("search_bias")!=("SEARCH_SELL_REBOUND" if direction=="SELL"
                              else "SEARCH_BUY_DIP"):
        out["reason_codes"]=["R1_REPRICING_DIRECTION_CONTRADICTION"]
        return out
    if (r2.get("headline_stance")!=("HAWKISH" if direction=="SELL" else "DOVISH")
        or r2.get("macro_watch_bias")!=("SEARCH_SELL_REBOUND" if direction=="SELL"
                                      else "SEARCH_BUY_DIP")):
        out["reason_codes"]=["FED_COMMUNICATION_AND_MARKET_DISAGREE"]
        return out
    out["direction"]=direction
    out["watch_bias"]="SEARCH_SELL_REBOUND" if direction=="SELL" else "SEARCH_BUY_DIP"
    out["reason_codes"]=["RESEARCH_WATCH_ONLY_HISTORICAL_80PCT_NOT_VALIDATED"]
    return out

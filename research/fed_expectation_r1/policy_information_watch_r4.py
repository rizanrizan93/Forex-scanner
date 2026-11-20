"""Fed R4 policy/information shock read-only XAU BUY/SELL watch.

No network, no orders. Uses ONLY captured intraday before/after source
snapshots with event ID, contract, units, publication and ingestion times.
Unverified FRED DAILY real yields or retrospectively published USMPD
event shocks cannot be supplied as realtime. Statement + full FOMC
market reactions are known only after each window closes.
"""
from __future__ import annotations
from collections import defaultdict
from datetime import timedelta
from math import isfinite
from urllib.parse import urlsplit
from research.fed_expectation_r1.engine import utc

SERIES={
    "OIS1Y_RATE_BP":"BPS",
    "TIPS10Y_INTRADAY_YIELD_BP":"BPS",
    "SP500_INDEX_LEVEL":"INDEX_LEVEL",
    "USD_INDEX_PROXY_LEVEL":"INDEX_LEVEL",
}
DECISION_MAX_MINUTES=150
MAX_LAST_QUOTE_AGE_MINUTES=10

def _empty(event_id,at,reason):
    return {
        "contract":"FED_R4_POLICY_INFORMATION_XAU_READONLY_V1",
        "event_id":event_id,"decision_at":at.isoformat(),
        "direction":"WAIT","watch_bias":"WAIT",
        "policy_information_regime":"UNKNOWN",
        "market_data_status":"UNVERIFIED",
        "reason_codes":[reason],
        "measured_ois1y_bp":None,
        "measured_real_yield10y_bp":None,
        "measured_sp500_return_pct":None,
        "measured_usd_proxy_return_pct":None,
        "research_backtest_accuracy_is_live_probability":False,
        "predicted_probability":None,
        "verified_80pct_both_sides":False,
        "authority_to_send_orders":False,
        "authority_to_deploy":False,
    }

def _https(url):
    try:
        p=urlsplit(str(url))
        return p.scheme=="https" and bool(p.hostname) and p.username is None
    except (ValueError,TypeError):
        return False

def _validate_point(x,event_id,now):
    need={"event_id","series","unit","value","instrument","provider",
          "source_url","provenance_mode","bar_end_at","published_at","ingested_at"}
    if not need.issubset(x) or x["event_id"]!=event_id:
        raise ValueError("SNAPSHOT_PROVENANCE_OR_EVENT_ID_INVALID")
    s=x["series"]
    if s not in SERIES or x["unit"]!=SERIES[s]:
        raise ValueError("SERIES_OR_UNIT_INVALID")
    if x["provenance_mode"]!="CAPTURED_REALTIME":
        raise ValueError("EXPOST_OR_UNCAPTURED_IS_NOT_REALTIME")
    if not (_https(x["source_url"]) and str(x["instrument"]).strip()
            and str(x["provider"]).strip()):
        raise ValueError("INCOMPLETE_INTRADAY_PROVIDER")
    if s=="TIPS10Y_INTRADAY_YIELD_BP" and (
            x.get("quote_frequency")!="INTRADAY_CASH_TIPS"):
        raise ValueError("DAILY_TIPS_CANNOT_SUBSTITUTE_LIVE")
    value=float(x["value"])
    if not isfinite(value) or (SERIES[s]=="INDEX_LEVEL" and value<=0):
        raise ValueError("INVALID_REALTIME_PRICE")
    bar=utc(x["bar_end_at"]);published=utc(x["published_at"])
    ingested=utc(x["ingested_at"])
    available=max(bar,published,ingested)
    if available>now:
        raise ValueError("FUTURE_SNAPSHOT_LOOKAHEAD")
    return {**x,"value":value,"bar_end_at":bar,
            "available_at":available,"ingested_at":ingested}

def watch(event,points,*,decision_at,r2_context=None):
    now=utc(decision_at)
    if not isinstance(event,dict) or not {"event_id","release_at","source_url"}.issubset(event):
        raise ValueError("INCOMPLETE_FOMC_EVENT")
    if not _https(event["source_url"]):
        raise ValueError("UNVERIFIED_FOMC_ORIGIN")
    release=utc(event["release_at"])
    eid=event["event_id"]
    result=_empty(eid,now,"MISSING_REALTIME_FEATURES")
    if now<release:
        result["reason_codes"]=["EVENT_NOT_YET_RELEASED"]
        return result
    if now-release>timedelta(minutes=DECISION_MAX_MINUTES):
        result["reason_codes"]=["FOMC_EVENT_WINDOW_TOO_OLD"]
        return result
    if not isinstance(points,list):raise ValueError("POINTS_MUST_BE_LIST")
    data=[_validate_point(x,eid,now) for x in points]
    groups=defaultdict(list)
    for x in data:groups[x["series"]].append(x)
    delta={}
    for series in SERIES:
        group=groups[series]
        if not group:
            result["reason_codes"]=["MISSING_"+series]
            return result
        # Instrument and origin provider must remain unchanged
        post=[x for x in group if x["bar_end_at"]>=release and
              x["available_at"]>=release]
        if not post:
            result["reason_codes"]=["NO_AFTER_RELEASE_"+series]
            return result
        a=max(post,key=lambda x:x["available_at"])
        pre=[x for x in group if x["available_at"]<release and
             x["instrument"]==a["instrument"] and
             x["provider"]==a["provider"]]
        if not pre:
            result["reason_codes"]=["NO_SAME_INSTRUMENT_BEFORE_RELEASE_"+series]
            return result
        b=max(pre,key=lambda x:x["available_at"])
        if (now-a["available_at"]>timedelta(minutes=MAX_LAST_QUOTE_AGE_MINUTES)
            or b["available_at"]<release-timedelta(minutes=30)):
            result["reason_codes"]=["STALE_OR_NONCOMPARABLE_"+series]
            return result
        if SERIES[series]=="BPS":
            d=a["value"]-b["value"]
        else:
            d=100*(a["value"]/b["value"]-1)
        delta[series]=d
    ois=delta["OIS1Y_RATE_BP"]
    real=delta["TIPS10Y_INTRADAY_YIELD_BP"]
    stocks=delta["SP500_INDEX_LEVEL"]
    usd=delta["USD_INDEX_PROXY_LEVEL"]
    result["market_data_status"]="VALIDATED_CAPTURED_PRE_POST_INTRADAY"
    result.update(measured_ois1y_bp=round(ois,5),
                  measured_real_yield10y_bp=round(real,5),
                  measured_sp500_return_pct=round(stocks,5),
                  measured_usd_proxy_return_pct=round(usd,5))
    # Market policy/information sign separation.
    if abs(ois)<1.5 or abs(stocks)<.10:
        result["policy_information_regime"]="UNCONFIRMED"
        result["reason_codes"]=["MARKET_REPRICING_TOO_SMALL"]
        return result
    if ois*stocks>0:
        result["policy_information_regime"]="INFORMATION_LIKE"
        result["reason_codes"]=["EQUITY_REACTION_IDENTIFIES_INFORMATION_SHOCK_WATCH_WAIT"]
        return result
    result["policy_information_regime"]="POLICY_LIKE"
    if ois>=1.5 and real>=1 and usd>=.05 and stocks<=-.10:
        side="SELL"
    elif ois<=-1.5 and real<=-1 and usd<=-.05 and stocks>=.10:
        side="BUY"
    else:
        result["reason_codes"]=["REAL_YIELD_DOLLAR_POLICY_NOT_ALIGNED"]
        return result
    if r2_context is not None:
        if r2_context.get("event_id")!=eid or (
                utc(r2_context["at"])>now):
            result["reason_codes"]=["OFFICIAL_FOMC_DOCUMENT_CONTEXT_INVALID"]
            return result
        tone=r2_context.get("headline_stance")
        if (tone=="HAWKISH" and side=="BUY") or (tone=="DOVISH" and side=="SELL"):
            result["reason_codes"]=["FOMC_TEXT_VS_MARKET_CONTRADICTION"]
            return result
    result["direction"]=side
    result["watch_bias"]="SEARCH_SELL_REBOUND" if side=="SELL" else "SEARCH_BUY_DIP"
    result["reason_codes"]=["RESEARCH_WATCH_ONLY_80PCT_NOT_VALIDATED"]
    return result

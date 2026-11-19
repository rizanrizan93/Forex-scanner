"""Fed Expectation Macro Direction R1. Strict point-in-time RESEARCH ONLY.

The model measures monetary-policy repricing, NOT sentiment of a headline.
It produces a directional CONTEXT label for manual zone research, not orders.
Historical (post-event) observation is never converted into a pre-release signal.
"""
from __future__ import annotations
from datetime import datetime, timezone
from math import isfinite
from urllib.parse import urlparse

EXECUTION_AUTHORITY = False
EXECUTION_INFLUENCE = False
SOURCE_KIND = {
    "EXPECTED_FED_RATE_BP": ("BPS", "POLICY_EXPECTATION"),
    "US2Y_YIELD_BP": ("BPS", "NOMINAL_TREASURY_YIELD"),
    "DXY_PROXY_LEVEL": ("INDEX_LEVEL", "BROKER_USD_INDEX_PROXY"),
}
MIN_REPRICING_BP = 2.0
MIN_US2Y_MOVE_BP = 1.0
MIN_DXY_RETURN_PCT = 0.05
POST_EVENT_MAX_SECONDS = 900
FRESHNESS_SECONDS = {"EXPECTED_FED_RATE_BP":900,
                     "US2Y_YIELD_BP":600, "DXY_PROXY_LEVEL":300}
ALLOWED_EVENT_KINDS = frozenset({
    "FOMC_STATEMENT","FOMC_PRESS_CONFERENCE","FOMC_MINUTES",
    "CPI","CORE_PCE","NFP","FED_SPEECH",
})


def utc(v):
    if isinstance(v, datetime):
        d = v
    elif isinstance(v, str):
        d = datetime.fromisoformat(v.replace("Z","+00:00"))
    else:
        raise ValueError("INVALID_TIMESTAMP")
    if d.tzinfo is None or d.utcoffset() is None:
        raise ValueError("NAIVE_TIMESTAMP_NOT_ALLOWED")
    return d.astimezone(timezone.utc)


def _source_valid(url):
    x=urlparse(url)
    return x.scheme=="https" and bool(x.hostname) and x.username is None


def _checked_snapshot(s):
    required={"series","instrument","value","bar_end_at","published_at",
              "provider","source_url","provenance_mode","ingested_at"}
    if not required.issubset(s):
        raise ValueError("MISSING_SNAPSHOT_PROVENANCE_OR_TIMESTAMPS")
    series=s["series"]
    if series not in SOURCE_KIND:
        raise ValueError("UNSUPPORTED_MACRO_SERIES")
    if s.get("unit")!=SOURCE_KIND[series][0]:
        raise ValueError("MACRO_UNIT_MISMATCH")
    if not str(s["instrument"]).strip():
        raise ValueError("MISSING_INSTRUMENT_ID")
    if not _source_valid(s["source_url"]):
        raise ValueError("HTTPS_SOURCE_REQUIRED")
    if not str(s["provider"]).strip():
        raise ValueError("MISSING_PROVIDER")
    if s["provenance_mode"] not in ("CAPTURED_REALTIME","HISTORICAL_RECONSTRUCTED"):
        raise ValueError("UNKNOWN_PROVENANCE_MODE")
    if series=="DXY_PROXY_LEVEL" and s.get("is_official_ice_dxy") is True:
        raise ValueError("PROXY_CANNOT_BE_LABELLED_OFFICIAL_ICE_DXY")
    value=float(s["value"])
    if not isfinite(value):
        raise ValueError("NONFINITE_MACRO_VALUE")
    if series=="DXY_PROXY_LEVEL" and value<=0:
        raise ValueError("INVALID_INDEX_LEVEL")
    bar_end=utc(s["bar_end_at"])
    published=utc(s["published_at"])
    ingested=utc(s["ingested_at"])
    # No historical observation can be assigned before its price bar closes
    # or before its provider actually publishes. Archival import can occur
    # later; this is explicitly marked and is NOT prospective capture.
    available=max(bar_end,published)
    if s["provenance_mode"]=="CAPTURED_REALTIME":
        available=max(available,ingested)
    if series=="EXPECTED_FED_RATE_BP" and not s.get("meeting_or_contract"):
        raise ValueError("FED_EXPECTATION_CONTRACT_OR_MEETING_REQUIRED")
    return {**s,"value":value,"series":series,"bar_end_at":bar_end,
            "published_at":published,"ingested_at":ingested,
            "available_at":available}


def _pick(group, *, instrument, series, release, decision, is_post):
    points=[s for s in group if
            s["series"]==series and s["instrument"]==instrument and
            s["available_at"]<=decision and
            ((s["available_at"]>=release and s["bar_end_at"]>=release) if is_post
             else s["available_at"]<release)]
    return max(points,key=lambda x:(x["available_at"],x["bar_end_at"])) if points else None


def decide(event, snapshots, *, decision_at):
    """Return macro directional *context* only; fail closed for missing data.

    Pre/post snapshots refer to the SAME event, SAME instrument, SAME futures
    expiry/meeting for expected rates. Latest quote must be fresh. No text
    sentiment or daily Treasury yield is silently substituted.
    """
    if not {"event_id","event_kind","release_at","source_url"}.issubset(event):
        raise ValueError("EVENT_METADATA_INCOMPLETE")
    if event["event_kind"] not in ALLOWED_EVENT_KINDS:
        raise ValueError("UNSUPPORTED_EVENT_KIND")
    if not _source_valid(event["source_url"]):
        raise ValueError("UNVERIFIED_EVENT_SOURCE")
    release=utc(event["release_at"])
    at=utc(decision_at)
    result={"contract":"FED_EXPECTATION_MACRO_R1",
            "event_id":event["event_id"],
            "event_kind":event["event_kind"],
            "release_at":release.isoformat(),
            "decision_at":at.isoformat(),
            "direction":"WAIT","search_bias":"NONE",
            "stage":"PRE_EVENT_WAIT" if at<release else "DATA_INCOMPLETE",
            "reason_codes":[],"fed_repricing_bp":None,
            "us2y_change_bp":None,"dxy_proxy_return_pct":None,
            "source_quality":"UNVERIFIED",
            "data_ready":False,"execution_authority":False,
            "execution_influence":False}
    if at < release:
        result["reason_codes"]=["NO_FUTURE_POLICY_SURPRISE_BEFORE_RELEASE"]
        return result
    if at-release>__import__("datetime").timedelta(seconds=POST_EVENT_MAX_SECONDS):
        result["stage"]="EXPIRED_EVENT_WINDOW"
        result["reason_codes"]=["EVENT_REPRICING_WINDOW_EXPIRED"]
        return result
    data=[_checked_snapshot(s) for s in snapshots]
    # Source ids must not change across before/after comparisons.
    # Fed rate futures of a different meeting month are NOT comparable.
    identifiers={}
    for series in SOURCE_KIND:
        xs=[s for s in data if s["series"]==series and
            s["available_at"]<=at and s["bar_end_at"]<=at]
        if not xs:
            result["reason_codes"].append("MISSING_"+series)
            continue
        post_candidates=[s for s in xs if s["available_at"]>=release and s["bar_end_at"]>=release]
        if not post_candidates:
            result["reason_codes"].append("NO_POST_EVENT_"+series)
            continue
        post=max(post_candidates,key=lambda s:s["available_at"])
        ident=post["instrument"]
        if series=="EXPECTED_FED_RATE_BP":
            ident += "|"+str(post["meeting_or_contract"])
        comparable=[s for s in xs if s["instrument"]==post["instrument"] and
                    (series!="EXPECTED_FED_RATE_BP" or
                     s.get("meeting_or_contract")==post["meeting_or_contract"])]
        pre=[s for s in comparable if s["available_at"]<release]
        if not pre:
            result["reason_codes"].append("MISSING_PRE_EVENT_"+series)
            continue
        before=max(pre,key=lambda s:s["available_at"])
        if (at-post["available_at"]).total_seconds()>FRESHNESS_SECONDS[series]:
            result["reason_codes"].append("STALE_"+series)
            continue
        if before["bar_end_at"]<release-__import__("datetime").timedelta(minutes=30):
            result["reason_codes"].append("PRE_EVENT_BASELINE_TOO_OLD_"+series)
            continue
        if series=="DXY_PROXY_LEVEL":
            delta=100*(post["value"]/before["value"]-1)
            result["dxy_proxy_return_pct"]=round(delta,5)
        else:
            delta=post["value"]-before["value"]
            result["fed_repricing_bp" if series=="EXPECTED_FED_RATE_BP" else
                   "us2y_change_bp"]=round(delta,5)
        identifiers[series]={"instrument":post["instrument"],
                             "source_kind":SOURCE_KIND[series][1],
                             "pre_available_at":before["available_at"].isoformat(),
                             "post_available_at":post["available_at"].isoformat(),
                             "post_provenance_mode":post["provenance_mode"],
                             "source_url":post["source_url"]}
    result["series_provenance"]=identifiers
    if len(identifiers)<3:
        result["reason_codes"].append("NOT_ALL_THREE_PIT_FEATURES_READY")
        return result
    fed=result["fed_repricing_bp"]
    us2y=result["us2y_change_bp"]
    dxy=result["dxy_proxy_return_pct"]
    signs=(1 if fed>=MIN_REPRICING_BP else -1 if fed<=-MIN_REPRICING_BP else 0,
           1 if us2y>=MIN_US2Y_MOVE_BP else -1 if us2y<=-MIN_US2Y_MOVE_BP else 0,
           1 if dxy>=MIN_DXY_RETURN_PCT else -1 if dxy<=-MIN_DXY_RETURN_PCT else 0)
    result["data_ready"]=True
    if any(v["post_provenance_mode"]=="HISTORICAL_RECONSTRUCTED"
           for v in identifiers.values()):
        result["source_quality"]="HISTORICAL_ASOF_ESTIMATE_NOT_PROSPECTIVE"
    else:
        result["source_quality"]="CAPTURED_REALTIME"
    result["direction"]="WAIT"
    if signs==(1,1,1):
        result["direction"]="HAWKISH_REPRICING"
        result["search_bias"]="SEARCH_SELL_REBOUND"
        result["stage"]="POST_EVENT_CONFIRMED"
    elif signs==(-1,-1,-1):
        result["direction"]="DOVISH_REPRICING"
        result["search_bias"]="SEARCH_BUY_DIP"
        result["stage"]="POST_EVENT_CONFIRMED"
    else:
        result["stage"]="CONFLICT_OR_INSUFFICIENT_MOVE"
        result["reason_codes"].append("MACRO_SIGN_NOT_UNANIMOUS")
    return result

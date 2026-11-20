"""R6.5 XAU four-hour directional SEARCH candidate (non-executable).

Research hypothesis only. Uses completed M15/H1/H4 structure, a source-
audited macro context, and closed M5 liquidity stress. This is a WATCH
classification for deciding WHICH SIDE to search for; not a calibrated
four-hour forecast, probability, entry timing, or order authorization.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from math import isfinite

CONTRACT = "RIZAN_XAU_R65_FOUR_HOUR_DIRECTION_RESEARCH_V1"
PRICE = "RIZAN_XAU_FED_R6_MANUAL_AREA_V1"
MACRO = "RIZAN_XAU_R61_MARKET_DIRECTION_CONTEXT_V1"
LIQUIDITY = "RIZAN_R63_LIQUIDITY_STRESS_RESEARCH_READONLY_V1"
HORIZON = timedelta(hours=4)
NEWS_KINDS = frozenset(("FOMC", "CPI", "PPI", "NFP"))


def _timestamp(v):
    try:
        x = datetime.fromisoformat(str(v).replace("Z","+00:00"))
        return x.astimezone(timezone.utc) if x.tzinfo else None
    except (TypeError, ValueError, OverflowError):
        return None


def _result(now, reason):
    return {
        "contract": CONTRACT, "status": "WAIT",
        "search_side": "WAIT", "watch_side": "WAIT",
        "state": reason, "reason": reason,
        "issued_at": now.isoformat(), "target_at": (now + HORIZON).isoformat(),
        "recheck_after_minutes": 15, "horizon_hours": 4,
        "evidence_score": 0, "max_score": 5,
        "score_is_probability": False, "win_probability_pct": None,
        "validated_four_hour_accuracy": False,
        "macro_mode": "UNAVAILABLE", "calendar_state": "UNKNOWN",
        "h4_state": "UNKNOWN", "liquidity_state": "UNKNOWN",
        "nearest_pool": None, "liquidation_confirmed": False,
        "entry_permission": False, "authority_to_send_orders": False,
        "execution_influence": False, "cbot_influence": False,
        "frozen_v1_influence": False,
    }


def evaluate_four_hour_search(price, macro, *, now=None, news_events=None):
    """Classify prospective 4h direction for manual analysis, never orders.

    NEWS: an upcoming or just-released high-impact event (>= -30m and
    <=+4h) vetoes the 4h direction because it can reprice the market.
    A missing calendar remains explicitly UNVERIFIED and weakens any
    technical watch; it is not represented as a clean calendar.
    """
    now = _timestamp(now) if now is not None else datetime.now(timezone.utc)
    if now is None:
        raise ValueError("TZ_AWARE_DECISION_CLOCK_REQUIRED")
    out = _result(now, "MISSING_OR_UNTRUSTED_MARKET_SOURCES")
    if (not isinstance(price,dict) or price.get("contract") != PRICE
        or price.get("entry_allowed") is not False
        or price.get("authority_to_send_orders") is not False
        or not isinstance(macro,dict) or macro.get("contract") != MACRO
        or macro.get("entry_permission") is not False):
        return out
    issued=_timestamp(price.get("as_of"))
    quoted=_timestamp(price.get("quote_at"))
    closed=_timestamp(price.get("last_closed_m1"))
    macro_asof=_timestamp(macro.get("as_of_utc"))
    if not all((issued,quoted,closed,macro_asof)):
        out["state"]=out["reason"]="TIMESTAMPS_MISSING"
        return out
    if not (0 <= (now-issued).total_seconds() <= 45
            and 0 <= (now-quoted).total_seconds() <= 30
            and 0 <= (now-closed).total_seconds() <= 90
            and 0 <= (now-macro_asof).total_seconds() <= 120):
        out["state"]=out["reason"]="SOURCE_STALE_OR_FUTURE"
        return out
    ref=price.get("price")
    if (price.get("status") not in ("WAIT","WATCH")
        or not isinstance(ref,(int,float)) or not isfinite(ref) or ref<=0):
        out["state"]=out["reason"]="XAU_PRICE_UNAVAILABLE"
        return out

    m15,h1,h4=(price.get("bias_m15"),price.get("bias_h1"),price.get("bias_h4"))
    out["h4_state"] = h4 if h4 in ("BUY","SELL","MIXED","UNKNOWN") else "UNKNOWN"
    if m15 not in ("BUY","SELL") or h1 not in ("BUY","SELL") or m15!=h1:
        out["state"]=out["reason"]="WAIT_H1_M15_STRUCTURE_NOT_ALIGNED"
        return out
    side=h1
    out["watch_side"]=side
    if h4 in ("BUY","SELL") and h4!=side:
        out["state"]=out["reason"]="WAIT_H4_OPPOSING"
        return out
    if h4 not in ("BUY","SELL","MIXED","UNKNOWN"):
        out["state"]=out["reason"]="WAIT_H4_UNRELIABLE"
        return out
    liq=price.get("liquidity_context")
    if not isinstance(liq,dict) or liq.get("contract")!=LIQUIDITY:
        out["state"]=out["reason"]="WAIT_LIQUIDITY_SOURCE_MISSING"
        return out
    state=liq.get("state","UNKNOWN")
    out["liquidity_state"]=state
    if (liq.get("risk_veto") is True or state=="UNKNOWN"
        or state!="NORMAL"):
        out["state"]=out["reason"]="WAIT_LIQUIDITY_STRESS_OR_INCOMPLETE"
        return out
    if liq.get("liquidation_confirmed") is not False:
        out["state"]=out["reason"]="UNTRUSTED_LIQUIDATION_LABEL"
        return out

    # Macro direction can be explicitly WATCH only when fresh, official
    # daily Treasury evidence and fresh intraday DXY agree. The H1/H4
    # price signal is still independently unvalidated.
    macro_side=macro.get("direction")
    if macro_side not in ("WAIT","BUY","SELL"):
        out["state"]=out["reason"]="MACRO_DIRECTION_INVALID"
        return out
    if macro_side in ("BUY","SELL"):
        official=macro.get("daily_yields") or {}
        dxy=macro.get("dxy") or {}
        if (macro.get("daily_direction")!=macro_side
            or any(official.get(k,{}).get("valid_official_daily") is not True
                   for k in ("US2Y","US10Y"))
            or dxy.get("fresh") is not True):
            out["state"]=out["reason"]="MACRO_ALIGNMENT_UNVERIFIED"
            return out
        if macro_side!=side:
            out["macro_mode"]="OPPOSITE"
            out["state"]=out["reason"]="WAIT_MACRO_CONFLICT"
            return out
        out["macro_mode"]="ALIGNED"
    else:
        daily=macro.get("daily_direction","WAIT")
        if daily in ("BUY","SELL") and daily!=side:
            out["macro_mode"]="DAILY_LEAN_OPPOSITE"
            out["state"]=out["reason"]="WAIT_DAILY_YIELD_LEAN_CONFLICT"
            return out
        out["macro_mode"]="TECHNICAL_ONLY_UNVERIFIED"

    if news_events is None:
        out["calendar_state"]="UNVERIFIED"
    elif not isinstance(news_events,list):
        out["state"]=out["reason"]="INVALID_NEWS_CALENDAR"
        return out
    else:
        out["calendar_state"]="REPORTED_NO_NEAR_EVENT"
        for e in news_events:
            if not isinstance(e,dict):
                out["state"]=out["reason"]="INVALID_NEWS_EVENT"
                return out
            if e.get("event") not in NEWS_KINDS:
                continue
            event_at=_timestamp(e.get("at"))
            if event_at is None:
                out["state"]=out["reason"]="INVALID_NEWS_TIMESTAMP"
                return out
            if -1800 <= (event_at-now).total_seconds() <= HORIZON.total_seconds():
                out["calendar_state"]="MAJOR_EVENT_WITHIN_4H"
                out["state"]=out["reason"]="WAIT_NEWS_REPRICING_RISK"
                return out

    # Nearby prior session extrema are *possible* resting-liquidity
    # references. They can warn against chasing; they cannot prove stops.
    pool=price.get("liquidity_pools")
    atr=price.get("atr_m5")
    if isinstance(pool,dict) and isinstance(atr,(int,float)) and isfinite(atr) and atr>0:
        choices=[
            (abs(float(x["price"])-ref),x) for x in pool.get("levels",[])
            if isinstance(x,dict) and isinstance(x.get("price"),(int,float))
            and isfinite(x["price"]) and x["price"]>0
        ]
        if choices:
            dist,near=min(choices,key=lambda x:x[0])
            out["nearest_pool"]={"name":near.get("name"),"price":near["price"],
                                 "distance_atr_m5":round(dist/atr,2)}
            if dist/atr <= .30:
                out["state"]=out["reason"]="WAIT_NEAR_PRIOR_LIQUIDITY_EXTREME"
                return out

    # Descriptive evidence score, NOT predictive likelihood.
    score=2+1  # H1 + M15 structure alignment (3 of 5)
    score+=int(h4==side)
    score+=int(macro_side==side)
    out["evidence_score"]=score
    out["search_side"]="SEARCH_BUY" if side=="BUY" else "SEARCH_SELL"
    out["status"]="RESEARCH_WATCH"
    out["state"]="RESEARCH_SEARCH_SIDE_ONLY"
    out["reason"]=(
        "MACRO_PRICE_ALIGNED_UNTESTED_4H" if macro_side==side
        else "PRICE_STRUCTURE_ONLY_UNTESTED_4H"
    )
    return out

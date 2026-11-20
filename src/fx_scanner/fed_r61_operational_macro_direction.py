"""RIZAN R6.1 — independent public-market macro directional CONTEXT.

Existing pre-news worker already publishes official DAILY US2Y/US10Y,
a timestamped DXY proxy, and ZN/Treasury intraday pressure. This view
joins those READ-ONLY sources with proper observed-at freshness.

It is NOT Fed R4 FOMC surprise/expectation; no OIS1Y/TIPS pre/post
timestamps, no calibrated hit rate, no cBot or order authority.
"""
from __future__ import annotations
from datetime import UTC, datetime
from math import isfinite
from .dashboard_independent_feeds import macro_input

CONTRACT="RIZAN_XAU_R61_MARKET_DIRECTION_CONTEXT_V1"
DAILY_MAX_HOURS=72
DXY_MAX_SECONDS=300
FUTURES_MAX_SECONDS=300
CASH_MAX_SECONDS=120
MIN_DXY_PCT=.05
OFFICIAL_YIELD_PROVIDERS={"US_TREASURY_DAILY_XML","FEDERAL_RESERVE_FRED",
                           "FEDERAL_RESERVE_H15","US_TREASURY"}


def _utc(value):
    try:
        x=datetime.fromisoformat(str(value).replace("Z","+00:00"))
        return x.astimezone(UTC) if x.tzinfo else None
    except (ValueError,TypeError):
        return None


def _num(value):
    try:
        n=float(value)
        return n if isfinite(n) else None
    except (TypeError,ValueError):
        return None


def _fresh(value, now, limit):
    x=_utc(value)
    return x is not None and 0<=(now-x).total_seconds()<=limit


def _unavailable(now,reason):
    return {
        "contract":CONTRACT,"as_of_utc":now.isoformat(),
        "direction":"WAIT","strength":"UNAVAILABLE",
        "mode":"UNAVAILABLE","reason":reason,
        "daily_direction":"WAIT","intraday_direction":"WAIT",
        "dxy_direction":"WAIT","yield_intraday_direction":"WAIT",
        "daily_yields":{},"dxy":{},"intraday_yield":{},
        "quality_state":"UNAVAILABLE","quality_screened_bias":"UNAVAILABLE",
        "source":"PRE_NEWS_MACRO_WORKER",
        "model":"EXPLORATORY_MACRO_CONTEXT_NOT_FED_R4",
        "validated_fed_r4":False,"entry_permission":False,
        "execution_authority":False,"execution_influence":False,
        "claimed_80pct_accuracy":False,
    }


def assess_market_direction(snapshot, *, now=None):
    """Return BUY/SELL indicated by same-sign official daily yields.

    Stronger cross-asset context requires both independently *fresh*
    intraday dollar AND a separately timestamped Treasury pressure
    proxy in the same XAU direction. Opposite live information → WAIT.
    Intraday ZN is a FUTURES PRICE PROXY, never claimed cash yield.
    Any risk or execution decision requires a separately validated R4
    engine (currently unavailable), not this informational label.
    """
    now=now or datetime.now(UTC)
    if now.tzinfo is None:
        raise ValueError("UTC_AWARE_NOW_REQUIRED")
    now=now.astimezone(UTC)
    out=_unavailable(now,"NO_VALIDATED_SOURCE")
    try:
        payload=macro_input(snapshot,now=now)
    except (ValueError,TypeError,KeyError,AttributeError):
        out["reason"]="MACRO_SNAPSHOT_STALE_OR_INVALID"
        return out
    evaluation=payload["evaluation"]
    quality=evaluation.get("attribution_quality") or {}
    out["source_observed_at"]=payload["observed_at"]
    out["source_published_at"]=payload["published_at"]
    out["quality_state"]=str(quality.get("quality_state") or "UNAVAILABLE")
    out["quality_screened_bias"]=str(quality.get("quality_screened_bias") or "UNAVAILABLE")
    out["legacy_macro_bias"]=str(evaluation.get("broader_macro_bias") or "UNAVAILABLE")
    out["legacy_macro_is_not_confirmation"]=True
    components=evaluation.get("components") or {}
    signs=[]
    daily={}
    for name in ("US2Y","US10Y"):
        item=components.get(name) or {}
        delta=_num(item.get("delta"))
        current=_num(item.get("current"))
        valid=(item.get("freshness")=="FRESH" and
               item.get("delta_unit")=="BPS" and
               item.get("provider") in OFFICIAL_YIELD_PROVIDERS and
               delta is not None and current is not None and 0<current<30 and
               _fresh(item.get("observed_at"),now,DAILY_MAX_HOURS*3600))
        sign=(1 if delta<=-1 else -1 if delta>=1 else 0) if valid else None
        signs.append(sign)
        daily[name]={
            "yield_pct":current,
            "daily_delta_bps":delta,
            "observed_at":item.get("observed_at"),
            "provider":item.get("provider"),
            "valid_official_daily":bool(valid),
            "gold_direction":"BUY" if sign==1 else "SELL" if sign==-1 else "WAIT",
        }
    out["daily_yields"]=daily
    daily_sign=signs[0] if (len(signs)==2 and signs[0] in (1,-1)
                           and signs[0]==signs[1]) else None
    out["daily_direction"]="BUY" if daily_sign==1 else "SELL" if daily_sign==-1 else "WAIT"
    dxy=evaluation.get("dxy_intraday") or {}
    delta=_num(dxy.get("net_pct"))
    valid_dxy=(
        dxy.get("available") is True and
        str(dxy.get("source") or "").startswith("YAHOO_FINANCE_ICE_DXY_PROXY") and
        delta is not None and
        _fresh(dxy.get("current_at"),now,DXY_MAX_SECONDS))
    dollar_sign=(-1 if delta>=MIN_DXY_PCT else 1 if delta<=-MIN_DXY_PCT else 0) if valid_dxy else None
    out["dxy"]={
        "current":_num(dxy.get("current")),
        "change_pct":delta,
        "observed_at":dxy.get("current_at"),
        "source":dxy.get("source"),
        "fresh":valid_dxy,
        "level_is_official_ice_dxy":False,
    }
    out["dxy_direction"]=(
        "BUY" if dollar_sign==1 else "SELL" if dollar_sign==-1 else "FLAT"
        if dollar_sign==0 else "WAIT"
    )
    intra=evaluation.get("intraday_yield_context") or {}
    p=str(intra.get("futures_yield_pressure") or "").upper()
    source_basis=str(intra.get("timing_basis") or "")
    # Worker can keep a much older cash timestamp while using NEWER ZN:
    # only the explicit futures QUOTE timestamp can validate futures pressure.
    valid_zn=(intra.get("available") is True and
              p in ("YIELD_DOWN_PROXY","YIELD_UP_PROXY","YIELD_FLAT_PROXY") and
              _num(intra.get("futures_price")) is not None and
              _fresh(intra.get("futures_at"),now,FUTURES_MAX_SECONDS))
    if valid_zn:
        yield_sign=1 if p=="YIELD_DOWN_PROXY" else -1 if p=="YIELD_UP_PROXY" else 0
        basis="ZN_FUTURES_PRICE_PROXY"
        timestamp=intra.get("futures_at")
    else:
        state=str(intra.get("gold_implication") or "").upper()
        basis="CASH_YIELD"
        valid_cash=(intra.get("available") is True and
                    _fresh(intra.get("current_at"),now,CASH_MAX_SECONDS) and
                    "PROXY" not in str(intra.get("source") or "").upper() and
                    _num(intra.get("net_bps")) is not None)
        yield_sign=(1 if state in ("GOLD_SUPPORT","GOLD_TAILWIND","GOLD_SUPPORT_CONFIRMED")
                    else -1 if state in ("GOLD_HEADWIND","GOLD_HEADWIND_CONFIRMED")
                    else 0) if valid_cash else None
        timestamp=intra.get("current_at")
        if not valid_cash:
            basis="UNAVAILABLE"
    out["intraday_yield"]={
        "basis":basis,"observed_at":timestamp,
        "futures_price":_num(intra.get("futures_price")),
        "pressure":p,
        "available_for_direction":yield_sign is not None,
        "cash_yield_claimed_from_futures":False,
    }
    out["yield_intraday_direction"]=(
        "BUY" if yield_sign==1 else "SELL" if yield_sign==-1
        else "FLAT" if yield_sign==0 else "WAIT"
    )
    if daily_sign is None:
        out["reason"]="DAILY_YIELDS_MISSING_FLAT_OR_CONFLICT"
        return out
    # R3 tested the *same three direction signs* around completed FOMC
    # event windows, not these mixed-frequency rolling daily/vendor sources.
    # Hence this is still an UNVALIDATED context, never a validated
    # 2019-2026 BUY/SELL trading model or a D5 holding recommendation.
    # Daily Treasury alone is a LEAN, not an actionable market direction.
    out["direction"]="WAIT"
    out["strength"]="WAIT_FOR_DXY_CONFLUENCE"
    out["mode"]="OFFICIAL_DAILY_LEAN_ONLY"
    out["reason"]="OFFICIAL_YIELDS_ALIGNED_BUT_DXY_NOT_CONFIRMED"
    if dollar_sign not in (1,-1):
        # Intraday yields alone cannot replace the required DXY vote.
        if yield_sign in (1,-1) and yield_sign!=daily_sign:
            out["strength"]="CONFLICT"
            out["mode"]="MIXED_MARKETS"
            out["reason"]="FRESH_INTRADAY_YIELD_OPPOSES_DAILY_YIELDS"
        return out
    if dollar_sign!=daily_sign:
        out["strength"]="CONFLICT"
        out["mode"]="MIXED_MARKETS"
        out["reason"]="FRESH_DXY_OPPOSES_DAILY_YIELDS"
        return out
    if yield_sign in (1,-1) and yield_sign!=daily_sign:
        out["strength"]="CONFLICT"
        out["mode"]="MIXED_MARKETS"
        out["reason"]="FRESH_INTRADAY_YIELD_OPPOSES_DAILY_YIELDS"
        return out
    out["direction"]=out["daily_direction"]
    out["strength"]="YIELD_DXY_DIRECTIONAL_CONTEXT"
    out["mode"]="DAILY_YIELD_PLUS_FRESH_DXY"
    out["reason"]="OFFICIAL_US2Y_US10Y_AND_FRESH_DXY_ALIGNED"
    if yield_sign==daily_sign:
        out["intraday_direction"]=out["direction"]
        out["strength"]="ALIGNED_MARKET_CONTEXT"
        out["mode"]="INTRADAY_AND_DAILY_ALIGNED"
        out["reason"]="TREASURY_DAILY_DXY_AND_INTRADAY_YIELD_ALIGNED"
    # Even the strongest directional market CONTEXT is not FOMC R4.
    out["validated_fed_r4"]=False
    out["entry_permission"]=False
    return out

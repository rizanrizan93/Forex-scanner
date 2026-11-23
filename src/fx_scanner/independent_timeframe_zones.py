"""Independent H1/H4/D1/W1 candidate-direction supply/demand watch zones.

Each timeframe is routed ONLY to matching-timeframe zones from the validated
read-only cTrader manual reversal packet, without cross-timeframe direction
vetoes or fallback to archived model accuracy. Source BOS/displacement,
freshness, single-touch, quote-side and parent-close invalidation are checked.

This is zone preparation for manual review, never an entry trigger/order. No
per-candle win probability, profit target or executable price is inferred.
"""
from __future__ import annotations

from datetime import UTC, datetime
from math import isfinite

import pandas as pd

from .best_candidate_direction import VERSIONS
from .best_candidate_smc import verified

TFS = ("H1", "H4", "D1", "W1")
ZONE_MAX_AGE_H = {"H1": 24, "H4": 72, "D1": 24 * 30, "W1": 24 * 112}
CANDLE_MAX_AGE_H = {"H1": 70/60, "H4": 250/60, "D1": 72, "W1": 24 * 8}
MAX_PACKET_AGE_SEC = 420


def utc(value):
    t=pd.Timestamp(value)
    if t.tzinfo is None:
        raise ValueError("TIMEFRAME_ZONE_NAIVE_TIMESTAMP")
    return t.tz_convert("UTC")


def _empty(tf, primary, reason, *, state="WAIT_DATA"):
    row=primary.get(tf) or {}
    return {
        "tf": tf, "direction": row.get("direction", "WAIT"),
        "models": VERSIONS[tf].copy(), "state": state, "reason": reason,
        "zones": [], "last_price": None, "source_closed_at": None,
        "source_at": None, "target": row.get("target"),
        "execution_authority": False, "execution_influence": False,
        "entry_reference": None, "sl_reference": None,
        "tp_reference": None, "probability": None,
    }


def _number(v):
    return type(v) in (int, float) and isfinite(v)


def independent_zones(primary, snapshot, *, now=None):
    """Return four independently validated rows. No cross-horizon vote.

    Requires a fresh validated reversal packet (fetch_manual_map). The checks
    below also fail closed if a synthetic/stale packet bypasses that loader.
    """
    now=utc(now or datetime.now(UTC))
    primary=primary or {}
    snapshot=snapshot if isinstance(snapshot,dict) else {}
    out={}
    shared=None
    try:
        as_of=utc(snapshot["as_of"])
        price_at=utc(snapshot["price_observed_at"])
        price=snapshot.get("price")
        tf_fresh=snapshot.get("timeframe_fresh")
        closes=snapshot.get("timeframe_closed_at")
        zones=snapshot.get("zones")
        if (snapshot.get("contract")!="RIZAN_XAU_MANUAL_REVERSAL_MAP_V2"
                or snapshot.get("symbol")!="XAUUSD"
                or snapshot.get("source")!="CTRADER_MARKET_DATA_READ_ONLY"
                or snapshot.get("execution_authority") is not False
                or snapshot.get("execution_influence") is not False
                or snapshot.get("state")!="MAP_AVAILABLE"
                or snapshot.get("fresh") is not True
                or not isinstance(tf_fresh,dict) or not isinstance(closes,dict)
                or not isinstance(zones,list) or len(zones)>120
                or not _number(price) or price<=0
                or not 0<=(now-as_of).total_seconds()<=MAX_PACKET_AGE_SEC
                or not 0<=(now-price_at).total_seconds()<=MAX_PACKET_AGE_SEC
                or price_at>as_of):
            raise ValueError("ZONE_PACKET_INVALID_OR_STALE")
        shared=(as_of,float(price),tf_fresh,closes,zones)
    except (KeyError,TypeError,ValueError,OverflowError):
        shared=None

    for tf in TFS:
        row=primary.get(tf) or {}
        if not verified(row,tf,now):
            out[tf]=_empty(tf,primary, "DIRECTION_NOT_VALIDATED_OR_EXPIRED",
                            state="WAIT_DIRECTION")
            # A bad or unqualified direction must not carry numeric zones.
            out[tf]["direction"]="WAIT"
            continue
        if shared is None:
            out[tf]=_empty(tf,primary,"BROKER_ZONE_PACKET_STALE_OR_UNAVAILABLE")
            continue
        as_of,price,fresh,closes,zones=shared
        if fresh.get(tf) is not True:
            out[tf]=_empty(tf,primary,"SOURCE_TIMEFRAME_CANDLE_NOT_FRESH")
            continue
        try:
            closed=utc(closes[tf])
            age=(now-closed).total_seconds()/3600
            if not 0<=age<=CANDLE_MAX_AGE_H[tf] or closed>as_of:
                raise ValueError("SOURCE_CANDLE_EXPIRED")
        except (KeyError,TypeError,ValueError,OverflowError):
            out[tf]=_empty(tf,primary,"SOURCE_TIMEFRAME_CANDLE_INVALID")
            continue

        side=row["direction"]
        accepted=[]
        for z in zones:
            if (not isinstance(z,dict) or z.get("timeframe")!=tf
                    or z.get("direction")!=side
                    or z.get("source_type")!="BASE_DISPLACEMENT"
                    or z.get("structural_bos") is not True
                    or z.get("lifecycle") not in ("FRESH","RETESTED")
                    or z.get("risk_state")!="NORMAL"
                    or z.get("probability") is not None
                    or z.get("eligible") is not True):
                continue
            touches=z.get("touch_count")
            if type(touches) is not int or not 0<=touches<=1:
                continue
            try:
                low,high,invalid=(float(z[k]) for k in ("low","high","invalidation"))
                if not all(isfinite(x) for x in (low,high,invalid)) or not 0<low<high:
                    continue
                available=utc(z["available_at"])
                duration=(now-available).total_seconds()/3600
                if (not 0<=duration<=ZONE_MAX_AGE_H[tf]
                        or available>closed or available>as_of):
                    continue
                if side=="BUY":
                    if not invalid<low or price<=invalid or price<low:
                        continue
                    invalidation_breached=False
                else:
                    if not invalid>high or price>=invalid or price>high:
                        continue
                    invalidation_breached=False
                # A retested source zone may be watched but is never an entry
                # until a separate closed M15->M5 confirmation is completed.
                distance=max(low-price,price-high,0.0)
                accepted.append({
                    "tf":tf,"direction":side,"zone_id":str(z["zone_id"]),
                    "low":low,"high":high,"invalidation":invalid,
                    "source":"CTRADER_MARKET_DATA_READ_ONLY",
                    "formed_at":available.isoformat(),
                    "source_closed_at":closed.isoformat(),
                    "touch_count":touches,
                    "status":("IN_ZONE_WAIT_CONFIRMATION" if low<=price<=high
                              else "WATCH_REBOUND" if side=="SELL"
                              else "WATCH_PULLBACK"),
                    "distance":distance,
                    "confirmation":"CLOSED_M15_RECLAIM_THEN_M5_BOS_REQUIRED",
                    "execution_authority":False,"execution_influence":False,
                    "entry_reference":None,"sl_reference":None,"tp_reference":None,
                    "probability":None,
                })
            except (KeyError,TypeError,ValueError,OverflowError):
                continue
        accepted.sort(key=lambda z:(z["distance"],-utc(z["formed_at"]).timestamp()))
        valid=accepted[:2]
        out[tf]={
            "tf":tf,"direction":side, "models":VERSIONS[tf].copy(),
            "state":"WATCH_ZONE" if valid else "WAIT_ZONE",
            "reason":"MATCHED_TIMEFRAME_CLOSED_BOS_ZONE" if valid
                     else "NO_UNBROKEN_MATCHED_TIMEFRAME_BOS_ZONE",
            "zones":valid, "last_price":price,
            "source_at":as_of.isoformat(),"source_closed_at":closed.isoformat(),
            "target":row["target"],
            "execution_authority":False,"execution_influence":False,
            "entry_reference":None,"sl_reference":None,"tp_reference":None,
            "probability":None,
        }
    return out

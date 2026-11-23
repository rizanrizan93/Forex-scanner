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

def fresh_m1_fallback_packet(market, *, now=None):
    """Build H1/H4-only closed-candle zone snapshot from validated manual-R3 M1.

    market MUST be returned by manual_r3_feed.fetch_market(), whose source and
    OHLC contracts are independently validated. Never extrapolate D1 or W1
    from a 2-8 day M1 window. A short or gappy series is WAIT, not padded.
    """
    from .manual_reversal_map import detect,project,annotate_intraday_zone_risk

    now=utc(now or datetime.now(UTC))
    if not isinstance(market,dict) or not isinstance(market.get("frame"),pd.DataFrame):
        raise ValueError("M1_FALLBACK_MARKET_UNAVAILABLE")
    at=utc(market.get("as_of"))
    if not 0<=(now-at).total_seconds()<=90:
        raise ValueError("M1_FALLBACK_PUBLISHER_STALE")
    m1=market["frame"]
    required=("open","high","low","close")
    if (not set(required).issubset(m1.columns)
            or m1.empty or m1.index.tz is None or m1.index.has_duplicates
            or not m1.index.is_monotonic_increasing
            or not all(m1.index.second==0)
            or not all(m1.index.microsecond==0)):
        raise ValueError("M1_FALLBACK_SOURCE_CANDLES_INVALID")
    last_close=m1.index[-1]+pd.Timedelta(minutes=1)
    if not 0<=(now-last_close).total_seconds()<=120:
        raise ValueError("M1_FALLBACK_LAST_CANDLE_STALE")
    if not all(pd.api.types.is_numeric_dtype(m1[col]) for col in required):
        raise ValueError("M1_FALLBACK_OHLC_TYPES_INVALID")
    if (not m1[list(required)].notna().all().all()
            or (m1.low<=0).any() or (m1.high<m1[["open","close","low"]].max(axis=1)).any()
            or (m1.low>m1[["open","close"]].min(axis=1)).any()):
        raise ValueError("M1_FALLBACK_OHLC_GEOMETRY_INVALID")

    def closed(minutes):
        q=m1.resample(f"{minutes}min",label="left",closed="left").agg(
            open=("open","first"),high=("high","max"),
            low=("low","min"),close=("close","last"),
            count=("close","size")
        )
        q=q.loc[(q["count"]==minutes)&
                (q.index+pd.Timedelta(minutes=minutes)<=now)]
        q=q.drop(columns="count").dropna()
        if q.empty:return q
        # Do not bridge gaps: use only uninterrupted source-TF history.
        cut=len(q)-1
        step=pd.Timedelta(minutes=minutes)
        while cut>0 and q.index[cut]-q.index[cut-1]==step:
            cut-=1
        return q.iloc[cut:]

    def records(q):
        return [
            {"timestamp":ts.isoformat(),"open":float(bar.open),
             "high":float(bar.high),"low":float(bar.low),"close":float(bar.close)}
            for ts,bar in q.iterrows()
        ]
    price=float(m1.close.iloc[-1])
    fresh={"H1":False,"H4":False,"D1":False,"W1":False}
    closed_at={"H1":None,"H4":None,"D1":None,"W1":None}
    zones=[]
    for tf,minutes in (("H1",60),("H4",240)):
        q=closed(minutes)
        if len(q)<24:continue
        at_close=q.index[-1]+pd.Timedelta(minutes=minutes)
        if not 0<=(now-at_close).total_seconds()<=CANDLE_MAX_AGE_H[tf]*3600:
            continue
        fresh[tf]=True
        closed_at[tf]=at_close.isoformat()
        zones+=detect(records(q.tail(80)),tf,now)
    m15=closed(15)
    m15frame=pd.DataFrame(records(m15)) if len(m15) else pd.DataFrame(
        columns=["timestamp","open","high","low","close"])
    for col in ("timestamp",):
        if len(m15frame):m15frame[col]=pd.to_datetime(m15frame[col],utc=True)
    selected=annotate_intraday_zone_risk(project(zones,price),m15frame,price)
    return {
        "contract":"RIZAN_XAU_MANUAL_REVERSAL_MAP_V2",
        "symbol":"XAUUSD","source":"CTRADER_MARKET_DATA_READ_ONLY",
        "source_detail":"VALIDATED_FRESH_M1_REAGGREGATED_H1_H4_ONLY",
        "state":"MAP_AVAILABLE","fresh":True,
        "as_of":at.isoformat(),"price_observed_at":last_close.isoformat(),
        "price":price,"timeframe_fresh":fresh,
        "timeframe_closed_at":closed_at,"zones":selected,
        "execution_authority":False,"execution_influence":False,
        "probability":None,
    }

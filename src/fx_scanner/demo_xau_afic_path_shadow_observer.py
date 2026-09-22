from __future__ import annotations

import hashlib
import os
from bisect import bisect_right
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from math import ceil, floor, isfinite
from typing import Any, Sequence

import numpy as np
import pandas as pd

from .config import load_project_config
from .execution.factory import build_ctrader_research_feed
from .execution.policy import load_execution_policy
from .models import Bar, ensure_utc
from .storage.supabase_operational import SupabaseOperationalStore

SYMBOL="XAUUSD"
STRATEGY_ID="XAU_AFIC_PATH_SHADOW_V1"
FORWARD_CONTRACT="XAU_AFIC_PATH_SHADOW_FORWARD_V1"
WORKER_NAME="ctrader_demo_xau_afic_path_shadow_observer"
EVENT_TYPE="DEMO_XAU_AFIC_PATH_SHADOW_EVALUATION"

REQUEST_COUNT=1500
LOOKBACK_DAYS=18
PIVOT_LEFT=2
PIVOT_RIGHT=2
ZONE_MAX_AGE_HOURS=24
FIRST_LEG_HORIZON_M15=64
CONFIRM_WINDOW_M15=8
DISPLACEMENT_RANGE_ATR=1.0
DISPLACEMENT_BODY_FRACTION=0.50
ORIGIN_SEARCH_H1_BARS=6
STOP_BUFFER_ATR=0.10
MIN_PUBLISHED_RR=1.50
ROUND_STEP_USD=10.0
ROUND_FRONT_RUN_USD=1.0
TP_STEP_USD=3.0
MAX_TP_STEPS=7


@dataclass(frozen=True)
class Pivot:
    kind:str
    price:float
    pivot_at:datetime
    available_at:datetime


@dataclass(frozen=True)
class OriginZone:
    direction:str
    available_at:datetime
    bos_at:datetime
    bos_level:float
    low:float
    high:float
    h1_atr:float
    origin_at:datetime
    displacement_range_atr:float
    displacement_body_fraction:float


def _account_label()->str:
    return (
        os.getenv("CTRADER_ACCOUNT_ID","").strip()
        or os.getenv("CTRADER_TRADER_LOGIN","").strip()
    )


def _closed_m15(rows:Sequence[Bar],*,as_of:datetime)->tuple[Bar,...]:
    now=ensure_utc(as_of)
    return tuple(
        row for row in sorted(rows,key=lambda x:ensure_utc(x.timestamp))
        if ensure_utc(row.timestamp)+timedelta(minutes=15)<=now
    )


def _frame(rows:Sequence[Bar])->pd.DataFrame:
    return pd.DataFrame(
        [{
            "time":pd.Timestamp(ensure_utc(x.timestamp)),
            "open":float(x.open),"high":float(x.high),
            "low":float(x.low),"close":float(x.close),
        } for x in rows]
    ).sort_values("time").reset_index(drop=True)


def _resample(rows:Sequence[Bar],rule:str)->pd.DataFrame:
    x=_frame(rows).set_index("time")
    return x.resample(rule,label="right",closed="left").agg(
        open=("open","first"),high=("high","max"),low=("low","min"),close=("close","last")
    ).dropna().reset_index()


def _resample_completed(rows:Sequence[Bar],rule:str,*,as_of:datetime)->pd.DataFrame:
    frame=_resample(rows,rule)
    cutoff=pd.Timestamp(ensure_utc(as_of))
    # Right-labelled bars become causal only when their right boundary has
    # passed. This excludes the currently forming H1/H4 candle.
    return frame[frame["time"]<=cutoff].reset_index(drop=True)


def _atr(frame:pd.DataFrame,period:int=14)->pd.Series:
    high=frame["high"].astype(float)
    low=frame["low"].astype(float)
    close=frame["close"].astype(float)
    prev=close.shift(1)
    tr=pd.concat([(high-low),(high-prev).abs(),(low-prev).abs()],axis=1).max(axis=1)
    return tr.ewm(alpha=1.0/period,adjust=False,min_periods=period).mean()


def _pivots(frame:pd.DataFrame)->tuple[Pivot,...]:
    rows=frame.reset_index(drop=True)
    out=[]
    for i in range(PIVOT_LEFT,len(rows)-PIVOT_RIGHT):
        hi=float(rows.iloc[i]["high"]);lo=float(rows.iloc[i]["low"])
        left=rows.iloc[i-PIVOT_LEFT:i]
        right=rows.iloc[i+1:i+1+PIVOT_RIGHT]
        pt=ensure_utc(rows.iloc[i]["time"].to_pydatetime())
        av=ensure_utc(rows.iloc[i+PIVOT_RIGHT]["time"].to_pydatetime())
        if hi>float(left["high"].max()) and hi>=float(right["high"].max()):
            out.append(Pivot("HIGH",hi,pt,av))
        if lo<float(left["low"].min()) and lo<=float(right["low"].min()):
            out.append(Pivot("LOW",lo,pt,av))
    return tuple(out)


def _available_pivots(pivots:Sequence[Pivot],timestamp)->tuple[Pivot,...]:
    t=ensure_utc(timestamp)
    return tuple(p for p in pivots if ensure_utc(p.available_at)<=t)


def _origin_zones(rows:Sequence[Bar],*,as_of:datetime)->tuple[OriginZone,...]:
    h1=_resample_completed(rows,"1h",as_of=as_of)
    h1["atr14"]=_atr(h1,14)
    pivots=_pivots(h1)
    out=[]
    for i in range(max(20,ORIGIN_SEARCH_H1_BARS+1),len(h1)):
        r=h1.iloc[i]
        t=ensure_utc(r["time"].to_pydatetime())
        atr=float(r.get("atr14",np.nan))
        if not isfinite(atr) or atr<=0:
            continue
        o=float(r["open"]);h=float(r["high"]);l=float(r["low"]);c=float(r["close"])
        prev_close=float(h1.iloc[i-1]["close"])
        rng=max(h-l,1e-12);body=abs(c-o)
        body_frac=body/rng;range_atr=rng/atr
        if range_atr<DISPLACEMENT_RANGE_ATR or body_frac<DISPLACEMENT_BODY_FRACTION:
            continue
        ps=_available_pivots(pivots,t)
        highs=[p for p in ps if p.kind=="HIGH" and p.pivot_at<t]
        lows=[p for p in ps if p.kind=="LOW" and p.pivot_at<t]
        direction=None;bos=None
        if c>o and highs:
            level=highs[-1].price
            if prev_close<=level and c>level:
                direction="LONG";bos=float(level)
        if direction is None and c<o and lows:
            level=lows[-1].price
            if prev_close>=level and c<level:
                direction="SHORT";bos=float(level)
        if direction is None:
            continue
        origin=None
        for j in range(i-1,max(-1,i-ORIGIN_SEARCH_H1_BARS-1),-1):
            rr=h1.iloc[j];oo=float(rr["open"]);cc=float(rr["close"])
            opposite=(direction=="LONG" and cc<oo) or (direction=="SHORT" and cc>oo)
            if opposite:
                origin=rr;break
        if origin is None:
            continue
        out.append(OriginZone(
            direction=direction,available_at=t,bos_at=t,bos_level=float(bos),
            low=float(origin["low"]),high=float(origin["high"]),h1_atr=atr,
            origin_at=ensure_utc(origin["time"].to_pydatetime()),
            displacement_range_atr=float(range_atr),
            displacement_body_fraction=float(body_frac),
        ))
    return tuple(out)


def _stable_zone_id(zone:OriginZone)->str:
    """Return a zone identity that does not depend on the current H4 map."""
    raw="|".join((
        str(zone.direction).upper(),
        ensure_utc(zone.origin_at).isoformat(),
        ensure_utc(zone.available_at).isoformat(),
        f"{float(zone.low):.8f}",
        f"{float(zone.high):.8f}",
        f"{float(zone.bos_level):.8f}",
    ))
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def _zone_touch_lifecycle(
    zone:OriginZone,
    *,
    bars:Sequence[Bar]|None,
    map_at,
)->dict[str,Any]:
    """Describe durable closed-M15 touch history independently from H4 remaps.

    A touch becomes durable evidence only after the M15 bar is closed and
    available to this observer. first_touch_at is the first actionable touch
    since the zone became available; map_first_touch_at is restricted to the
    current H4 map.
    """
    t=ensure_utc(map_at)
    available=ensure_utc(zone.available_at)
    rows=tuple(sorted(tuple(bars or ()),key=lambda row:ensure_utc(row.timestamp)))
    actionable=tuple(
        row for row in rows if ensure_utc(row.timestamp)>=available
    )
    first_touch_at=None
    map_first_touch_at=None
    invalidated_at=None
    for row in actionable:
        ts=ensure_utc(row.timestamp)
        if _touch(row,zone):
            if first_touch_at is None:
                first_touch_at=ts
            if ts>=t and map_first_touch_at is None:
                map_first_touch_at=ts
        if _invalidated(row,zone):
            invalidated_at=ts
            break

    if map_first_touch_at is not None:
        lifecycle="TOUCHED_DURING_CURRENT_MAP"
    elif first_touch_at is not None and first_touch_at<t:
        lifecycle="TOUCHED_BEFORE_CURRENT_MAP"
    else:
        lifecycle="UNTOUCHED"
    invalidated_before_map=bool(
        invalidated_at is not None and invalidated_at<t
    )
    zone_lifecycle=(
        "INVALIDATED_BEFORE_CURRENT_MAP"
        if invalidated_before_map
        else "INVALIDATED_DURING_CURRENT_MAP"
        if invalidated_at is not None
        else lifecycle
    )

    return {
        "zone_id":_stable_zone_id(zone),
        "first_touch_at":None if first_touch_at is None else first_touch_at.isoformat(),
        "map_first_touch_at":None
            if map_first_touch_at is None
            else map_first_touch_at.isoformat(),
        "touch_lifecycle":lifecycle,
        "zone_lifecycle":zone_lifecycle,
        "origin_invalidated_at":None
            if invalidated_at is None
            else invalidated_at.isoformat(),
        "invalidation_known_at":None
            if invalidated_at is None
            else (invalidated_at+timedelta(minutes=15)).isoformat(),
        "invalidated_before_map":invalidated_before_map,
    }


def _zone_diagnostics(
    zones:Sequence[OriginZone],
    *,
    map_at,
    price:float,
    continuation:str,
    bars:Sequence[Bar]|None=None,
)->dict[str,Any]:
    t=ensure_utc(map_at)
    all_zones=tuple(zones)
    available_by_time=tuple(
        z for z in all_zones
        if ensure_utc(z.available_at)<=t
    )
    fresh=tuple(
        z for z in available_by_time
        if t-ensure_utc(z.available_at)<=timedelta(hours=ZONE_MAX_AGE_HOURS)
    )
    closed_bars=tuple(bars or ())
    lifecycle_by_id={
        _stable_zone_id(z):_zone_touch_lifecycle(z,bars=closed_bars,map_at=t)
        for z in fresh
    }
    active_fresh=tuple(
        z for z in fresh
        if not lifecycle_by_id[_stable_zone_id(z)]["invalidated_before_map"]
    )
    matching=tuple(z for z in active_fresh if z.direction==continuation)
    if continuation=="SHORT":
        correct_side=tuple(z for z in matching if z.low>price)
        wrong_side=tuple(z for z in matching if z.low<=price)
    else:
        correct_side=tuple(z for z in matching if z.high<price)
        wrong_side=tuple(z for z in matching if z.high>=price)

    stale=tuple(
        z for z in available_by_time
        if t-ensure_utc(z.available_at)>timedelta(hours=ZONE_MAX_AGE_HOURS)
    )
    future=tuple(
        z for z in all_zones
        if ensure_utc(z.available_at)>t
    )
    opposite=tuple(z for z in fresh if z.direction!=continuation)
    latest_price=float(closed_bars[-1].close) if closed_bars else float(price)
    latest_at=(
        ensure_utc(closed_bars[-1].timestamp)
        if closed_bars else t
    )

    def _distance_to_zone(px:float,z:OriginZone)->float:
        if px<z.low:
            return float(z.low-px)
        if px>z.high:
            return float(px-z.high)
        return 0.0

    alternative_watch=[]
    for z in opposite:
        lifecycle=lifecycle_by_id[_stable_zone_id(z)]
        invalidated_at=lifecycle["origin_invalidated_at"]
        if continuation=="SHORT" and z.direction=="LONG":
            role=(
                "DOWNSIDE_DESTINATION_LONG_REVERSAL_WATCH"
                if z.high<price else
                "COUNTERTREND_LONG_REVERSAL_WATCH"
            )
        elif continuation=="LONG" and z.direction=="SHORT":
            role=(
                "UPSIDE_DESTINATION_SHORT_REVERSAL_WATCH"
                if z.low>price else
                "COUNTERTREND_SHORT_REVERSAL_WATCH"
            )
        else:
            role="OPPOSITE_DIRECTION_REVERSAL_WATCH"
        alternative_watch.append({
            "zone_id":lifecycle["zone_id"],
            "direction":z.direction,
            "role":role,
            "low":z.low,
            "high":z.high,
            "bos_level":z.bos_level,
            "available_at":z.available_at.isoformat(),
            "origin_at":z.origin_at.isoformat(),
            "age_at_map_hours":(
                t-ensure_utc(z.available_at)
            ).total_seconds()/3600.0,
            "current_age_hours":max(
                0.0,
                (latest_at-ensure_utc(z.available_at)).total_seconds()/3600.0,
            ),
            "distance_from_map_anchor_points":_distance_to_zone(float(price),z),
            "distance_from_latest_price_points":_distance_to_zone(latest_price,z),
            "displacement_range_atr":z.displacement_range_atr,
            "displacement_body_fraction":z.displacement_body_fraction,
            "first_touch_at":lifecycle["first_touch_at"],
            "map_first_touch_at":lifecycle["map_first_touch_at"],
            "touch_lifecycle":lifecycle["touch_lifecycle"],
            "zone_lifecycle":lifecycle["zone_lifecycle"],
            "invalidated_at":invalidated_at,
            "invalidation_known_at":lifecycle["invalidation_known_at"],
            "invalidated_before_map":lifecycle["invalidated_before_map"],
            "status":"INVALIDATED" if invalidated_at else (
                "TOUCHED_WATCH_REVERSAL"
                if lifecycle["map_first_touch_at"]
                else "ACTIVE_WATCH"
            ),
            "auto_execution_authority":False,
            "required_confirmation":"H1/M15_BULLISH_REVERSAL_REMAP" if z.direction=="LONG"
                else "H1/M15_BEARISH_REVERSAL_REMAP",
        })
    alternative_watch.sort(
        key=lambda item:(
            item["status"]=="INVALIDATED",
            float(item["distance_from_latest_price_points"]),
            float(item["current_age_hours"]),
        )
    )

    nearest=None
    if correct_side:
        if continuation=="SHORT":
            nearest=min(correct_side,key=lambda z:z.low-price)
            distance=max(0.0,nearest.low-price)
        else:
            nearest=min(correct_side,key=lambda z:price-z.high)
            distance=max(0.0,price-nearest.high)
        nearest_payload={
            "direction":nearest.direction,
            "zone_id":_stable_zone_id(nearest),
            "low":nearest.low,
            "high":nearest.high,
            "available_at":nearest.available_at.isoformat(),
            "origin_at":nearest.origin_at.isoformat(),
            "age_hours":(
                t-ensure_utc(nearest.available_at)
            ).total_seconds()/3600.0,
            "distance_points":distance,
            "displacement_range_atr":nearest.displacement_range_atr,
            "displacement_body_fraction":nearest.displacement_body_fraction,
        }
    else:
        nearest_payload=None

    return {
        "map_at":t.isoformat(),
        "map_price":float(price),
        "continuation_direction":continuation,
        "origin_zones_total":len(all_zones),
        "available_at_map":len(available_by_time),
        "fresh_within_24h":len(fresh),
        "structurally_active_fresh":len(active_fresh),
        "invalidated_before_map":len(fresh)-len(active_fresh),
        "stale_over_24h":len(stale),
        "future_not_available_at_map":len(future),
        "matching_direction_fresh":len(matching),
        "opposite_direction_fresh":len(opposite),
        "alternative_reversal_watch_zones":alternative_watch[:5],
        "active_alternative_watch_count":sum(
            1 for item in alternative_watch
            if item["status"]!="INVALIDATED"
        ),
        "wrong_side_of_anchor":len(wrong_side),
        "eligible_correct_side":len(correct_side),
        "nearest_eligible":nearest_payload,
        "selection_result":"ELIGIBLE_ZONE_FOUND" if correct_side else "NO_ELIGIBLE_MAP_ZONE",
        "not_bug_if_zero_eligible":True,
    }


def _choose_zone(
    zones:Sequence[OriginZone],
    *,
    map_at,
    price:float,
    continuation:str,
    bars:Sequence[Bar]|None=None,
)->OriginZone|None:
    diagnostics=_zone_diagnostics(
        zones,map_at=map_at,price=price,continuation=continuation,bars=bars
    )
    nearest=dict(diagnostics.get("nearest_eligible") or {})
    if not nearest:
        return None
    t=ensure_utc(map_at)
    nearest_zone_id=str(nearest.get("zone_id") or "")
    candidates=[
        z for z in zones
        if ensure_utc(z.available_at)<=t
        and t-ensure_utc(z.available_at)<=timedelta(hours=ZONE_MAX_AGE_HOURS)
        and z.direction==continuation
        and not _zone_touch_lifecycle(z,bars=bars,map_at=t)["invalidated_before_map"]
    ]
    if nearest_zone_id:
        candidates=[z for z in candidates if _stable_zone_id(z)==nearest_zone_id]
    if continuation=="SHORT":
        candidates=[z for z in candidates if z.low>price]
        return None if not candidates else min(candidates,key=lambda z:z.low-price)
    candidates=[z for z in candidates if z.high<price]
    return None if not candidates else min(candidates,key=lambda z:price-z.high)


def _touch(row:Bar,z:OriginZone)->bool:
    return float(row.low)<=z.high and float(row.high)>=z.low


def _invalidated(row:Bar,z:OriginZone)->bool:
    return float(row.close)>z.high if z.direction=="SHORT" else float(row.close)<z.low


def _engulf_reject(rows:Sequence[Bar],i:int,z:OriginZone)->bool:
    if i<=0 or not _touch(rows[i],z):
        return False
    prev=rows[i-1];row=rows[i]
    po,pc=float(prev.open),float(prev.close)
    o,c=float(row.open),float(row.close)
    if z.direction=="SHORT":
        return bool(pc>po and c<o and o>=pc and c<=po and c<=z.low)
    return bool(pc<po and c>o and o<=pc and c>=po and c>=z.high)


def _stop(z:OriginZone)->float:
    return (
        z.low-STOP_BUFFER_ATR*z.h1_atr
        if z.direction=="LONG"
        else z.high+STOP_BUFFER_ATR*z.h1_atr
    )


def _ladder(entry:float,terminal:float,direction:str)->tuple[float,...]:
    sign=1.0 if direction=="LONG" else -1.0
    distance=(terminal-entry)*sign
    if distance<TP_STEP_USD:
        return ()
    steps=min(MAX_TP_STEPS,int(np.floor(distance/TP_STEP_USD+1e-12)))
    return tuple(round(entry+sign*TP_STEP_USD*i,5) for i in range(1,steps+1))


def _target(entry:float,stop:float,direction:str):
    sign=1.0 if direction=="LONG" else -1.0
    risk=(entry-stop)*sign
    if not isfinite(risk) or risk<=0:
        return None
    threshold=entry+sign*MIN_PUBLISHED_RR*risk
    if direction=="LONG":
        round_level=ceil(threshold/ROUND_STEP_USD)*ROUND_STEP_USD
        front=round_level-ROUND_FRONT_RUN_USD
        while (front-entry)/risk<MIN_PUBLISHED_RR:
            round_level+=ROUND_STEP_USD;front=round_level-ROUND_FRONT_RUN_USD
    else:
        round_level=floor(threshold/ROUND_STEP_USD)*ROUND_STEP_USD
        front=round_level+ROUND_FRONT_RUN_USD
        while (entry-front)/risk<MIN_PUBLISHED_RR:
            round_level-=ROUND_STEP_USD;front=round_level+ROUND_FRONT_RUN_USD
    ladder=_ladder(entry,front,direction)
    if not ladder:
        return None
    terminal=ladder[-1]
    if (terminal-entry)*sign/risk<MIN_PUBLISHED_RR:
        return None
    return float(round_level),float(terminal),ladder


def _h4_features(h4:pd.DataFrame,i:int,*,continuation:str,zone:OriginZone,map_price:float)->dict[str,Any]:
    if i<1:
        return {}
    r=h4.iloc[i];p=h4.iloc[i-1]
    atr_series=_atr(h4,14)
    atr=float(atr_series.iloc[i])
    o=float(r["open"]);h=float(r["high"]);l=float(r["low"]);c=float(r["close"])
    po=float(p["open"]);ph=float(p["high"]);pl=float(p["low"]);pc=float(p["close"])
    rng=max(h-l,1e-12);body=abs(c-o)
    loc=(c-l)/rng
    bullish=continuation=="LONG"
    directional_loc=loc if bullish else 1.0-loc
    rejection=(max(0.0,min(o,c)-l) if bullish else max(0.0,h-max(o,c)))/rng
    breakout=(c>ph) if bullish else (c<pl)
    engulf=(c>o and pc<po and o<=pc and c>=po) if bullish else (c<o and pc>po and o>=pc and c<=po)
    zone_distance=(map_price-zone.high) if bullish else (zone.low-map_price)
    return {
        "h4_range_atr":None if not isfinite(atr) or atr<=0 else rng/atr,
        "h4_body_atr":None if not isfinite(atr) or atr<=0 else body/atr,
        "h4_body_fraction":body/rng,
        "h4_directional_close_location":directional_loc,
        "h4_rejection_wick_fraction":rejection,
        "h4_directional_breakout":bool(breakout),
        "h4_body_engulfing":bool(engulf),
        "zone_distance_atr":None if not isfinite(atr) or atr<=0 else max(0.0,zone_distance)/atr,
        "zone_age_hours":(ensure_utc(r["time"].to_pydatetime())-ensure_utc(zone.available_at)).total_seconds()/3600.0,
        "origin_displacement_range_atr":zone.displacement_range_atr,
        "origin_displacement_body_fraction":zone.displacement_body_fraction,
    }


def evaluate_afic_shadow(rows:Sequence[Bar],*,as_of:datetime)->dict[str,Any]:
    bars=_closed_m15(rows,as_of=as_of)
    if len(bars)<300:
        return {"state":"INSUFFICIENT_HISTORY","closed_m15":len(bars),"execution_influence":False}

    h4=_resample_completed(bars,"4h",as_of=as_of)
    if len(h4)<20:
        return {"state":"INSUFFICIENT_H4","closed_m15":len(bars),"execution_influence":False}
    zones=_origin_zones(bars,as_of=as_of)
    if not zones:
        return {
            "state":"NO_ORIGIN_ZONE",
            "closed_m15":len(bars),
            "zone_diagnostics":{
                "origin_zones_total":0,
                "selection_result":"NO_ORIGIN_ZONE",
                "not_bug_if_zero_eligible":True,
            },
            "execution_influence":False,
        }

    i=len(h4)-1
    hr=h4.iloc[i]
    map_at=ensure_utc(hr["time"].to_pydatetime())
    o=float(hr["open"]);c=float(hr["close"])
    if c==o:
        return {"state":"NO_DIRECTION","map_at":map_at.isoformat(),"execution_influence":False}
    continuation="LONG" if c>o else "SHORT"
    first_leg="SHORT" if continuation=="LONG" else "LONG"
    map_price=c
    zone_diagnostics=_zone_diagnostics(
        zones,
        map_at=map_at,
        price=map_price,
        continuation=continuation,
        bars=bars,
    )
    zone=_choose_zone(
        zones,map_at=map_at,price=map_price,continuation=continuation,bars=bars
    )
    if zone is None:
        return {
            "state":"NO_MAP_ZONE",
            "map_at":map_at.isoformat(),
            "map_price":map_price,
            "continuation_direction":continuation,
            "first_leg_direction":first_leg,
            "zone_diagnostics":zone_diagnostics,
            "execution_influence":False,
        }

    features=_h4_features(h4,i,continuation=continuation,zone=zone,map_price=map_price)
    lifecycle=_zone_touch_lifecycle(zone,bars=bars,map_at=map_at)
    after=[(j,b) for j,b in enumerate(bars) if ensure_utc(b.timestamp)>=map_at]
    touch_idx=None;invalid_idx=None
    for j,b in after:
        if _invalidated(b,zone):
            invalid_idx=j;break
        if _touch(b,zone):
            touch_idx=j;break

    elapsed_bars=len(after)
    payload={
        "state":"APPROACHING_ZONE",
        "map_at":map_at.isoformat(),
        "map_price":map_price,
        "continuation_direction":continuation,
        "first_leg_direction":first_leg,
        "zone":asdict(zone)|{
            "zone_id":lifecycle["zone_id"],
            "available_at":zone.available_at.isoformat(),
            "bos_at":zone.bos_at.isoformat(),
            "origin_at":zone.origin_at.isoformat(),
        },
        "first_touch_at":lifecycle["first_touch_at"],
        "map_first_touch_at":lifecycle["map_first_touch_at"],
        "touch_lifecycle":lifecycle["touch_lifecycle"],
        "zone_lifecycle":lifecycle["zone_lifecycle"],
        "origin_invalidated_at":lifecycle["origin_invalidated_at"],
        "h4_features":features,
        "zone_diagnostics":zone_diagnostics,
        "closed_m15":len(bars),
        "execution_influence":False,
        "promotion_authority":False,
    }

    if invalid_idx is not None:
        payload["state"]="INVALIDATED_REMAP_DUE"
        payload["invalidated_at"]=ensure_utc(bars[invalid_idx].timestamp).isoformat()
        payload["zone_lifecycle"]="INVALIDATED_DURING_CURRENT_MAP"
        return payload

    if touch_idx is None:
        if elapsed_bars>FIRST_LEG_HORIZON_M15:
            payload["state"]="FIRST_LEG_TIMEOUT_REMAP_DUE"
        return payload

    payload["map_first_touch_at"]=ensure_utc(bars[touch_idx].timestamp).isoformat()
    if payload.get("first_touch_at") is None:
        payload["first_touch_at"]=payload["map_first_touch_at"]
    payload["touch_lifecycle"]="TOUCHED_DURING_CURRENT_MAP"
    payload["zone_lifecycle"]="TOUCHED_DURING_CURRENT_MAP"
    confirm_idx=None
    c_end=min(len(bars)-1,touch_idx+CONFIRM_WINDOW_M15)
    for j in range(touch_idx,c_end+1):
        if _invalidated(bars[j],zone):
            payload["state"]="INVALIDATED_AFTER_TOUCH_REMAP_DUE"
            payload["invalidated_at"]=ensure_utc(bars[j].timestamp).isoformat()
            payload["zone_lifecycle"]="INVALIDATED_DURING_CURRENT_MAP"
            return payload
        if _engulf_reject(bars,j,zone):
            confirm_idx=j;break

    if confirm_idx is None:
        bars_since_touch=(len(bars)-1)-touch_idx
        payload["state"]="ZONE_TOUCHED_WAIT_CONFIRM" if bars_since_touch<CONFIRM_WINDOW_M15 else "CONFIRM_TIMEOUT_REMAP_DUE"
        return payload

    payload["confirm_at"]=ensure_utc(bars[confirm_idx].timestamp).isoformat()
    entry_idx=confirm_idx+1
    if entry_idx>=len(bars):
        payload["state"]="CONFIRMED_PENDING_ENTRY_BAR"
        return payload

    entry=float(bars[entry_idx].open)
    stop=_stop(zone)
    target=_target(entry,stop,continuation)
    payload["entry_at"]=ensure_utc(bars[entry_idx].timestamp).isoformat()
    payload["entry"]=entry
    payload["stop"]=stop
    if target is None:
        payload["state"]="CONFIRMED_NO_TARGET_GEOMETRY"
        return payload
    round_level,terminal,ladder=target
    payload["state"]="CONFIRMED_SHADOW"
    payload["round_liquidity"]=round_level
    payload["tp_ladder"]=list(ladder)
    payload["terminal"]=terminal
    return payload


def _evaluation_key(payload:dict[str,Any])->str:
    fields=(
        STRATEGY_ID,
        str(payload.get("map_at") or "NONE"),
        str(payload.get("state") or "NONE"),
        str(payload.get("continuation_direction") or "NONE"),
        str(payload.get("first_touch_at") or "NONE"),
        str(payload.get("confirm_at") or "NONE"),
        str(dict(payload.get("zone") or {}).get("origin_at") or "NONE"),
    )
    return "|".join(fields)


def _already_recorded(store,key:str)->bool:
    try:
        response=(
            store.client.table("broker_order_events")
            .select("payload,event_type,code")
            .eq("event_type",EVENT_TYPE)
            .eq("code",STRATEGY_ID)
            .order("observed_at",desc=True)
            .limit(120)
            .execute()
        )
    except Exception:
        return True
    return any(str(dict(r.get("payload") or {}).get("evaluation_key") or "")==key for r in response.data or [])


def _persist(store,*,payload,key)->bool:
    if _already_recorded(store,key):
        return False
    account=_account_label()
    if not account:
        raise RuntimeError("CTRADER_ACCOUNT_ID_REQUIRED_FOR_AFIC_SHADOW")
    digest=hashlib.sha256(key.encode()).hexdigest()[:28]
    store.record_order_event(
        backend="CTRADER",account_id=account,
        signal_key=f"AFIC_SHADOW:{digest}",
        broker_order_id=None,event_type=EVENT_TYPE,
        accepted=None,code=STRATEGY_ID,
        message="AFIC path-state forward shadow evaluation; no broker action",
        payload={
            "evaluation_key":key,
            "environment":"DEMO",
            "execution_influence":False,
            "promotion_authority":False,
            "forward_contract":FORWARD_CONTRACT,
            "code_version":os.getenv("GITHUB_SHA","LOCAL"),
            "evaluation":payload,
        },
    )
    return True


def run()->int:
    cfg=load_project_config(None)
    policy=load_execution_policy(None)
    if str(policy.ctrader.get("environment","")).upper()!="DEMO":
        raise SystemExit("AFIC_PATH_SHADOW_DEMO_ONLY")
    if not bool(policy.ctrader.get("require_demo",False)):
        raise SystemExit("AFIC_PATH_SHADOW_REQUIRE_DEMO")
    if SYMBOL not in cfg.pair_map:
        raise SystemExit("AFIC_PATH_SHADOW_XAUUSD_NOT_CONFIGURED")

    feed=build_ctrader_research_feed(policy,(SYMBOL,))
    store=SupabaseOperationalStore.from_env()
    now=datetime.now(tz=UTC)
    payload:dict[str,Any]={}
    persisted=False
    error=None
    raw_count=0
    try:
        feed.ensure_connected()
        raw=tuple(feed.historical_bars(
            SYMBOL,"M15",
            from_time=now-timedelta(days=LOOKBACK_DAYS),
            to_time=now,count=REQUEST_COUNT,
        ))
        raw_count=len(raw)
        payload=evaluate_afic_shadow(raw,as_of=now)
        key=_evaluation_key(payload)
        persisted=_persist(store,payload=payload,key=key)
    except Exception as exc:
        error=f"{type(exc).__name__}:{exc}"
    finally:
        try: feed.close()
        except Exception: pass

    healthy=error is None
    store.write_heartbeat(
        WORKER_NAME,healthy=healthy,lag_seconds=0.0,
        details={
            "strategy_id":STRATEGY_ID,
            "forward_contract":FORWARD_CONTRACT,
            "environment":"DEMO",
            "execution_influence":False,
            "promotion_authority":False,
            "live_execution_enabled":False,
            "raw_m15_bars":raw_count,
            "persisted":persisted,
            "evaluation":payload,
            "error":error,
        },
    )
    print(
        "CTRADER_DEMO_XAU_AFIC_PATH_SHADOW "
        f"healthy={int(healthy)} state={payload.get('state','ERROR')} "
        f"persisted={int(persisted)} execution_influence=0"
    )
    return 0 if healthy else 2


if __name__=="__main__":
    raise SystemExit(run())

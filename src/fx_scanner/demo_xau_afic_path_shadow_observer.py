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


def _origin_zones(rows:Sequence[Bar])->tuple[OriginZone,...]:
    h1=_resample(rows,"1h")
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


def _choose_zone(zones:Sequence[OriginZone],*,map_at,price:float,continuation:str)->OriginZone|None:
    t=ensure_utc(map_at)
    available=[
        z for z in zones
        if ensure_utc(z.available_at)<=t
        and t-ensure_utc(z.available_at)<=timedelta(hours=ZONE_MAX_AGE_HOURS)
    ]
    if continuation=="SHORT":
        c=[z for z in available if z.direction=="SHORT" and z.low>price]
        return None if not c else min(c,key=lambda z:z.low-price)
    c=[z for z in available if z.direction=="LONG" and z.high<price]
    return None if not c else min(c,key=lambda z:price-z.high)


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

    h4=_resample(bars,"4h")
    if len(h4)<20:
        return {"state":"INSUFFICIENT_H4","closed_m15":len(bars),"execution_influence":False}
    zones=_origin_zones(bars)
    if not zones:
        return {"state":"NO_ORIGIN_ZONE","closed_m15":len(bars),"execution_influence":False}

    i=len(h4)-1
    hr=h4.iloc[i]
    map_at=ensure_utc(hr["time"].to_pydatetime())
    o=float(hr["open"]);c=float(hr["close"])
    if c==o:
        return {"state":"NO_DIRECTION","map_at":map_at.isoformat(),"execution_influence":False}
    continuation="LONG" if c>o else "SHORT"
    first_leg="SHORT" if continuation=="LONG" else "LONG"
    map_price=c
    zone=_choose_zone(zones,map_at=map_at,price=map_price,continuation=continuation)
    if zone is None:
        return {
            "state":"NO_MAP_ZONE","map_at":map_at.isoformat(),
            "continuation_direction":continuation,"first_leg_direction":first_leg,
            "execution_influence":False,
        }

    features=_h4_features(h4,i,continuation=continuation,zone=zone,map_price=map_price)
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
            "available_at":zone.available_at.isoformat(),
            "bos_at":zone.bos_at.isoformat(),
            "origin_at":zone.origin_at.isoformat(),
        },
        "h4_features":features,
        "closed_m15":len(bars),
        "execution_influence":False,
        "promotion_authority":False,
    }

    if invalid_idx is not None:
        payload["state"]="INVALIDATED_REMAP_DUE"
        payload["invalidated_at"]=ensure_utc(bars[invalid_idx].timestamp).isoformat()
        return payload

    if touch_idx is None:
        if elapsed_bars>FIRST_LEG_HORIZON_M15:
            payload["state"]="FIRST_LEG_TIMEOUT_REMAP_DUE"
        return payload

    payload["first_touch_at"]=ensure_utc(bars[touch_idx].timestamp).isoformat()
    confirm_idx=None
    c_end=min(len(bars)-1,touch_idx+CONFIRM_WINDOW_M15)
    for j in range(touch_idx,c_end+1):
        if _invalidated(bars[j],zone):
            payload["state"]="INVALIDATED_AFTER_TOUCH_REMAP_DUE"
            payload["invalidated_at"]=ensure_utc(bars[j].timestamp).isoformat()
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

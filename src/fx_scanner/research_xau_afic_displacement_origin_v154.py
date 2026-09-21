from __future__ import annotations

from bisect import bisect_right
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from math import ceil, floor, isfinite
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from .models import Bar, ensure_utc
from .research_xau_hierarchical_regime_router_v35 import (
    _resample_completed,
    _wilder_atr,
    build_d1_context,
)
from .research_xau_afic_liquidity_forecast_v152 import (
    Forecast,
    FORECAST_HORIZONS,
    _Asof,
    _PivotAsof,
    _confirmed_pivots,
    _latest_range,
    _m15_sweep,
    build_ladder,
    _evaluate_forecast,
)
from .research_xau_afic_external_liquidity_v153 import _external_liquidity

RESEARCH_VERSION="XAU_AFIC_DISPLACEMENT_ORIGIN_LIQUIDITY_V154"
ARTIFACT_CONTRACT="XAU_AFIC_DISPLACEMENT_ORIGIN_LIQUIDITY_V154_EVIDENCE_1"
POLICY_EFFECT="SHADOW_ONLY"
EXECUTION_INFLUENCE=False
PROMOTION_ELIGIBLE=False

ORIGIN_SEARCH_H1_BARS=6
ORIGIN_MAX_AGE_HOURS=24
DISPLACEMENT_BODY_FRACTION=0.50
DISPLACEMENT_RANGE_ATR=1.00
STOP_BUFFER_ATR=0.10
MIN_PUBLISHED_RR=1.50
ROUND_STEP_USD=10.0
ROUND_FRONT_RUN_USD=1.0
TP_LADDER_STEP_USD=3.0
MAX_LADDER_STEPS=7

VARIANTS=(
    "ORIGIN_REJECTION_ROUND",
    "ORIGIN_REJECTION_H4_LOCATION_ROUND",
    "ORIGIN_REJECTION_H4_SWEEP_ROUND",
    "ORIGIN_REJECTION_H4_SWEEP_EXTERNAL_ROUND",
)

ERA_WINDOWS=(
    ("2012_2018",datetime(2012,1,1,tzinfo=timezone.utc),datetime(2019,1,1,tzinfo=timezone.utc)),
    ("2019_2024",datetime(2019,1,1,tzinfo=timezone.utc),datetime(2025,1,1,tzinfo=timezone.utc)),
    ("2025_2026YTD",datetime(2025,1,1,tzinfo=timezone.utc),datetime(2026,9,20,tzinfo=timezone.utc)),
)


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

    def payload(self)->dict[str,Any]:
        x=asdict(self)
        for key in ("available_at","bos_at","origin_at"):
            x[key]=ensure_utc(x[key]).isoformat()
        return x


class _ZoneAsof:
    def __init__(self,zones:Sequence[OriginZone]):
        self.zones=tuple(sorted(zones,key=lambda z:ensure_utc(z.available_at)))
        self.times=[ensure_utc(z.available_at) for z in self.zones]

    def latest(self,timestamp)->OriginZone|None:
        i=bisect_right(self.times,ensure_utc(timestamp))-1
        return None if i<0 else self.zones[i]


def _h1_origin_zones(rows:Sequence[Bar])->tuple[OriginZone,...]:
    h1=_resample_completed(rows,"1h")
    h1["atr14"]=_wilder_atr(h1,14)
    pivots=_PivotAsof(_confirmed_pivots(h1))
    out=[]

    for i in range(max(20,ORIGIN_SEARCH_H1_BARS+1),len(h1)):
        row=h1.iloc[i]
        t=ensure_utc(row["time"].to_pydatetime() if hasattr(row["time"],"to_pydatetime") else row["time"])
        atr=float(row.get("atr14",np.nan))
        if not isfinite(atr) or atr<=0:
            continue

        prev_close=float(h1.iloc[i-1]["close"])
        o=float(row["open"]);h=float(row["high"]);l=float(row["low"]);c=float(row["close"])
        candle_range=max(h-l,1e-12)
        body=abs(c-o)
        body_fraction=body/candle_range
        range_atr=candle_range/atr
        if range_atr<DISPLACEMENT_RANGE_ATR or body_fraction<DISPLACEMENT_BODY_FRACTION:
            continue

        available=pivots.available(t)
        highs=[p for p in available if p.kind=="HIGH" and ensure_utc(p.pivot_at)<t]
        lows=[p for p in available if p.kind=="LOW" and ensure_utc(p.pivot_at)<t]

        direction=None
        bos_level=None
        if c>o and highs:
            level=highs[-1].price
            if prev_close<=level and c>level:
                direction="LONG";bos_level=float(level)
        if direction is None and c<o and lows:
            level=lows[-1].price
            if prev_close>=level and c<level:
                direction="SHORT";bos_level=float(level)
        if direction is None:
            continue

        origin=None
        start=max(0,i-ORIGIN_SEARCH_H1_BARS)
        for j in range(i-1,start-1,-1):
            candidate=h1.iloc[j]
            co=float(candidate["open"]);cc=float(candidate["close"])
            opposite=(direction=="LONG" and cc<co) or (direction=="SHORT" and cc>co)
            if opposite:
                origin=candidate
                break
        if origin is None:
            continue

        origin_at=ensure_utc(origin["time"].to_pydatetime() if hasattr(origin["time"],"to_pydatetime") else origin["time"])
        out.append(
            OriginZone(
                direction=direction,
                available_at=t,
                bos_at=t,
                bos_level=float(bos_level),
                low=float(origin["low"]),
                high=float(origin["high"]),
                h1_atr=atr,
                origin_at=origin_at,
                displacement_range_atr=float(range_atr),
                displacement_body_fraction=float(body_fraction),
            )
        )
    return tuple(out)


def _zone_rejection(row:Bar,zone:OriginZone)->bool:
    touch=float(row.low)<=zone.high and float(row.high)>=zone.low
    if not touch:
        return False
    if zone.direction=="LONG":
        # Demand-origin retest must reject upward and close back above the
        # proximal (upper) edge rather than merely trade through the zone.
        return float(row.close)>float(row.open) and float(row.close)>=zone.high
    return float(row.close)<float(row.open) and float(row.close)<=zone.low


def _h4_location_ok(price:float,direction:str,h4_pivots)->bool:
    dr=_latest_range(h4_pivots)
    if dr is None:
        return False
    lo,hi=dr
    mid=0.5*(lo+hi)
    return price<=mid if direction=="LONG" else price>=mid


def _zone_stop(zone:OriginZone)->float:
    if zone.direction=="LONG":
        return zone.low-STOP_BUFFER_ATR*zone.h1_atr
    return zone.high+STOP_BUFFER_ATR*zone.h1_atr


def _published_round_target(entry:float,stop:float,direction:str)->tuple[float,float,tuple[float,...]]|None:
    sign=1.0 if direction=="LONG" else -1.0
    risk=(entry-stop)*sign
    if not isfinite(risk) or risk<=0:
        return None

    threshold=entry+sign*MIN_PUBLISHED_RR*risk
    if direction=="LONG":
        round_level=ceil(threshold/ROUND_STEP_USD)*ROUND_STEP_USD
        front=round_level-ROUND_FRONT_RUN_USD
        while (front-entry)/risk<MIN_PUBLISHED_RR:
            round_level+=ROUND_STEP_USD
            front=round_level-ROUND_FRONT_RUN_USD
    else:
        round_level=floor(threshold/ROUND_STEP_USD)*ROUND_STEP_USD
        front=round_level+ROUND_FRONT_RUN_USD
        while (entry-front)/risk<MIN_PUBLISHED_RR:
            round_level-=ROUND_STEP_USD
            front=round_level+ROUND_FRONT_RUN_USD

    ladder=build_ladder(entry,front,direction)
    if not ladder:
        return None

    # AFIC examples publish at most seven $3 targets. The displayed terminal
    # is therefore the last $3 step before the front-run level, not necessarily
    # the exact psychological-liquidity front.
    displayed=ladder[-1]
    rr=(displayed-entry)*sign/risk
    if rr<MIN_PUBLISHED_RR:
        return None
    return float(round_level),float(displayed),tuple(ladder)


def reconstruct_example(entry:float,stop:float,direction:str):
    return _published_round_target(entry,stop,direction)


def _external_beyond_published(
    *,entry:float,published:float,direction:str,h4_pivots,daily,weekly,
)->tuple[bool,str|None,float|None]:
    ext=_external_liquidity(
        price=entry,direction=direction,h4_pivots=h4_pivots,daily=daily,weekly=weekly
    )
    if ext is None:
        return False,None,None
    px,src=ext
    if direction=="LONG":
        return bool(px>=published),src,float(px)
    return bool(px<=published),src,float(px)


def build_forecasts(rows:Sequence[Bar],*,variant:str,evaluation_end)->tuple[Forecast,...]:
    if variant not in VARIANTS:
        raise ValueError("V154_UNKNOWN_VARIANT")

    bars=tuple(sorted(rows,key=lambda x:ensure_utc(x.timestamp)))
    end=ensure_utc(evaluation_end)
    zones=_ZoneAsof(_h1_origin_zones(bars))

    h4=_resample_completed(bars,"4h")
    h4p=_PivotAsof(_confirmed_pivots(h4))
    daily=_resample_completed(bars,"1D")
    weekly=_resample_completed(bars,"W-SUN")
    daily_lookup=_Asof(daily);weekly_lookup=_Asof(weekly)

    forecasts=[]
    active=None
    active_entry_i=None

    for i,row in enumerate(bars[:-1]):
        signal_at=ensure_utc(row.timestamp)
        if signal_at>=end:
            break

        if active is not None and active_entry_i is not None:
            if i>=active_entry_i:
                if active.direction=="LONG":
                    stop_hit=float(row.low)<=active.stop
                    target_hit=float(row.high)>=active.terminal_target
                else:
                    stop_hit=float(row.high)>=active.stop
                    target_hit=float(row.low)<=active.terminal_target
                expired=(i-active_entry_i)>=max(FORECAST_HORIZONS)
                if stop_hit or target_hit or expired:
                    active=None;active_entry_i=None
                    continue
                continue

        zone=zones.latest(signal_at)
        if zone is None:
            continue
        age=signal_at-ensure_utc(zone.available_at)
        if age<timedelta(0) or age>timedelta(hours=ORIGIN_MAX_AGE_HOURS):
            continue
        if not _zone_rejection(row,zone):
            continue

        hp4=h4p.available(signal_at)
        if variant in {
            "ORIGIN_REJECTION_H4_LOCATION_ROUND",
            "ORIGIN_REJECTION_H4_SWEEP_ROUND",
            "ORIGIN_REJECTION_H4_SWEEP_EXTERNAL_ROUND",
        }:
            if not _h4_location_ok(float(row.close),zone.direction,hp4):
                continue

        sweep=_m15_sweep(bars,i,zone.direction)
        if variant in {
            "ORIGIN_REJECTION_H4_SWEEP_ROUND",
            "ORIGIN_REJECTION_H4_SWEEP_EXTERNAL_ROUND",
        } and not sweep:
            continue

        entry_at=ensure_utc(bars[i+1].timestamp)
        entry=float(bars[i+1].open)
        stop=_zone_stop(zone)
        target=_published_round_target(entry,stop,zone.direction)
        if target is None:
            continue
        round_level,published,ladder=target

        dl=daily_lookup.row(signal_at);wl=weekly_lookup.row(signal_at)
        ext_ok,ext_src,ext_px=_external_beyond_published(
            entry=entry,published=published,direction=zone.direction,
            h4_pivots=hp4,daily=dl,weekly=wl,
        )
        if variant=="ORIGIN_REJECTION_H4_SWEEP_EXTERNAL_ROUND" and not ext_ok:
            continue

        source=f"ROUND_{round_level:g}_FRONT1"
        if ext_src is not None:
            source+=f"|EXT_{ext_src}_{ext_px:g}|EXT_OK_{int(ext_ok)}"

        f=Forecast(
            variant=variant,
            direction=zone.direction,
            signal_at=signal_at,
            entry_at=entry_at,
            entry=entry,
            stop=stop,
            terminal_target=published,
            terminal_source=source,
            ladder=ladder,
            d1_side=0,
            h4_side=0,
            h1_side=1 if zone.direction=="LONG" else -1,
            dealing_location="ORIGIN_ZONE",
            m15_sweep=sweep,
        )
        forecasts.append(f)
        active=f
        active_entry_i=i+1

    return tuple(forecasts)


def _summarize(rows:Sequence[Bar],forecasts:Sequence[Forecast],start,end)->dict[str,Any]:
    bars=tuple(sorted(rows,key=lambda x:ensure_utc(x.timestamp)))
    by_time={ensure_utc(b.timestamp):i for i,b in enumerate(bars)}
    fs=tuple(f for f in forecasts if ensure_utc(start)<=ensure_utc(f.entry_at)<ensure_utc(end))
    horizons={}

    for h in FORECAST_HORIZONS:
        pairs=[]
        for f in fs:
            idx=by_time.get(ensure_utc(f.entry_at))
            if idx is not None:
                pairs.append((f,_evaluate_forecast(f,bars,idx,h)))
        n=len(pairs)
        max_steps=max((len(ev["tp_hits"]) for _,ev in pairs),default=0)
        steps=[]
        for k in range(max_steps):
            eligible=[ev for _,ev in pairs if len(ev["tp_hits"])>k]
            steps.append({
                "step":k+1,
                "eligible":len(eligible),
                "hit_rate":None if not eligible else sum(bool(ev["tp_hits"][k]) for ev in eligible)/len(eligible),
            })
        direction={}
        for side in ("LONG","SHORT"):
            eligible=[ev for f,ev in pairs if f.direction==side]
            direction[side]={
                "n":len(eligible),
                "tp1_hit_rate":None if not eligible else sum(ev["tp1_hit"] for ev in eligible)/len(eligible),
                "terminal_hit_rate":None if not eligible else sum(ev["terminal_hit"] for ev in eligible)/len(eligible),
                "stop_rate":None if not eligible else sum(ev["stop_hit"] for ev in eligible)/len(eligible),
            }
        horizons[str(h)]={
            "n":n,
            "tp1_hit_rate":None if n==0 else sum(ev["tp1_hit"] for _,ev in pairs)/n,
            "terminal_hit_rate":None if n==0 else sum(ev["terminal_hit"] for _,ev in pairs)/n,
            "stop_rate":None if n==0 else sum(ev["stop_hit"] for _,ev in pairs)/n,
            "median_terminal_rr":None if n==0 else float(np.median([ev["terminal_rr"] for _,ev in pairs])),
            "step_hit_rates":steps,
            "direction":direction,
        }

    return {
        "forecasts":len(fs),
        "direction_counts":{
            "LONG":sum(f.direction=="LONG" for f in fs),
            "SHORT":sum(f.direction=="SHORT" for f in fs),
        },
        "horizons":horizons,
        "examples":[f.payload() for f in fs[:10]],
    }


def evaluate_v154(rows:Sequence[Bar],*,evaluation_end)->dict[str,Any]:
    bars=tuple(sorted(rows,key=lambda x:ensure_utc(x.timestamp)))
    end=ensure_utc(evaluation_end)
    streams={v:build_forecasts(bars,variant=v,evaluation_end=end) for v in VARIANTS}
    full_start=datetime(2012,1,1,tzinfo=timezone.utc)
    full={v:_summarize(bars,streams[v],full_start,end) for v in VARIANTS}
    eras={}
    for label,a,b in ERA_WINDOWS:
        bb=min(ensure_utc(b),end)
        if ensure_utc(a)<bb:
            eras[label]={v:_summarize(bars,streams[v],a,bb) for v in VARIANTS}

    return {
        "research_version":RESEARCH_VERSION,
        "artifact_contract":ARTIFACT_CONTRACT,
        "policy_effect":POLICY_EFFECT,
        "execution_influence":EXECUTION_INFLUENCE,
        "promotion_eligible":PROMOTION_ELIGIBLE,
        "live_execution_enabled":False,
        "reconstruction_basis":{
            "buy_4278_sl4265":"1.5R threshold 4297.5 -> psychological 4300 -> front-run 4299 -> 7x $3 ladder",
            "sell_4349_sl4359":"1.5R threshold 4334 -> psychological 4330 -> front-run 4331 -> 6x $3 ladder",
            "claim_limit":"exactly reproduces the two supplied target ladders, but remains a hypothesis until broader forecasts are matched",
        },
        "contract":{
            "direction_event":"causal H1 BOS with displacement candle",
            "displacement":"H1 range >= 1.0 ATR14 and body >= 50% of candle range",
            "origin_zone":"last opposite H1 candle within prior 6 completed H1 bars",
            "entry":"M15 retest of origin zone with directional rejection; stricter variants add H4 premium/discount and local liquidity sweep",
            "origin_max_age_hours":ORIGIN_MAX_AGE_HOURS,
            "stop":"beyond distal origin-zone edge + 0.10 H1 ATR",
            "published_target":"first $10 psychological liquidity at/after 1.5R, front-run by $1; publish $3 ladder up to seven steps",
            "external_confirmation":"strictest variant requires HTF external liquidity at/beyond the published target",
            "forecast_horizons_m15_bars":list(FORECAST_HORIZONS),
            "same_bar_ambiguity":"STOP_FIRST",
            "no_parameter_grid":True,
            "no_execution_authority":True,
        },
        "full":full,
        "eras":eras,
        "note":"V154 tests the strongest fingerprint from the supplied AFIC calls: displacement-origin entry geometry plus psychological-liquidity front-running and fixed $3 TP ladders.",
    }

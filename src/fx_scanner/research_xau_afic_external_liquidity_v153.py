from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite
from typing import Any, Mapping, Sequence

import numpy as np

from .models import Bar, ensure_utc
from .research_xau_hierarchical_regime_router_v35 import (
    _resample_completed,
    _wilder_atr,
    build_d1_context,
)
from .research_xau_afic_liquidity_forecast_v152 import (
    Forecast,
    PIVOT_MEMORY,
    STOP_BUFFER_ATR,
    MIN_TERMINAL_RR,
    FORECAST_HORIZONS,
    _Asof,
    _PivotAsof,
    _confirmed_pivots,
    _structure_side,
    _latest_range,
    _completed_extremes,
    _m15_sweep,
    build_ladder,
    _evaluate_forecast,
)

RESEARCH_VERSION="XAU_AFIC_EXTERNAL_LIQUIDITY_RECONSTRUCTION_V153"
ARTIFACT_CONTRACT="XAU_AFIC_EXTERNAL_LIQUIDITY_RECONSTRUCTION_V153_EVIDENCE_1"
POLICY_EFFECT="SHADOW_ONLY"
EXECUTION_INFLUENCE=False
PROMOTION_ELIGIBLE=False

VARIANTS=(
    "H1_EXTERNAL_ROUTE",
    "H4_H1_ALIGNED_EXTERNAL",
    "H1_EXTERNAL_D1_MATCH",
    "H1_EXTERNAL_PLUS_M15_SWEEP",
)

ERA_WINDOWS=(
    ("2012_2018",datetime(2012,1,1,tzinfo=timezone.utc),datetime(2019,1,1,tzinfo=timezone.utc)),
    ("2019_2024",datetime(2019,1,1,tzinfo=timezone.utc),datetime(2025,1,1,tzinfo=timezone.utc)),
    ("2025_2026YTD",datetime(2025,1,1,tzinfo=timezone.utc),datetime(2026,9,20,tzinfo=timezone.utc)),
)


def _external_liquidity(
    *,price:float,direction:str,h4_pivots,
    daily:Mapping[str,Any]|None,weekly:Mapping[str,Any]|None,
)->tuple[float,str]|None:
    c=[]
    if direction=="LONG":
        if daily is not None and float(daily["high"])>price:c.append((float(daily["high"]),"PDH"))
        if weekly is not None and float(weekly["high"])>price:c.append((float(weekly["high"]),"PWH"))
        c += [(x.price,"H4_SWING_HIGH") for x in h4_pivots if x.kind=="HIGH" and x.price>price]
        return None if not c else min(c,key=lambda z:z[0]-price)
    if daily is not None and float(daily["low"])<price:c.append((float(daily["low"]),"PDL"))
    if weekly is not None and float(weekly["low"])<price:c.append((float(weekly["low"]),"PWL"))
    c += [(x.price,"H4_SWING_LOW") for x in h4_pivots if x.kind=="LOW" and x.price<price]
    return None if not c else min(c,key=lambda z:price-z[0])


def _external_stop(
    *,price:float,direction:str,h4_pivots,
    daily:Mapping[str,Any]|None,weekly:Mapping[str,Any]|None,h1_atr:float,
)->tuple[float,str]|None:
    if not isfinite(h1_atr) or h1_atr<=0:return None
    c=[]
    if direction=="LONG":
        if daily is not None and float(daily["low"])<price:c.append((float(daily["low"]),"PDL"))
        if weekly is not None and float(weekly["low"])<price:c.append((float(weekly["low"]),"PWL"))
        c += [(x.price,"H4_SWING_LOW") for x in h4_pivots if x.kind=="LOW" and x.price<price]
        if not c:return None
        level,src=max(c,key=lambda z:z[0])
        return level-STOP_BUFFER_ATR*h1_atr,src
    if daily is not None and float(daily["high"])>price:c.append((float(daily["high"]),"PDH"))
    if weekly is not None and float(weekly["high"])>price:c.append((float(weekly["high"]),"PWH"))
    c += [(x.price,"H4_SWING_HIGH") for x in h4_pivots if x.kind=="HIGH" and x.price>price]
    if not c:return None
    level,src=min(c,key=lambda z:z[0])
    return level+STOP_BUFFER_ATR*h1_atr,src


def build_forecasts(rows:Sequence[Bar],*,variant:str,evaluation_end)->tuple[Forecast,...]:
    if variant not in VARIANTS:raise ValueError("V153_UNKNOWN_VARIANT")
    bars=tuple(sorted(rows,key=lambda x:ensure_utc(x.timestamp)))
    end=ensure_utc(evaluation_end)

    d1=build_d1_context(bars); d1_lookup=_Asof(d1)
    h4=_resample_completed(bars,"4h")
    h1=_resample_completed(bars,"1h")
    h1["atr14"]=_wilder_atr(h1,14); h1_lookup=_Asof(h1)
    h4p=_PivotAsof(_confirmed_pivots(h4))
    h1p=_PivotAsof(_confirmed_pivots(h1))
    daily=_completed_extremes(bars,"1D"); weekly=_completed_extremes(bars,"W-SUN")
    daily_lookup=_Asof(daily); weekly_lookup=_Asof(weekly)

    forecasts=[]
    active=None;active_entry_i=None
    for i,row in enumerate(bars[:-1]):
        signal_at=ensure_utc(row.timestamp)
        if signal_at>=end:break

        if active is not None and active_entry_i is not None:
            if i>=active_entry_i:
                if active.direction=="LONG":
                    stop_hit=float(row.low)<=active.stop
                    terminal_hit=float(row.high)>=active.terminal_target
                else:
                    stop_hit=float(row.high)>=active.stop
                    terminal_hit=float(row.low)<=active.terminal_target
                expired=(i-active_entry_i)>=max(FORECAST_HORIZONS)
                if stop_hit or terminal_hit or expired:
                    active=None;active_entry_i=None
                    continue
                continue

        d=d1_lookup.row(signal_at);h1row=h1_lookup.row(signal_at)
        if d is None or h1row is None:continue
        dside=int(d.get("regime_side") or 0)

        hp4=h4p.available(signal_at);hp1=h1p.available(signal_at)
        s4=_structure_side(hp4);s1=_structure_side(hp1)
        if s1==0:continue
        direction="LONG" if s1>0 else "SHORT"

        dr=_latest_range(hp4)
        if dr is None:continue
        lo,hi=dr;mid=0.5*(lo+hi)
        price=float(row.close)
        dealing="DISCOUNT" if price<=mid else "PREMIUM"
        if direction=="LONG" and dealing!="DISCOUNT":continue
        if direction=="SHORT" and dealing!="PREMIUM":continue

        if variant=="H4_H1_ALIGNED_EXTERNAL" and s4!=s1:continue
        if variant=="H1_EXTERNAL_D1_MATCH" and dside!=s1:continue
        sweep=_m15_sweep(bars,i,direction)
        if variant=="H1_EXTERNAL_PLUS_M15_SWEEP" and not sweep:continue

        dl=daily_lookup.row(signal_at);wl=weekly_lookup.row(signal_at)
        target=_external_liquidity(
            price=price,direction=direction,h4_pivots=hp4,daily=dl,weekly=wl
        )
        if target is None:continue
        terminal,target_src=target
        h1atr=float(h1row.get("atr14",np.nan))
        stop_row=_external_stop(
            price=price,direction=direction,h4_pivots=hp4,daily=dl,weekly=wl,h1_atr=h1atr
        )
        if stop_row is None:continue
        stop,stop_src=stop_row

        sign=1.0 if direction=="LONG" else -1.0
        reward=(terminal-price)*sign;risk=(price-stop)*sign
        if reward<=0 or risk<=0 or reward/risk<MIN_TERMINAL_RR:continue

        entry_at=ensure_utc(bars[i+1].timestamp);entry=float(bars[i+1].open)
        reward2=(terminal-entry)*sign;risk2=(entry-stop)*sign
        if reward2<=0 or risk2<=0 or reward2/risk2<MIN_TERMINAL_RR:continue
        ladder=build_ladder(entry,terminal,direction)
        if not ladder:continue

        # Preserve stop source in the target-source label for forensic attribution.
        source=f"{target_src}|STOP_{stop_src}"
        f=Forecast(
            variant,direction,signal_at,entry_at,entry,stop,terminal,source,ladder,
            dside,s4,s1,dealing,sweep,
        )
        forecasts.append(f);active=f;active_entry_i=i+1
    return tuple(forecasts)


def _summarize(rows:Sequence[Bar],forecasts:Sequence[Forecast],start,end)->dict[str,Any]:
    bars=tuple(sorted(rows,key=lambda x:ensure_utc(x.timestamp)))
    by_time={ensure_utc(b.timestamp):i for i,b in enumerate(bars)}
    fs=tuple(f for f in forecasts if ensure_utc(start)<=ensure_utc(f.entry_at)<ensure_utc(end))
    houts={}
    for h in FORECAST_HORIZONS:
        pairs=[]
        for f in fs:
            idx=by_time.get(ensure_utc(f.entry_at))
            if idx is not None:pairs.append((f,_evaluate_forecast(f,bars,idx,h)))
        n=len(pairs)
        max_steps=max((len(x[1]["tp_hits"]) for x in pairs),default=0)
        steps=[]
        for k in range(max_steps):
            e=[x for x in pairs if len(x[1]["tp_hits"])>k]
            steps.append({"step":k+1,"eligible":len(e),"hit_rate":None if not e else sum(x[1]["tp_hits"][k] for x in e)/len(e)})
        dirs={}
        for direction in ("LONG","SHORT"):
            e=[x for x in pairs if x[0].direction==direction]
            dirs[direction]={
                "n":len(e),
                "tp1_hit_rate":None if not e else sum(x[1]["tp1_hit"] for x in e)/len(e),
                "terminal_hit_rate":None if not e else sum(x[1]["terminal_hit"] for x in e)/len(e),
                "stop_rate":None if not e else sum(x[1]["stop_hit"] for x in e)/len(e),
            }
        rel={"D1_MATCH":0,"D1_COUNTER":0,"D1_NEUTRAL":0}
        for f,_ in pairs:
            side=1 if f.direction=="LONG" else -1
            if f.d1_side==side:rel["D1_MATCH"]+=1
            elif f.d1_side==-side and f.d1_side!=0:rel["D1_COUNTER"]+=1
            else:rel["D1_NEUTRAL"]+=1
        houts[str(h)]={
            "n":n,
            "tp1_hit_rate":None if not n else sum(x[1]["tp1_hit"] for x in pairs)/n,
            "terminal_hit_rate":None if not n else sum(x[1]["terminal_hit"] for x in pairs)/n,
            "stop_rate":None if not n else sum(x[1]["stop_hit"] for x in pairs)/n,
            "median_terminal_rr":None if not n else float(np.median([x[1]["terminal_rr"] for x in pairs])),
            "step_hit_rates":steps,
            "direction":dirs,
            "d1_relation":rel,
        }
    return {
        "forecasts":len(fs),
        "direction_counts":{"LONG":sum(f.direction=="LONG" for f in fs),"SHORT":sum(f.direction=="SHORT" for f in fs)},
        "liquidity_routes":{s:sum(f.terminal_source==s for f in fs) for s in sorted({f.terminal_source for f in fs})},
        "horizons":houts,
        "examples":[f.payload() for f in fs[:10]],
    }


def evaluate_v153(rows:Sequence[Bar],*,evaluation_end)->dict[str,Any]:
    bars=tuple(sorted(rows,key=lambda x:ensure_utc(x.timestamp)));end=ensure_utc(evaluation_end)
    streams={v:build_forecasts(bars,variant=v,evaluation_end=end) for v in VARIANTS}
    full_start=datetime(2012,1,1,tzinfo=timezone.utc)
    full={v:_summarize(bars,streams[v],full_start,end) for v in VARIANTS}
    eras={}
    for label,a,b in ERA_WINDOWS:
        bb=min(ensure_utc(b),end)
        if ensure_utc(a)<bb:eras[label]={v:_summarize(bars,streams[v],a,bb) for v in VARIANTS}
    return {
        "research_version":RESEARCH_VERSION,
        "artifact_contract":ARTIFACT_CONTRACT,
        "policy_effect":POLICY_EFFECT,
        "execution_influence":EXECUTION_INFLUENCE,
        "promotion_eligible":PROMOTION_ELIGIBLE,
        "live_execution_enabled":False,
        "contract":{
            "reconstruction_change_from_v152":"H1 tactical direction; D1 becomes attribution/context; H1 swings internal only; terminal and stop use external day/week/H4 liquidity",
            "direction":"causal H1 HH/HL or LH/LL structure",
            "location":"H4 dealing-range discount for LONG / premium for SHORT",
            "terminal":"nearest causal PDH/PDL/PWH/PWL/H4 swing in trade direction",
            "stop":"nearest opposite causal PDH/PDL/PWH/PWL/H4 swing plus 0.10 H1 ATR",
            "minimum_terminal_rr":MIN_TERMINAL_RR,
            "ladder":"$3 increments toward terminal liquidity, max seven",
            "forecast_horizons_m15_bars":list(FORECAST_HORIZONS),
            "same_bar_ambiguity":"STOP_FIRST",
            "pivot_memory_events":PIVOT_MEMORY,
            "no_parameter_grid":True,
            "no_execution_authority":True,
        },
        "full":full,"eras":eras,
        "note":"V153 directly tests whether AFIC-like forecasts are tactical H1 routes inside HTF liquidity/dealing-range context rather than D1-direction continuation calls.",
    }

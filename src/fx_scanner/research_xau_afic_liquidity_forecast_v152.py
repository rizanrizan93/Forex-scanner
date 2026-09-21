from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from math import isfinite
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from .models import Bar, ensure_utc
from .research_xau_hierarchical_regime_router_v35 import (
    _bars_frame,
    _resample_completed,
    _wilder_atr,
    build_d1_context,
)

RESEARCH_VERSION="XAU_AFIC_LIQUIDITY_FORECAST_RECONSTRUCTION_V152"
ARTIFACT_CONTRACT="XAU_AFIC_LIQUIDITY_FORECAST_RECONSTRUCTION_V152_EVIDENCE_1"
POLICY_EFFECT="SHADOW_ONLY"
EXECUTION_INFLUENCE=False
PROMOTION_ELIGIBLE=False

PIVOT_LEFT=2
PIVOT_RIGHT=2
LADDER_STEP_USD=3.0
MAX_LADDER_STEPS=7
MIN_TERMINAL_RR=1.50
STOP_BUFFER_ATR=0.10
FORECAST_HORIZONS=(16,32,64)  # 4h / 8h / 16h on M15
M15_SWEEP_LOOKBACK=12

VARIANTS=(
    "HTF_LIQUIDITY_ROUTE",
    "HTF_PLUS_H1_STRUCTURE",
    "HTF_PLUS_H1_PLUS_M15_SWEEP",
)

ERA_WINDOWS=(
    ("2012_2018",datetime(2012,1,1,tzinfo=timezone.utc),datetime(2019,1,1,tzinfo=timezone.utc)),
    ("2019_2024",datetime(2019,1,1,tzinfo=timezone.utc),datetime(2025,1,1,tzinfo=timezone.utc)),
    ("2025_2026YTD",datetime(2025,1,1,tzinfo=timezone.utc),datetime(2026,9,20,tzinfo=timezone.utc)),
)


@dataclass(frozen=True)
class Pivot:
    kind:str
    price:float
    pivot_at:datetime
    available_at:datetime


@dataclass(frozen=True)
class Forecast:
    variant:str
    direction:str
    signal_at:datetime
    entry_at:datetime
    entry:float
    stop:float
    terminal_target:float
    terminal_source:str
    ladder:tuple[float,...]
    d1_side:int
    h4_side:int
    h1_side:int
    dealing_location:str
    m15_sweep:bool

    def payload(self)->dict[str,Any]:
        x=asdict(self)
        x["signal_at"]=ensure_utc(self.signal_at).isoformat()
        x["entry_at"]=ensure_utc(self.entry_at).isoformat()
        x["ladder"]=list(self.ladder)
        return x


class _Asof:
    def __init__(self,frame:pd.DataFrame,time_col:str="time"):
        self.frame=frame.reset_index(drop=True)
        self.time_col=time_col
        self.times=[ensure_utc(x.to_pydatetime() if hasattr(x,"to_pydatetime") else x) for x in self.frame[time_col]]
    def row(self,timestamp):
        i=bisect_right(self.times,ensure_utc(timestamp))-1
        return None if i<0 else self.frame.iloc[i].to_dict()


class _PivotAsof:
    def __init__(self,pivots:Sequence[Pivot]):
        self.pivots=tuple(sorted(pivots,key=lambda x:(ensure_utc(x.available_at),ensure_utc(x.pivot_at),x.kind)))
        self.times=[ensure_utc(x.available_at) for x in self.pivots]
    def available(self,timestamp)->tuple[Pivot,...]:
        i=bisect_right(self.times,ensure_utc(timestamp))
        return self.pivots[:i]


def _confirmed_pivots(frame:pd.DataFrame)->tuple[Pivot,...]:
    rows=frame.reset_index(drop=True)
    out=[]
    for i in range(PIVOT_LEFT,len(rows)-PIVOT_RIGHT):
        hi=float(rows.iloc[i]["high"]);lo=float(rows.iloc[i]["low"])
        left=rows.iloc[i-PIVOT_LEFT:i];right=rows.iloc[i+1:i+1+PIVOT_RIGHT]
        pivot_at=ensure_utc(rows.iloc[i]["time"].to_pydatetime() if hasattr(rows.iloc[i]["time"],"to_pydatetime") else rows.iloc[i]["time"])
        avail=ensure_utc(rows.iloc[i+PIVOT_RIGHT]["time"].to_pydatetime() if hasattr(rows.iloc[i+PIVOT_RIGHT]["time"],"to_pydatetime") else rows.iloc[i+PIVOT_RIGHT]["time"])
        if hi>float(left["high"].max()) and hi>=float(right["high"].max()):
            out.append(Pivot("HIGH",hi,pivot_at,avail))
        if lo<float(left["low"].min()) and lo<=float(right["low"].min()):
            out.append(Pivot("LOW",lo,pivot_at,avail))
    return tuple(out)


def _structure_side(pivots:Sequence[Pivot])->int:
    highs=[x for x in pivots if x.kind=="HIGH"]
    lows=[x for x in pivots if x.kind=="LOW"]
    if len(highs)<2 or len(lows)<2:return 0
    h1,h2=highs[-2],highs[-1]
    l1,l2=lows[-2],lows[-1]
    if h2.price>h1.price and l2.price>l1.price:return 1
    if h2.price<h1.price and l2.price<l1.price:return -1
    return 0


def _latest_range(pivots:Sequence[Pivot])->tuple[float,float]|None:
    highs=[x for x in pivots if x.kind=="HIGH"]
    lows=[x for x in pivots if x.kind=="LOW"]
    if not highs or not lows:return None
    hi=highs[-1].price;lo=lows[-1].price
    return (min(lo,hi),max(lo,hi)) if hi!=lo else None


def _completed_extremes(rows:Sequence[Bar],rule:str)->pd.DataFrame:
    x=_bars_frame(rows).set_index("time")
    return x.resample(rule,label="right",closed="left").agg(
        high=("high","max"),low=("low","min"),close=("close","last")
    ).dropna().reset_index()


def _previous_bucket(frame:pd.DataFrame,timestamp)->Mapping[str,Any]|None:
    # resampled timestamps mark completed bucket end. The latest row <= signal
    # is therefore already complete and causal.
    return _Asof(frame).row(timestamp)


def _nearest_liquidity(
    *,price:float,direction:str,
    h1_pivots:Sequence[Pivot],h4_pivots:Sequence[Pivot],
    daily:Mapping[str,Any]|None,weekly:Mapping[str,Any]|None,
)->tuple[float,str]|None:
    c=[]
    if direction=="LONG":
        if daily is not None and float(daily["high"])>price:c.append((float(daily["high"]),"PDH"))
        if weekly is not None and float(weekly["high"])>price:c.append((float(weekly["high"]),"PWH"))
        c += [(x.price,"H1_SWING_HIGH") for x in h1_pivots if x.kind=="HIGH" and x.price>price]
        c += [(x.price,"H4_SWING_HIGH") for x in h4_pivots if x.kind=="HIGH" and x.price>price]
        return None if not c else min(c,key=lambda z:z[0]-price)
    if daily is not None and float(daily["low"])<price:c.append((float(daily["low"]),"PDL"))
    if weekly is not None and float(weekly["low"])<price:c.append((float(weekly["low"]),"PWL"))
    c += [(x.price,"H1_SWING_LOW") for x in h1_pivots if x.kind=="LOW" and x.price<price]
    c += [(x.price,"H4_SWING_LOW") for x in h4_pivots if x.kind=="LOW" and x.price<price]
    return None if not c else min(c,key=lambda z:price-z[0])


def _protected_stop(
    *,price:float,direction:str,h1_pivots:Sequence[Pivot],h4_pivots:Sequence[Pivot],h1_atr:float
)->float|None:
    if not isfinite(h1_atr) or h1_atr<=0:return None
    if direction=="LONG":
        c=[x.price for x in h1_pivots if x.kind=="LOW" and x.price<price]
        if not c:c=[x.price for x in h4_pivots if x.kind=="LOW" and x.price<price]
        return None if not c else max(c)-STOP_BUFFER_ATR*h1_atr
    c=[x.price for x in h1_pivots if x.kind=="HIGH" and x.price>price]
    if not c:c=[x.price for x in h4_pivots if x.kind=="HIGH" and x.price>price]
    return None if not c else min(c)+STOP_BUFFER_ATR*h1_atr


def build_ladder(entry:float,terminal:float,direction:str)->tuple[float,...]:
    sign=1.0 if direction=="LONG" else -1.0
    distance=(terminal-entry)*sign
    if distance<LADDER_STEP_USD:return ()
    steps=min(MAX_LADDER_STEPS,int(np.floor(distance/LADDER_STEP_USD+1e-12)))
    return tuple(round(entry+sign*LADDER_STEP_USD*i,5) for i in range(1,steps+1))


def _m15_sweep(rows:Sequence[Bar],i:int,direction:str)->bool:
    if i<M15_SWEEP_LOOKBACK:return False
    row=rows[i];prior=rows[i-M15_SWEEP_LOOKBACK:i]
    if direction=="SHORT":
        level=max(float(x.high) for x in prior)
        return float(row.high)>level and float(row.close)<level
    level=min(float(x.low) for x in prior)
    return float(row.low)<level and float(row.close)>level


def build_forecasts(rows:Sequence[Bar],*,variant:str,evaluation_end)->tuple[Forecast,...]:
    if variant not in VARIANTS:raise ValueError("V152_UNKNOWN_VARIANT")
    bars=tuple(sorted(rows,key=lambda x:ensure_utc(x.timestamp)))
    end=ensure_utc(evaluation_end)

    d1=build_d1_context(bars)
    d1_lookup=_Asof(d1)
    h4=_resample_completed(bars,"4h")
    h1=_resample_completed(bars,"1h")
    h1["atr14"]=_wilder_atr(h1,14)
    h1_lookup=_Asof(h1)

    h4p=_PivotAsof(_confirmed_pivots(h4))
    h1p=_PivotAsof(_confirmed_pivots(h1))
    daily=_completed_extremes(bars,"1D")
    weekly=_completed_extremes(bars,"7D")
    daily_lookup=_Asof(daily);weekly_lookup=_Asof(weekly)

    forecasts=[]
    blocked_until=None
    for i,row in enumerate(bars[:-1]):
        signal_at=ensure_utc(row.timestamp)
        if signal_at>=end:break
        if blocked_until is not None and signal_at<=blocked_until:continue

        d=d1_lookup.row(signal_at);h1row=h1_lookup.row(signal_at)
        if d is None or h1row is None:continue
        dside=int(d.get("regime_side") or 0)
        if dside==0:continue

        hp4=h4p.available(signal_at);hp1=h1p.available(signal_at)
        s4=_structure_side(hp4);s1=_structure_side(hp1)
        if s4==0 or s4!=dside:continue

        price=float(row.close)
        dr=_latest_range(hp4)
        if dr is None:continue
        lo,hi=dr;mid=0.5*(lo+hi)
        direction="LONG" if dside>0 else "SHORT"
        dealing="DISCOUNT" if price<=mid else "PREMIUM"
        if direction=="LONG" and dealing!="DISCOUNT":continue
        if direction=="SHORT" and dealing!="PREMIUM":continue

        if variant in {"HTF_PLUS_H1_STRUCTURE","HTF_PLUS_H1_PLUS_M15_SWEEP"} and s1!=dside:
            continue
        sweep=_m15_sweep(bars,i,direction)
        if variant=="HTF_PLUS_H1_PLUS_M15_SWEEP" and not sweep:
            continue

        dl=daily_lookup.row(signal_at);wl=weekly_lookup.row(signal_at)
        target=_nearest_liquidity(
            price=price,direction=direction,h1_pivots=hp1,h4_pivots=hp4,daily=dl,weekly=wl
        )
        if target is None:continue
        terminal,source=target
        h1atr=float(h1row.get("atr14",np.nan))
        stop=_protected_stop(
            price=price,direction=direction,h1_pivots=hp1,h4_pivots=hp4,h1_atr=h1atr
        )
        if stop is None:continue

        sign=1.0 if direction=="LONG" else -1.0
        reward=(terminal-price)*sign
        risk=(price-stop)*sign
        if reward<=0 or risk<=0 or reward/risk<MIN_TERMINAL_RR:continue
        ladder=build_ladder(price,terminal,direction)
        if not ladder:continue

        entry_at=ensure_utc(bars[i+1].timestamp)
        entry=float(bars[i+1].open)
        # Recompute route geometry at executable next-open price; target/stop
        # are frozen from signal-time liquidity map.
        reward2=(terminal-entry)*sign;risk2=(entry-stop)*sign
        if reward2<=0 or risk2<=0 or reward2/risk2<MIN_TERMINAL_RR:continue
        ladder=build_ladder(entry,terminal,direction)
        if not ladder:continue

        f=Forecast(
            variant,direction,signal_at,entry_at,entry,stop,terminal,source,ladder,
            dside,s4,s1,dealing,sweep,
        )
        forecasts.append(f)
        # One discrete AFIC-style forecast at a time; no repeated M15 spam.
        blocked_until=entry_at
    return tuple(forecasts)


def _evaluate_forecast(f:Forecast,bars:Sequence[Bar],entry_index:int,horizon:int)->dict[str,Any]:
    sign=1.0 if f.direction=="LONG" else -1.0
    max_i=min(len(bars)-1,entry_index+horizon)
    hit=[False]*len(f.ladder)
    stop_hit=False
    terminal_hit=False
    exit_reason="TIME"
    exit_at=ensure_utc(bars[max_i].timestamp)
    for j in range(entry_index,max_i+1):
        b=bars[j]
        if f.direction=="LONG":
            s=float(b.low)<=f.stop
            hits=[float(b.high)>=x for x in f.ladder]
            th=float(b.high)>=f.terminal_target
        else:
            s=float(b.high)>=f.stop
            hits=[float(b.low)<=x for x in f.ladder]
            th=float(b.low)<=f.terminal_target
        # Conservative same-bar ambiguity: stop dominates.
        if s:
            stop_hit=True;exit_reason="STOP";exit_at=ensure_utc(b.timestamp);break
        for k,v in enumerate(hits):
            hit[k]=hit[k] or v
        if th:
            terminal_hit=True;exit_reason="TERMINAL";exit_at=ensure_utc(b.timestamp);break
    rr_terminal=abs(f.terminal_target-f.entry)/abs(f.entry-f.stop)
    return {
        "tp_hits":hit,
        "tp1_hit":bool(hit[0]) if hit else False,
        "terminal_hit":terminal_hit,
        "stop_hit":stop_hit,
        "exit_reason":exit_reason,
        "exit_at":exit_at.isoformat(),
        "terminal_rr":rr_terminal,
    }


def evaluate_variant(rows:Sequence[Bar],*,variant:str,evaluation_start,evaluation_end)->dict[str,Any]:
    bars=tuple(sorted(rows,key=lambda x:ensure_utc(x.timestamp)))
    by_time={ensure_utc(b.timestamp):i for i,b in enumerate(bars)}
    fs=tuple(
        f for f in build_forecasts(bars,variant=variant,evaluation_end=evaluation_end)
        if ensure_utc(evaluation_start)<=ensure_utc(f.entry_at)<ensure_utc(evaluation_end)
    )
    horizon_out={}
    for h in FORECAST_HORIZONS:
        evals=[]
        for f in fs:
            idx=by_time.get(ensure_utc(f.entry_at))
            if idx is None:continue
            evals.append(_evaluate_forecast(f,bars,idx,h))
        n=len(evals)
        max_steps=max((len(x["tp_hits"]) for x in evals),default=0)
        step_rates=[]
        for k in range(max_steps):
            eligible=[x for x in evals if len(x["tp_hits"])>k]
            step_rates.append({
                "step":k+1,
                "eligible":len(eligible),
                "hit_rate":None if not eligible else sum(bool(x["tp_hits"][k]) for x in eligible)/len(eligible),
            })
        horizon_out[str(h)]={
            "n":n,
            "tp1_hit_rate":None if n==0 else sum(x["tp1_hit"] for x in evals)/n,
            "terminal_hit_rate":None if n==0 else sum(x["terminal_hit"] for x in evals)/n,
            "stop_rate":None if n==0 else sum(x["stop_hit"] for x in evals)/n,
            "step_hit_rates":step_rates,
            "median_terminal_rr":None if n==0 else float(np.median([x["terminal_rr"] for x in evals])),
        }
    return {
        "variant":variant,
        "forecasts":len(fs),
        "direction_counts":{
            "LONG":sum(f.direction=="LONG" for f in fs),
            "SHORT":sum(f.direction=="SHORT" for f in fs),
        },
        "terminal_sources":{
            s:sum(f.terminal_source==s for f in fs)
            for s in sorted({f.terminal_source for f in fs})
        },
        "horizons":horizon_out,
        "examples":[f.payload() for f in fs[:10]],
    }


def evaluate_v152(rows:Sequence[Bar],*,evaluation_end)->dict[str,Any]:
    end=ensure_utc(evaluation_end)
    full_start=datetime(2012,1,1,tzinfo=timezone.utc)
    eras={}
    for label,a,b in ERA_WINDOWS:
        bb=min(ensure_utc(b),end)
        if ensure_utc(a)>=bb:continue
        eras[label]={
            v:evaluate_variant(rows,variant=v,evaluation_start=a,evaluation_end=bb)
            for v in VARIANTS
        }
    full={
        v:evaluate_variant(rows,variant=v,evaluation_start=full_start,evaluation_end=end)
        for v in VARIANTS
    }
    return {
        "research_version":RESEARCH_VERSION,
        "artifact_contract":ARTIFACT_CONTRACT,
        "policy_effect":POLICY_EFFECT,
        "execution_influence":EXECUTION_INFLUENCE,
        "promotion_eligible":PROMOTION_ELIGIBLE,
        "live_execution_enabled":False,
        "reconstruction_basis":{
            "user_supplied_buy_example":"BUY 4278 / SL 4265 / TP 4281..4299 in $3 steps",
            "user_supplied_sell_example":"SELL 4349 / SL 4359 / TP 4346..4331 in $3 steps",
            "inference":"terminal objective may be liquidity-derived and then partitioned into $3 target steps",
            "claim_limit":"does not claim to reproduce proprietary AFIC rules",
        },
        "contract":{
            "direction":"completed D1 regime side must match causal H4 HH/HL or LH/LL structure",
            "location":"LONG only in H4 discount; SHORT only in H4 premium",
            "optional_h1":"variant requires matching H1 structure",
            "optional_entry_timing":"variant requires M15 local liquidity sweep/reclaim",
            "terminal_liquidity":"nearest causal PDH/PDL/PWH/PWL/H1/H4 swing liquidity in forecast direction",
            "stop":"nearest opposite protected H1 swing, fallback H4 swing, plus 0.10 H1 ATR buffer",
            "minimum_terminal_rr":MIN_TERMINAL_RR,
            "ladder_step_usd":LADDER_STEP_USD,
            "max_ladder_steps":MAX_LADDER_STEPS,
            "forecast_horizons_m15_bars":list(FORECAST_HORIZONS),
            "same_bar_ambiguity":"STOP_FIRST",
            "pivot_confirmation":"2 left / 2 right; pivot usable only after right-side confirmation",
            "no_calendar_routing":True,
            "no_parameter_grid":True,
            "outcome_metric":"TP1 and each ladder step reported separately from terminal-target hit rate",
        },
        "full":full,
        "eras":eras,
        "note":"V152 is forensic reconstruction. A headline ~85% forecast accuracy is not accepted unless the exact outcome definition (TP1 vs terminal target) is reproduced causally.",
    }

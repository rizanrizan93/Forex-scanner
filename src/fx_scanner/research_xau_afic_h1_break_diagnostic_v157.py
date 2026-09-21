from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Sequence
import numpy as np

from .models import Bar, ensure_utc
from .research_xau_hierarchical_regime_router_v35 import _resample_completed
from .research_xau_afic_liquidity_forecast_v152 import _PivotAsof, _confirmed_pivots
from .research_xau_afic_public_path_state_v155 import FORECAST_HORIZONS, build_forecasts as build_v155_forecasts

RESEARCH_VERSION="XAU_AFIC_H1_BREAK_DIAGNOSTIC_V157"
ARTIFACT_CONTRACT="XAU_AFIC_H1_BREAK_DIAGNOSTIC_V157_EVIDENCE_1"
POLICY_EFFECT="SHADOW_ONLY"
EXECUTION_INFLUENCE=False
PROMOTION_ELIGIBLE=False

BREAK_DEFINITIONS=(
    "PREVIOUS_H1_EXTREME",
    "SIGNAL_H1_EXTREME",
    "LOCAL_3H_STRUCTURE",
    "CONFIRMED_PIVOT",
)
VARIANTS=("PUBLIC_SHORT_M15_ENGULF","MIRROR_BIDIR_M15_ENGULF")
ERA_START=datetime(2025,1,1,tzinfo=timezone.utc)


def _h1_rows_before(h1,timestamp):
    return h1[h1["time"]<=ensure_utc(timestamp)]


def _break_level(h1,h1p,timestamp,direction,definition,signal_at=None):
    past=_h1_rows_before(h1,timestamp)
    if len(past)<4:
        return None

    if definition=="PREVIOUS_H1_EXTREME":
        row=past.iloc[-1]
        return float(row["low"] if direction=="SHORT" else row["high"])

    if definition=="SIGNAL_H1_EXTREME":
        signal_past=_h1_rows_before(h1,signal_at if signal_at is not None else timestamp)
        if len(signal_past)<1:
            return None
        # Freeze the H1 reference that was already completed when the original
        # M15 signal appeared; later TP1 movement cannot move this level.
        row=signal_past.iloc[-1]
        return float(row["low"] if direction=="SHORT" else row["high"])

    if definition=="LOCAL_3H_STRUCTURE":
        recent=past.iloc[-3:]
        return float(recent["low"].min() if direction=="SHORT" else recent["high"].max())

    if definition=="CONFIRMED_PIVOT":
        available=h1p.available(timestamp)
        vals=[x.price for x in available if x.kind==("LOW" if direction=="SHORT" else "HIGH")]
        return None if not vals else float(vals[-1])

    raise ValueError(f"V157_UNKNOWN_BREAK_DEF:{definition}")


def _tp1_index(f,bars,entry_index,max_i):
    tp1=float(f.ladder[0])
    for j in range(entry_index,max_i+1):
        b=bars[j]
        if f.direction=="LONG":
            if float(b.low)<=f.stop:return None,"STOP"
            if float(b.high)>=tp1:return j,"TP1"
        else:
            if float(b.high)>=f.stop:return None,"STOP"
            if float(b.low)<=tp1:return j,"TP1"
    return None,"TIME"


def _diagnose_one(f,bars,entry_index,h1,h1p,horizon,definition):
    max_i=min(len(bars)-1,entry_index+horizon)
    tp1_i,status=_tp1_index(f,bars,entry_index,max_i)
    if tp1_i is None:
        return {"tp1_hit":False,"pre_tp1_status":status,"break_after_tp1":False,"terminal_after_break":False,"be_after_tp1":False}

    level=_break_level(
        h1,h1p,ensure_utc(bars[tp1_i].timestamp),f.direction,definition,
        signal_at=f.signal_at,
    )
    if level is None:
        return {"tp1_hit":True,"pre_tp1_status":"TP1","break_after_tp1":False,"terminal_after_break":False,"be_after_tp1":False}

    h1_after=h1[h1["time"]>=ensure_utc(bars[tp1_i].timestamp)]
    break_time=None
    for _,row in h1_after.iterrows():
        t=ensure_utc(row["time"].to_pydatetime() if hasattr(row["time"],"to_pydatetime") else row["time"])
        if t>ensure_utc(bars[max_i].timestamp):break
        close=float(row["close"])
        if (f.direction=="SHORT" and close<level) or (f.direction=="LONG" and close>level):
            break_time=t
            break

    broke=False
    terminal_after_break=False
    be_after_tp1=False
    for j in range(tp1_i+1,max_i+1):
        b=bars[j];t=ensure_utc(b.timestamp)
        if break_time is not None and t>=break_time:
            broke=True
        if f.direction=="LONG":
            be=float(b.low)<=f.entry;terminal=float(b.high)>=f.terminal_target
        else:
            be=float(b.high)>=f.entry;terminal=float(b.low)<=f.terminal_target
        if be:
            be_after_tp1=True;break
        if terminal:
            terminal_after_break=bool(broke);break

    return {
        "tp1_hit":True,
        "pre_tp1_status":"TP1",
        "break_after_tp1":broke,
        "terminal_after_break":terminal_after_break,
        "be_after_tp1":be_after_tp1,
        "break_level":level,
        "break_time":None if break_time is None else break_time.isoformat(),
    }


def evaluate_v157(rows:Sequence[Bar],*,evaluation_end)->dict[str,Any]:
    bars=tuple(sorted(rows,key=lambda x:ensure_utc(x.timestamp)))
    end=ensure_utc(evaluation_end)
    by_time={ensure_utc(b.timestamp):i for i,b in enumerate(bars)}
    h1=_resample_completed(bars,"1h")
    h1p=_PivotAsof(_confirmed_pivots(h1))

    payload={}
    for variant in VARIANTS:
        forecasts=tuple(f for f in build_v155_forecasts(bars,variant=variant,evaluation_end=end) if ERA_START<=ensure_utc(f.entry_at)<end)
        variant_out={}
        for h in FORECAST_HORIZONS:
            defs={}
            for definition in BREAK_DEFINITIONS:
                vals=[]
                for f in forecasts:
                    idx=by_time.get(ensure_utc(f.entry_at))
                    if idx is not None:
                        vals.append((f,_diagnose_one(f,bars,idx,h1,h1p,h,definition)))
                tp1=[x for _,x in vals if x["tp1_hit"]]
                br=[x for _,x in vals if x["tp1_hit"] and x["break_after_tp1"]]
                defs[definition]={
                    "n":len(vals),
                    "tp1_hits":len(tp1),
                    "break_after_tp1_count":len(br),
                    "break_after_tp1_rate":None if not tp1 else len(br)/len(tp1),
                    "terminal_given_break_rate":None if not br else sum(x["terminal_after_break"] for x in br)/len(br),
                    "be_after_tp1_rate":None if not tp1 else sum(x["be_after_tp1"] for x in tp1)/len(tp1),
                }
            variant_out[str(h)]=defs
        payload[variant]={
            "forecasts":len(forecasts),
            "horizons":variant_out,
        }

    return {
        "research_version":RESEARCH_VERSION,
        "artifact_contract":ARTIFACT_CONTRACT,
        "policy_effect":POLICY_EFFECT,
        "execution_influence":EXECUTION_INFLUENCE,
        "promotion_eligible":PROMOTION_ELIGIBLE,
        "live_execution_enabled":False,
        "definitions":{
            "PREVIOUS_H1_EXTREME":"completed H1 low/high immediately available after TP1",
            "SIGNAL_H1_EXTREME":"latest completed H1 candle used as local breakdown reference",
            "LOCAL_3H_STRUCTURE":"lowest low / highest high of last 3 completed H1 bars",
            "CONFIRMED_PIVOT":"2-left/2-right confirmed H1 swing used in V156",
        },
        "recent":payload,
        "note":"Diagnostic only. Entry, stop, target, and V155 forecast set are frozen; V157 only operationalizes the ambiguous public phrase H1 breakdown.",
    }

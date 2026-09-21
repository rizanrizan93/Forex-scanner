from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Sequence

import numpy as np

from .models import Bar, ensure_utc
from .research_xau_hierarchical_regime_router_v35 import _resample_completed
from .research_xau_afic_liquidity_forecast_v152 import _PivotAsof, _confirmed_pivots
from .research_xau_afic_public_path_state_v155 import (
    Forecast,
    FORECAST_HORIZONS,
    build_forecasts as build_v155_forecasts,
)

RESEARCH_VERSION="XAU_AFIC_RUNNER_STATE_V156"
ARTIFACT_CONTRACT="XAU_AFIC_RUNNER_STATE_V156_EVIDENCE_1"
POLICY_EFFECT="SHADOW_ONLY"
EXECUTION_INFLUENCE=False
PROMOTION_ELIGIBLE=False

VARIANTS=(
    "PUBLIC_SHORT_M15_ENGULF",
    "MIRROR_BIDIR_M15_ENGULF",
)

ERA_WINDOWS=(
    ("2012_2018",datetime(2012,1,1,tzinfo=timezone.utc),datetime(2019,1,1,tzinfo=timezone.utc)),
    ("2019_2024",datetime(2019,1,1,tzinfo=timezone.utc),datetime(2025,1,1,tzinfo=timezone.utc)),
    ("2025_2026YTD",datetime(2025,1,1,tzinfo=timezone.utc),datetime(2026,9,20,tzinfo=timezone.utc)),
)


def _latest_break_level(h1p:_PivotAsof,timestamp,direction:str)->float|None:
    available=h1p.available(timestamp)
    if direction=="SHORT":
        vals=[x.price for x in available if x.kind=="LOW"]
    else:
        vals=[x.price for x in available if x.kind=="HIGH"]
    return None if not vals else float(vals[-1])


def _runner_sequence(
    f:Forecast,
    *,
    bars:Sequence[Bar],
    entry_index:int,
    h1,
    h1p:_PivotAsof,
    horizon:int,
)->dict[str,Any]:
    max_i=min(len(bars)-1,entry_index+horizon)
    tp1=float(f.ladder[0])
    break_level=_latest_break_level(h1p,f.entry_at,f.direction)

    tp1_index=None
    stop_before_tp1=False
    be_after_tp1=False
    h1_break_after_tp1=False
    h1_break_at=None
    terminal_after_h1_break=False

    # First stage: public M15-confirmed entry -> partial target.
    for j in range(entry_index,max_i+1):
        b=bars[j]
        if f.direction=="LONG":
            stop_hit=float(b.low)<=f.stop
            tp1_hit=float(b.high)>=tp1
        else:
            stop_hit=float(b.high)>=f.stop
            tp1_hit=float(b.low)<=tp1

        if stop_hit:
            stop_before_tp1=True
            return {
                "tp1_hit":False,
                "stop_before_tp1":True,
                "h1_break_after_tp1":False,
                "runner_be_after_tp1":False,
                "terminal_after_h1_break":False,
                "break_level":break_level,
                "h1_break_at":None,
            }
        if tp1_hit:
            tp1_index=j
            break

    if tp1_index is None:
        return {
            "tp1_hit":False,
            "stop_before_tp1":False,
            "h1_break_after_tp1":False,
            "runner_be_after_tp1":False,
            "terminal_after_h1_break":False,
            "break_level":break_level,
            "h1_break_at":None,
        }

    # Public sequence: take some layers / protect at BE, THEN wait for H1
    # breakdown as continuation evidence. H1 breakdown is not an entry gate.
    h1_after=h1[h1["time"]>=ensure_utc(bars[tp1_index].timestamp)]
    h1_break_times=[]
    if break_level is not None:
        for _,row in h1_after.iterrows():
            t=ensure_utc(row["time"].to_pydatetime() if hasattr(row["time"],"to_pydatetime") else row["time"])
            if t>ensure_utc(bars[max_i].timestamp):
                break
            close=float(row["close"])
            passed=(f.direction=="SHORT" and close<break_level) or (f.direction=="LONG" and close>break_level)
            if passed:
                h1_break_times.append(t)
                break

    next_break=h1_break_times[0] if h1_break_times else None

    for j in range(tp1_index+1,max_i+1):
        b=bars[j]
        t=ensure_utc(b.timestamp)

        if next_break is not None and not h1_break_after_tp1 and t>=next_break:
            h1_break_after_tp1=True
            h1_break_at=next_break

        if f.direction=="LONG":
            be_hit=float(b.low)<=f.entry
            terminal=float(b.high)>=f.terminal_target
        else:
            be_hit=float(b.high)>=f.entry
            terminal=float(b.low)<=f.terminal_target

        # Runner has been protected at BE after TP1. Same-bar BE remains
        # conservative over deeper target.
        if be_hit:
            be_after_tp1=True
            break
        if terminal:
            if h1_break_after_tp1:
                terminal_after_h1_break=True
            break

    return {
        "tp1_hit":True,
        "stop_before_tp1":False,
        "h1_break_after_tp1":h1_break_after_tp1,
        "runner_be_after_tp1":be_after_tp1,
        "terminal_after_h1_break":terminal_after_h1_break,
        "break_level":break_level,
        "h1_break_at":None if h1_break_at is None else h1_break_at.isoformat(),
    }


def _summarize(rows:Sequence[Bar],forecasts:Sequence[Forecast],start,end)->dict[str,Any]:
    bars=tuple(sorted(rows,key=lambda x:ensure_utc(x.timestamp)))
    by_time={ensure_utc(b.timestamp):i for i,b in enumerate(bars)}
    h1=_resample_completed(bars,"1h")
    h1p=_PivotAsof(_confirmed_pivots(h1))

    fs=tuple(f for f in forecasts if ensure_utc(start)<=ensure_utc(f.entry_at)<ensure_utc(end))
    horizons={}

    for h in FORECAST_HORIZONS:
        pairs=[]
        for f in fs:
            idx=by_time.get(ensure_utc(f.entry_at))
            if idx is not None:
                pairs.append((f,_runner_sequence(f,bars=bars,entry_index=idx,h1=h1,h1p=h1p,horizon=h)))

        n=len(pairs)
        tp1=[x for _,x in pairs if x["tp1_hit"]]
        broke=[x for _,x in pairs if x["tp1_hit"] and x["h1_break_after_tp1"]]
        directions={}
        for side in ("LONG","SHORT"):
            e=[x for f,x in pairs if f.direction==side]
            etp=[x for x in e if x["tp1_hit"]]
            eb=[x for x in etp if x["h1_break_after_tp1"]]
            directions[side]={
                "n":len(e),
                "tp1_hit_rate":None if not e else sum(x["tp1_hit"] for x in e)/len(e),
                "h1_break_after_tp1_rate":None if not etp else len(eb)/len(etp),
                "terminal_given_h1_break_rate":None if not eb else sum(x["terminal_after_h1_break"] for x in eb)/len(eb),
                "runner_be_after_tp1_rate":None if not etp else sum(x["runner_be_after_tp1"] for x in etp)/len(etp),
            }

        horizons[str(h)]={
            "n":n,
            "tp1_hit_rate":None if n==0 else len(tp1)/n,
            "stop_before_tp1_rate":None if n==0 else sum(x["stop_before_tp1"] for _,x in pairs)/n,
            "h1_break_after_tp1_rate":None if not tp1 else len(broke)/len(tp1),
            "terminal_given_h1_break_rate":None if not broke else sum(x["terminal_after_h1_break"] for x in broke)/len(broke),
            "runner_be_after_tp1_rate":None if not tp1 else sum(x["runner_be_after_tp1"] for x in tp1)/len(tp1),
            "median_published_rr":None if not pairs else float(np.median([
                abs(f.terminal_target-f.entry)/abs(f.entry-f.stop) for f,_ in pairs
            ])),
            "direction":directions,
        }

    return {
        "forecasts":len(fs),
        "direction_counts":{"LONG":sum(f.direction=="LONG" for f in fs),"SHORT":sum(f.direction=="SHORT" for f in fs)},
        "horizons":horizons,
    }


def evaluate_v156(rows:Sequence[Bar],*,evaluation_end)->dict[str,Any]:
    bars=tuple(sorted(rows,key=lambda x:ensure_utc(x.timestamp)))
    end=ensure_utc(evaluation_end)
    streams={
        v:build_v155_forecasts(bars,variant=v,evaluation_end=end)
        for v in VARIANTS
    }
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
        "contract":{
            "entry":"unchanged V155 M15 engulfing/rejection entry",
            "tp1":"take partial when first $3 ladder target is hit",
            "runner":"move remaining exposure to BE after TP1",
            "h1_breakdown":"post-entry continuation confirmation only; never an entry prerequisite",
            "deeper_target":"measure terminal hit conditional on H1 breakdown after TP1",
            "public_sequence_basis":"AFIC public post reports profit/BE first, then says wait for H1 breakdown",
            "no_parameter_grid":True,
            "no_execution_authority":True,
        },
        "full":full,
        "eras":eras,
        "note":"V156 corrects the V155 interpretation error: H1 breakdown is modeled as runner authorization after M15 entry/partial-profit, matching public AFIC chronology.",
    }

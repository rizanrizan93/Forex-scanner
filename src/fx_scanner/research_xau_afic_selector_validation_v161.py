from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite
from typing import Any, Sequence

from .models import Bar, ensure_utc
from .research_xau_hierarchical_regime_router_v35 import _resample_completed, _wilder_atr
from .research_xau_afic_planb_remap_v159 import build_scenarios, _second_leg_outcome

RESEARCH_VERSION="XAU_AFIC_SELECTOR_VALIDATION_V161"
ARTIFACT_CONTRACT="XAU_AFIC_SELECTOR_VALIDATION_V161_EVIDENCE_1"
POLICY_EFFECT="SHADOW_ONLY"
EXECUTION_INFLUENCE=False
PROMOTION_ELIGIBLE=False
LIVE_EXECUTION_ENABLED=False

MAX_ZONE_DISTANCE_ATR=0.75
MAX_H4_DIRECTIONAL_CLOSE_LOC=0.65

ERA_WINDOWS=(
    ("2012_2018",datetime(2012,1,1,tzinfo=timezone.utc),datetime(2019,1,1,tzinfo=timezone.utc)),
    ("2019_2024",datetime(2019,1,1,tzinfo=timezone.utc),datetime(2025,1,1,tzinfo=timezone.utc)),
    ("2025_2026YTD",datetime(2025,1,1,tzinfo=timezone.utc),datetime(2026,9,20,tzinfo=timezone.utc)),
)

def _safe(v):
    try:
        x=float(v)
        return x if isfinite(x) else None
    except Exception:
        return None

def _decorate(rows:Sequence[Bar],evaluation_end):
    bars=tuple(sorted(rows,key=lambda x:ensure_utc(x.timestamp)))
    scenarios=build_scenarios(bars,evaluation_end=evaluation_end)

    h4=_resample_completed(bars,"4h").copy()
    h4["atr14"]=_wilder_atr(h4,14)
    by_h4={}
    for _,r in h4.iterrows():
        t=ensure_utc(r["time"].to_pydatetime() if hasattr(r["time"],"to_pydatetime") else r["time"])
        by_h4[t]=r

    out=[]
    for s in scenarios:
        r=by_h4.get(ensure_utc(s.map_at))
        if r is None:
            continue
        o,h,l,c=map(float,(r["open"],r["high"],r["low"],r["close"]))
        atr=_safe(r.get("atr14"))
        rng=max(h-l,1e-12)
        direction=1 if s.continuation_direction=="LONG" else -1
        directional_close=(c-l)/rng if direction>0 else (h-c)/rng
        if s.continuation_direction=="SHORT":
            raw_dist=max(0.0,float(s.zone.low)-float(s.map_price))
        else:
            raw_dist=max(0.0,float(s.map_price)-float(s.zone.high))
        zone_distance_atr=None if atr in (None,0.0) else raw_dist/atr

        ev=None
        if s.primary_status=="CONFIRMED" and s.confirm_index is not None:
            ev=_second_leg_outcome(f=s,bars=bars,confirm_index=int(s.confirm_index))

        selected=(
            zone_distance_atr is not None
            and zone_distance_atr<=MAX_ZONE_DISTANCE_ATR
            and directional_close<=MAX_H4_DIRECTIONAL_CLOSE_LOC
        )

        out.append({
            "scenario":s,
            "selected":selected,
            "zone_distance_atr":zone_distance_atr,
            "h4_directional_close_loc":directional_close,
            "tp1":None if ev is None else bool(ev["tp1_hit"]),
            "terminal":None if ev is None else bool(ev["terminal_hit"]),
        })
    return out

def _metrics(rows):
    n=len(rows)
    hit=[x for x in rows if x["scenario"].first_touch_at is not None]
    confirmed=[x for x in rows if x["scenario"].primary_status=="CONFIRMED"]
    tp1=[x for x in confirmed if x["tp1"]]
    terminal=[x for x in confirmed if x["terminal"]]
    return {
        "n":n,
        "first_leg_hit_rate":None if n==0 else len(hit)/n,
        "confirm_rate_all":None if n==0 else len(confirmed)/n,
        "confirm_rate_given_hit":None if not hit else len(confirmed)/len(hit),
        "tp1_rate_given_confirm":None if not confirmed else len(tp1)/len(confirmed),
        "terminal_rate_given_confirm":None if not confirmed else len(terminal)/len(confirmed),
        "confirmed_count":len(confirmed),
        "tp1_count":len(tp1),
        "terminal_count":len(terminal),
    }

def _scope(rows,start,end):
    xs=[x for x in rows if ensure_utc(start)<=ensure_utc(x["scenario"].map_at)<ensure_utc(end)]
    selected=[x for x in xs if x["selected"]]
    return {
        "baseline":_metrics(xs),
        "selected":_metrics(selected),
        "selection_rate":None if not xs else len(selected)/len(xs),
        "selected_direction_counts":{
            "LONG":sum(x["scenario"].continuation_direction=="LONG" for x in selected),
            "SHORT":sum(x["scenario"].continuation_direction=="SHORT" for x in selected),
        },
    }

def evaluate_v161(rows:Sequence[Bar],*,evaluation_end)->dict[str,Any]:
    end=ensure_utc(evaluation_end)
    xs=_decorate(rows,end)

    full_start=datetime(2012,1,1,tzinfo=timezone.utc)
    scopes={"FULL":_scope(xs,full_start,end)}
    for label,a,b in ERA_WINDOWS:
        bb=min(ensure_utc(b),end)
        if ensure_utc(a)<bb:
            scopes[label]=_scope(xs,a,bb)

    return {
        "research_version":RESEARCH_VERSION,
        "artifact_contract":ARTIFACT_CONTRACT,
        "policy_effect":POLICY_EFFECT,
        "execution_influence":EXECUTION_INFLUENCE,
        "promotion_eligible":PROMOTION_ELIGIBLE,
        "live_execution_enabled":LIVE_EXECUTION_ENABLED,
        "selector":{
            "zone_distance_atr_max":MAX_ZONE_DISTANCE_ATR,
            "h4_directional_close_loc_max":MAX_H4_DIRECTIONAL_CLOSE_LOC,
            "origin":"preregistered in V160 before V160 result inspection",
            "calendar_used_for_routing":False,
            "parameter_grid_search":False,
        },
        "scopes":scopes,
        "acceptance_guidance":{
            "goal":"reduce false H4 maps while preserving first-leg reach and post-confirm TP1 behavior across eras",
            "must_not_claim":"85% universal win rate from recent small sample",
            "next_step_if_stable":"prospective shadow observer using selector",
            "next_step_if_unstable":"keep V159/V160 diagnostic only and investigate causal H4-map features without retuning V161",
        },
    }

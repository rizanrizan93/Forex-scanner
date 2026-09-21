from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite
from typing import Any, Sequence

import numpy as np
import pandas as pd

from .models import Bar, ensure_utc
from .research_xau_hierarchical_regime_router_v35 import _resample_completed, _wilder_atr
from .research_xau_afic_planb_remap_v159 import build_scenarios, _second_leg_outcome

RESEARCH_VERSION="XAU_AFIC_SELECTOR_FORENSIC_V160"
ARTIFACT_CONTRACT="XAU_AFIC_SELECTOR_FORENSIC_V160_EVIDENCE_1"
POLICY_EFFECT="SHADOW_ONLY"
EXECUTION_INFLUENCE=False
PROMOTION_ELIGIBLE=False

RECENT_START=datetime(2025,1,1,tzinfo=timezone.utc)

BINS={
    "zone_distance_atr":[0.0,0.35,0.75,1.10,1.50,2.00,999.0],
    "h4_directional_close_loc":[0.0,0.25,0.50,0.65,0.80,1.000001],
    "h4_body_fraction":[0.0,0.25,0.50,0.75,1.000001],
    "h4_range_atr":[0.0,0.75,1.00,1.25,1.75,2.50,999.0],
    "zone_age_hours":[0.0,4.0,8.0,12.0,18.0,24.0001],
    "zone_displacement_atr":[1.0,1.25,1.50,2.00,3.00,999.0],
    "zone_displacement_body_fraction":[0.50,0.60,0.70,0.80,0.90,1.000001],
}

def _safe(v):
    try:
        x=float(v)
        return x if isfinite(x) else None
    except Exception:
        return None

def _h4_features(rows:Sequence[Bar]):
    h4=_resample_completed(rows,"4h").copy()
    h4["atr14"]=_wilder_atr(h4,14)
    return h4

def _scenario_rows(rows:Sequence[Bar],evaluation_end):
    bars=tuple(sorted(rows,key=lambda x:ensure_utc(x.timestamp)))
    scenarios=build_scenarios(bars,evaluation_end=evaluation_end)
    h4=_h4_features(bars)
    by_h4={}
    for _,r in h4.iterrows():
        t=ensure_utc(r["time"].to_pydatetime() if hasattr(r["time"],"to_pydatetime") else r["time"])
        by_h4[t]=r

    out=[]
    for s in scenarios:
        if ensure_utc(s.map_at)<RECENT_START:
            continue
        r=by_h4.get(ensure_utc(s.map_at))
        if r is None:
            continue
        o,h,l,c=map(float,(r["open"],r["high"],r["low"],r["close"]))
        atr=_safe(r.get("atr14"))
        rng=max(h-l,1e-12)
        body=abs(c-o)
        direction=1 if s.continuation_direction=="LONG" else -1
        directional_close=(c-l)/rng if direction>0 else (h-c)/rng
        if s.continuation_direction=="SHORT":
            raw_dist=max(0.0,float(s.zone.low)-float(s.map_price))
        else:
            raw_dist=max(0.0,float(s.map_price)-float(s.zone.high))
        zone_distance_atr=None if atr in (None,0.0) else raw_dist/atr
        zone_age=(ensure_utc(s.map_at)-ensure_utc(s.zone.available_at)).total_seconds()/3600.0

        tp1=None
        terminal=None
        if s.primary_status=="CONFIRMED" and s.confirm_index is not None:
            ev=_second_leg_outcome(f=s,bars=bars,confirm_index=int(s.confirm_index))
            tp1=bool(ev["tp1_hit"])
            terminal=bool(ev["terminal_hit"])

        out.append({
            "map_at":ensure_utc(s.map_at),
            "direction":s.continuation_direction,
            "status":s.primary_status,
            "first_leg_hit":s.first_touch_at is not None,
            "confirmed":s.primary_status=="CONFIRMED",
            "tp1_given_confirm":tp1,
            "terminal_given_confirm":terminal,
            "zone_distance_atr":zone_distance_atr,
            "h4_directional_close_loc":directional_close,
            "h4_body_fraction":body/rng,
            "h4_range_atr":None if atr in (None,0.0) else rng/atr,
            "zone_age_hours":zone_age,
            "zone_displacement_atr":float(s.zone.displacement_range_atr),
            "zone_displacement_body_fraction":float(s.zone.displacement_body_fraction),
        })
    return out

def _metric(rows):
    n=len(rows)
    hit=[x for x in rows if x["first_leg_hit"]]
    confirmed=[x for x in rows if x["confirmed"]]
    tp1=[x for x in confirmed if x["tp1_given_confirm"]]
    terminal=[x for x in confirmed if x["terminal_given_confirm"]]
    return {
        "n":n,
        "first_leg_hit_rate":None if n==0 else len(hit)/n,
        "confirm_rate_all":None if n==0 else len(confirmed)/n,
        "confirm_rate_given_hit":None if not hit else len(confirmed)/len(hit),
        "tp1_rate_given_confirm":None if not confirmed else len(tp1)/len(confirmed),
        "terminal_rate_given_confirm":None if not confirmed else len(terminal)/len(confirmed),
    }

def _bin_label(a,b):
    return f"[{a:g},{b:g})"

def _binned(rows,key,edges):
    result=[]
    for a,b in zip(edges[:-1],edges[1:]):
        subset=[x for x in rows if x.get(key) is not None and a<=float(x[key])<b]
        result.append({"bin":_bin_label(a,b),**_metric(subset)})
    return result

def _quantiles(rows,key):
    vals=[float(x[key]) for x in rows if x.get(key) is not None]
    if not vals:
        return None
    return {
        "p10":float(np.quantile(vals,.10)),
        "p25":float(np.quantile(vals,.25)),
        "p50":float(np.quantile(vals,.50)),
        "p75":float(np.quantile(vals,.75)),
        "p90":float(np.quantile(vals,.90)),
    }

def evaluate_v160(rows:Sequence[Bar],*,evaluation_end)->dict[str,Any]:
    xs=_scenario_rows(rows,evaluation_end)
    features={}
    for key,edges in BINS.items():
        features[key]={
            "all_quantiles":_quantiles(xs,key),
            "confirmed_quantiles":_quantiles([x for x in xs if x["confirmed"]],key),
            "bins":_binned(xs,key,edges),
        }

    combos={
        "near_zone_le_0_75atr":_metric([x for x in xs if x["zone_distance_atr"] is not None and x["zone_distance_atr"]<=0.75]),
        "close_not_extreme_le_0_65":_metric([x for x in xs if x["h4_directional_close_loc"] is not None and x["h4_directional_close_loc"]<=0.65]),
        "near_and_not_extreme":_metric([
            x for x in xs
            if x["zone_distance_atr"] is not None and x["zone_distance_atr"]<=0.75
            and x["h4_directional_close_loc"] is not None and x["h4_directional_close_loc"]<=0.65
        ]),
        "near_and_mid_close_0_25_0_65":_metric([
            x for x in xs
            if x["zone_distance_atr"] is not None and x["zone_distance_atr"]<=0.75
            and x["h4_directional_close_loc"] is not None and 0.25<=x["h4_directional_close_loc"]<=0.65
        ]),
    }

    confirmed=[x for x in xs if x["confirmed"]]
    return {
        "research_version":RESEARCH_VERSION,
        "artifact_contract":ARTIFACT_CONTRACT,
        "policy_effect":POLICY_EFFECT,
        "execution_influence":EXECUTION_INFLUENCE,
        "promotion_eligible":PROMOTION_ELIGIBLE,
        "recent_start":RECENT_START.isoformat(),
        "overall":_metric(xs),
        "direction":{
            "LONG":_metric([x for x in xs if x["direction"]=="LONG"]),
            "SHORT":_metric([x for x in xs if x["direction"]=="SHORT"]),
        },
        "features":features,
        "preregistered_simple_combos":combos,
        "confirmed_count":len(confirmed),
        "confirmed_examples":[
            {
                "map_at":x["map_at"].isoformat(),
                "direction":x["direction"],
                "zone_distance_atr":x["zone_distance_atr"],
                "h4_directional_close_loc":x["h4_directional_close_loc"],
                "h4_body_fraction":x["h4_body_fraction"],
                "h4_range_atr":x["h4_range_atr"],
                "zone_age_hours":x["zone_age_hours"],
                "tp1":x["tp1_given_confirm"],
                "terminal":x["terminal_given_confirm"],
            } for x in confirmed[:50]
        ],
        "contract":{
            "diagnostic_only":True,
            "entry_stop_target_unchanged":"V159",
            "no_grid_search":True,
            "bins_frozen_before_results":True,
            "candidate_selector_for_next_version":"zone_distance_atr <=0.75 AND h4_directional_close_loc <=0.65",
        },
    }

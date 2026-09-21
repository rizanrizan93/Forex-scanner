from __future__ import annotations

from bisect import bisect_right
from datetime import datetime, timezone
from math import isfinite
from typing import Any, Sequence

import numpy as np
import pandas as pd

from .models import Bar, ensure_utc
from .research_xau_hierarchical_regime_router_v35 import _resample_completed, _wilder_atr
from .research_xau_afic_planb_remap_v159 import (
    PathScenario,
    build_scenarios,
    _second_leg_outcome,
)

RESEARCH_VERSION="XAU_AFIC_H4_SELECTOR_DIAGNOSTIC_V160"
ARTIFACT_CONTRACT="XAU_AFIC_H4_SELECTOR_DIAGNOSTIC_V160_EVIDENCE_1"
POLICY_EFFECT="SHADOW_ONLY"
EXECUTION_INFLUENCE=False
PROMOTION_ELIGIBLE=False

ERA_START=datetime(2025,1,1,tzinfo=timezone.utc)
BIN_COUNT=4

FEATURES=(
    "h4_range_atr",
    "h4_body_atr",
    "h4_body_fraction",
    "h4_directional_close_location",
    "h4_rejection_wick_fraction",
    "zone_distance_atr",
    "zone_age_hours",
    "origin_displacement_range_atr",
    "origin_displacement_body_fraction",
)

BOOLEAN_FEATURES=(
    "h4_directional_breakout",
    "h4_body_engulfing",
)


def _h4_feature_table(rows:Sequence[Bar])->pd.DataFrame:
    h4=_resample_completed(rows,"4h").copy()
    h4["atr14"]=_wilder_atr(h4,14)
    return h4.reset_index(drop=True)


def _row_for_time(h4:pd.DataFrame,timestamp)->int|None:
    times=[
        ensure_utc(x.to_pydatetime() if hasattr(x,"to_pydatetime") else x)
        for x in h4["time"]
    ]
    i=bisect_right(times,ensure_utc(timestamp))-1
    return None if i<1 else i


def _features(h4:pd.DataFrame,i:int,s:PathScenario)->dict[str,Any]:
    r=h4.iloc[i];p=h4.iloc[i-1]
    atr=float(r.get("atr14",np.nan))
    if not isfinite(atr) or atr<=0:
        atr=np.nan

    o=float(r["open"]);h=float(r["high"]);l=float(r["low"]);c=float(r["close"])
    po=float(p["open"]);ph=float(p["high"]);pl=float(p["low"]);pc=float(p["close"])
    rng=max(h-l,1e-12)
    body=abs(c-o)
    body_fraction=body/rng
    bullish=s.continuation_direction=="LONG"

    close_loc=(c-l)/rng
    directional_close=close_loc if bullish else 1.0-close_loc

    if bullish:
        rejection_wick=max(0.0,min(o,c)-l)/rng
        breakout=c>ph
        engulf=(c>o and pc<po and o<=pc and c>=po)
        zone_distance=max(0.0,float(s.map_price)-float(s.zone.high))
    else:
        rejection_wick=max(0.0,h-max(o,c))/rng
        breakout=c<pl
        engulf=(c<o and pc>po and o>=pc and c<=po)
        zone_distance=max(0.0,float(s.zone.low)-float(s.map_price))

    return {
        "h4_range_atr":None if not isfinite(atr) else rng/atr,
        "h4_body_atr":None if not isfinite(atr) else body/atr,
        "h4_body_fraction":body_fraction,
        "h4_directional_close_location":directional_close,
        "h4_rejection_wick_fraction":rejection_wick,
        "zone_distance_atr":None if not isfinite(atr) else zone_distance/atr,
        "zone_age_hours":(
            ensure_utc(s.map_at)-ensure_utc(s.zone.available_at)
        ).total_seconds()/3600.0,
        "origin_displacement_range_atr":float(s.zone.displacement_range_atr),
        "origin_displacement_body_fraction":float(s.zone.displacement_body_fraction),
        "h4_directional_breakout":bool(breakout),
        "h4_body_engulfing":bool(engulf),
    }


def _quantile_bins(values,labels,*,bins=BIN_COUNT):
    x=np.asarray(values,dtype=float)
    y=np.asarray(labels,dtype=float)
    ok=np.isfinite(x)
    x=x[ok];y=y[ok]
    if len(x)<bins or len(np.unique(x))<2:
        return []
    qs=np.unique(np.quantile(x,np.linspace(0,1,bins+1)))
    if len(qs)<3:
        return []
    out=[]
    for j in range(len(qs)-1):
        lo=float(qs[j]);hi=float(qs[j+1])
        mask=(x>=lo)&(x<=hi if j==len(qs)-2 else x<hi)
        yy=y[mask]
        out.append({
            "bin":j+1,
            "lo":lo,
            "hi":hi,
            "n":int(mask.sum()),
            "rate":None if len(yy)==0 else float(np.mean(yy)),
        })
    return out


def _point_biserial(values,labels):
    x=np.asarray(values,dtype=float);y=np.asarray(labels,dtype=float)
    ok=np.isfinite(x)
    x=x[ok];y=y[ok]
    if len(x)<3 or len(np.unique(y))<2 or np.std(x)==0:
        return None
    return float(np.corrcoef(x,y)[0,1])


def evaluate_v160(rows:Sequence[Bar],*,evaluation_end)->dict[str,Any]:
    bars=tuple(sorted(rows,key=lambda x:ensure_utc(x.timestamp)))
    end=ensure_utc(evaluation_end)
    h4=_h4_feature_table(bars)
    scenarios=tuple(
        s for s in build_scenarios(bars,evaluation_end=end)
        if ERA_START<=ensure_utc(s.map_at)<end
    )

    records=[]
    for s in scenarios:
        i=_row_for_time(h4,s.map_at)
        if i is None:
            continue
        feats=_features(h4,i,s)
        outcome={
            "first_leg_hit":s.first_touch_at is not None,
            "confirmed":s.primary_status=="CONFIRMED",
            "tp1_after_confirm":False,
            "terminal_after_confirm":False,
        }
        if s.primary_status=="CONFIRMED" and s.confirm_index is not None:
            o=_second_leg_outcome(f=s,bars=bars,confirm_index=int(s.confirm_index))
            outcome["tp1_after_confirm"]=bool(o["tp1_hit"])
            outcome["terminal_after_confirm"]=bool(o["terminal_hit"])
        records.append({"scenario":s,**feats,**outcome})

    targets=("first_leg_hit","confirmed")
    diagnostics={}
    for target in targets:
        labels=[1.0 if r[target] else 0.0 for r in records]
        diagnostics[target]={}
        for feature in FEATURES:
            vals=[np.nan if r[feature] is None else float(r[feature]) for r in records]
            diagnostics[target][feature]={
                "correlation":_point_biserial(vals,labels),
                "quartiles":_quantile_bins(vals,labels),
            }
        for feature in BOOLEAN_FEATURES:
            groups={}
            for flag in (False,True):
                sel=[r for r in records if bool(r[feature]) is flag]
                groups[str(flag).lower()]={
                    "n":len(sel),
                    "rate":None if not sel else sum(bool(r[target]) for r in sel)/len(sel),
                }
            diagnostics[target][feature]={"groups":groups}

    confirmed=[r for r in records if r["confirmed"]]
    tp1_rate=None if not confirmed else sum(r["tp1_after_confirm"] for r in confirmed)/len(confirmed)

    return {
        "research_version":RESEARCH_VERSION,
        "artifact_contract":ARTIFACT_CONTRACT,
        "policy_effect":POLICY_EFFECT,
        "execution_influence":EXECUTION_INFLUENCE,
        "promotion_eligible":PROMOTION_ELIGIBLE,
        "sample":{
            "scenarios":len(records),
            "first_leg_hits":sum(r["first_leg_hit"] for r in records),
            "confirmed":len(confirmed),
            "tp1_after_confirm_rate":tp1_rate,
        },
        "public_material_hypotheses":[
            "H4 close quality matters; AFIC publicly remaps based on H4 close.",
            "Public channel tag/content repeatedly references direction, breakout, pattern, forecast.",
            "V160 diagnoses H4 breakout/body/close-pattern features but does not select thresholds.",
        ],
        "diagnostics":diagnostics,
        "no_reselection":True,
        "note":"Diagnostic only. Use results to preregister a later selector; never promote a feature directly from this same sample.",
    }

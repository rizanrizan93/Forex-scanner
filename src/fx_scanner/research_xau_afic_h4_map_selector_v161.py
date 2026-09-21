from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Sequence

from .models import Bar, ensure_utc
from .research_xau_hierarchical_regime_router_v35 import _resample_completed
from .research_xau_afic_planb_remap_v159 import build_scenarios, _second_leg_outcome
from .research_xau_afic_h4_selector_diagnostic_v160 import _h4_feature_table, _row_for_time, _features

RESEARCH_VERSION="XAU_AFIC_H4_MAP_SELECTOR_V161"
ARTIFACT_CONTRACT="XAU_AFIC_H4_MAP_SELECTOR_V161_EVIDENCE_1"
POLICY_EFFECT="SHADOW_ONLY"
EXECUTION_INFLUENCE=False
PROMOTION_ELIGIBLE=False

PRIMARY_SELECTOR="NEAR_WEAK_H4_CLOSE"
ZONE_DISTANCE_ATR_MAX=0.75
DIRECTIONAL_CLOSE_LOCATION_MAX=0.65
BODY_FRACTION_MAX=0.55

VARIANTS=(
    "NEAR_WEAK_H4_CLOSE",
    "NEAR_WEAK_H4_CLOSE_BODY",
    "NEAR_WEAK_H4_CLOSE_BREAKOUT",
)

WINDOWS=(
    ("2012_2018",datetime(2012,1,1,tzinfo=timezone.utc),datetime(2019,1,1,tzinfo=timezone.utc)),
    ("2019_2024",datetime(2019,1,1,tzinfo=timezone.utc),datetime(2025,1,1,tzinfo=timezone.utc)),
    ("2025",datetime(2025,1,1,tzinfo=timezone.utc),datetime(2026,1,1,tzinfo=timezone.utc)),
    ("2026YTD",datetime(2026,1,1,tzinfo=timezone.utc),datetime(2026,9,20,tzinfo=timezone.utc)),
    ("2025_2026YTD",datetime(2025,1,1,tzinfo=timezone.utc),datetime(2026,9,20,tzinfo=timezone.utc)),
)


def _selected(feats:dict[str,Any],variant:str)->bool:
    dist=feats.get("zone_distance_atr")
    close=feats.get("h4_directional_close_location")
    if dist is None or close is None:
        return False
    base=float(dist)<=ZONE_DISTANCE_ATR_MAX and float(close)<=DIRECTIONAL_CLOSE_LOCATION_MAX
    if not base:
        return False
    if variant=="NEAR_WEAK_H4_CLOSE":
        return True
    if variant=="NEAR_WEAK_H4_CLOSE_BODY":
        return float(feats.get("h4_body_fraction") or 999.0)<=BODY_FRACTION_MAX
    if variant=="NEAR_WEAK_H4_CLOSE_BREAKOUT":
        return bool(feats.get("h4_directional_breakout"))
    raise ValueError(f"V161_UNKNOWN_VARIANT:{variant}")


def _records(rows:Sequence[Bar],evaluation_end):
    bars=tuple(sorted(rows,key=lambda x:ensure_utc(x.timestamp)))
    h4=_h4_feature_table(bars)
    scenarios=build_scenarios(bars,evaluation_end=evaluation_end)
    out=[]
    for s in scenarios:
        i=_row_for_time(h4,s.map_at)
        if i is None:
            continue
        feats=_features(h4,i,s)
        outcome=None
        if s.primary_status=="CONFIRMED" and s.confirm_index is not None:
            outcome=_second_leg_outcome(f=s,bars=bars,confirm_index=int(s.confirm_index))
        out.append((s,feats,outcome))
    return bars,tuple(out)


def _summarize(records,start,end,variant):
    r=[
        x for x in records
        if ensure_utc(start)<=ensure_utc(x[0].map_at)<ensure_utc(end)
        and _selected(x[1],variant)
    ]
    first=[x for x in r if x[0].first_touch_at is not None]
    confirmed=[x for x in r if x[0].primary_status=="CONFIRMED"]
    outcomes=[x[2] for x in confirmed if x[2] is not None]
    return {
        "selector":variant,
        "scenarios":len(r),
        "first_leg_zone_hit_rate":None if not r else len(first)/len(r),
        "zone_confirmation_rate_given_hit":None if not first else len(confirmed)/len(first),
        "confirmed_count":len(confirmed),
        "second_leg_tp1_rate_given_confirm":None if not outcomes else sum(o["tp1_hit"] for o in outcomes)/len(outcomes),
        "second_leg_terminal_rate_given_confirm":None if not outcomes else sum(o["terminal_hit"] for o in outcomes)/len(outcomes),
        "full_sequence_terminal_rate":None if not r else sum(bool(o and o["terminal_hit"]) for _,_,o in r)/len(r),
        "direction_counts":{
            "CONT_LONG":sum(x[0].continuation_direction=="LONG" for x in r),
            "CONT_SHORT":sum(x[0].continuation_direction=="SHORT" for x in r),
        },
    }


def evaluate_v161(rows:Sequence[Bar],*,evaluation_end)->dict[str,Any]:
    end=ensure_utc(evaluation_end)
    _,records=_records(rows,end)
    windows={}
    for label,a,b in WINDOWS:
        bb=min(ensure_utc(b),end)
        if ensure_utc(a)>=bb:
            continue
        windows[label]={v:_summarize(records,a,bb,v) for v in VARIANTS}
    full_start=datetime(2012,1,1,tzinfo=timezone.utc)
    full={v:_summarize(records,full_start,end,v) for v in VARIANTS}
    return {
        "research_version":RESEARCH_VERSION,
        "artifact_contract":ARTIFACT_CONTRACT,
        "policy_effect":POLICY_EFFECT,
        "execution_influence":EXECUTION_INFLUENCE,
        "promotion_eligible":PROMOTION_ELIGIBLE,
        "primary_selector":PRIMARY_SELECTOR,
        "selector_contract":{
            "zone_distance_atr_max":ZONE_DISTANCE_ATR_MAX,
            "directional_close_location_max":DIRECTIONAL_CLOSE_LOCATION_MAX,
            "body_fraction_max_sensitivity":BODY_FRACTION_MAX,
            "rationale":[
                "V160 recent diagnostic: zone distance dominated first-leg reachability.",
                "V160 recent diagnostic: weak/non-extreme directional H4 closes had the highest confirmation frequency.",
                "Public AFIC material explicitly says H4 close can cause forecast remap and describes a 'not pretty' H4 close.",
                "Thresholds are rounded/broad and frozen before V161 cross-era evaluation; primary selector does not require breakout/body tuning.",
            ],
            "primary":"NEAR_WEAK_H4_CLOSE; other variants are sensitivity only",
            "no_same_sample_promotion":True,
        },
        "full":full,
        "windows":windows,
        "note":"V161 is a preregistered cross-era validation of a public-material-informed H4 map selector. It is not execution authority.",
    }

from __future__ import annotations

from bisect import bisect_left
from datetime import datetime, timezone
from typing import Any, Sequence

import pandas as pd

from .models import Bar, ensure_utc
from .research_xau_afic_planb_remap_v159 import (
    build_scenarios,
    _second_leg_outcome,
)
from .research_xau_afic_h4_map_selector_v161 import (
    PRIMARY_SELECTOR,
    _selected,
)
from .research_xau_afic_h4_selector_diagnostic_v160 import (
    _h4_feature_table,
    _row_for_time,
    _features,
)
from .research_xau_afic_public_path_state_v155 import _m15_engulfing_rejection
from .research_xau_afic_displacement_origin_v154 import _zone_stop, _published_round_target

RESEARCH_VERSION="XAU_AFIC_M12_VS_M15_V162"
ARTIFACT_CONTRACT="XAU_AFIC_M12_VS_M15_V162_EVIDENCE_1"
POLICY_EFFECT="SHADOW_ONLY"
EXECUTION_INFLUENCE=False
PROMOTION_ELIGIBLE=False
LIVE_EXECUTION_ENABLED=False

EVAL_START=datetime(2026,1,1,tzinfo=timezone.utc)
FIRST_LEG_HOURS=16
CONFIRM_WINDOW_HOURS=2
SECOND_LEG_HOURS=8


def _frame(rows:Sequence[Bar])->pd.DataFrame:
    return pd.DataFrame([
        {
            "time":pd.Timestamp(ensure_utc(x.timestamp)),
            "open":float(x.open),"high":float(x.high),
            "low":float(x.low),"close":float(x.close),
        } for x in rows
    ]).sort_values("time").reset_index(drop=True)


def resample_bars(rows:Sequence[Bar],*,minutes:int,timeframe:str)->tuple[Bar,...]:
    x=_frame(rows).set_index("time")
    rule=f"{minutes}min"
    y=x.resample(
        rule,label="left",closed="left",origin="start_day"
    ).agg(
        open=("open","first"),
        high=("high","max"),
        low=("low","min"),
        close=("close","last"),
    ).dropna().reset_index()
    return tuple(
        Bar(
            symbol="XAUUSD",timeframe=timeframe,
            timestamp=r.time.to_pydatetime(),
            open=float(r.open),high=float(r.high),
            low=float(r.low),close=float(r.close),
            tick_count=1,spread_avg=0.0,spread_max=0.0,
        )
        for r in y.itertuples(index=False)
    )


def _selected_scenarios(m15:Sequence[Bar],evaluation_end):
    bars=tuple(sorted(m15,key=lambda x:ensure_utc(x.timestamp)))
    scenarios=build_scenarios(bars,evaluation_end=evaluation_end)
    h4=_h4_feature_table(bars)
    out=[]
    for s in scenarios:
        if ensure_utc(s.map_at)<EVAL_START:
            continue
        i=_row_for_time(h4,s.map_at)
        if i is None:
            continue
        feats=_features(h4,i,s)
        if _selected(feats,PRIMARY_SELECTOR):
            out.append((s,feats))
    return bars,tuple(out)


def _m15_record(s,bars):
    confirmed=s.primary_status=="CONFIRMED" and s.confirm_index is not None
    outcome=None
    if confirmed:
        outcome=_second_leg_outcome(f=s,bars=bars,confirm_index=int(s.confirm_index))
    return {
        "map_at":ensure_utc(s.map_at).isoformat(),
        "first_leg_hit":s.first_touch_at is not None,
        "confirmed":confirmed,
        "tp1":None if outcome is None else bool(outcome["tp1_hit"]),
        "terminal":None if outcome is None else bool(outcome["terminal_hit"]),
    }


def _times(rows:Sequence[Bar]):
    return [ensure_utc(x.timestamp) for x in rows]


def _m12_record(s,m12:Sequence[Bar]):
    bars=tuple(m12);times=_times(bars)
    start=bisect_left(times,ensure_utc(s.map_at))
    if start>=len(bars):
        return {
            "map_at":ensure_utc(s.map_at).isoformat(),
            "first_leg_hit":False,"confirmed":False,
            "tp1":None,"terminal":None,"status":"NO_DATA",
        }

    first_leg_bars=int(FIRST_LEG_HOURS*60/12)
    confirm_bars=int(CONFIRM_WINDOW_HOURS*60/12)
    outcome_bars=int(SECOND_LEG_HOURS*60/12)
    end=min(len(bars)-1,start+first_leg_bars)

    touch=None
    invalid=None
    for i in range(start,end+1):
        b=bars[i]
        invalidated=(
            float(b.close)>s.zone.high
            if s.zone.direction=="SHORT"
            else float(b.close)<s.zone.low
        )
        if invalidated:
            invalid=i;break
        touched=float(b.low)<=s.zone.high and float(b.high)>=s.zone.low
        if touched:
            touch=i;break

    if touch is None:
        return {
            "map_at":ensure_utc(s.map_at).isoformat(),
            "first_leg_hit":False,"confirmed":False,
            "tp1":None,"terminal":None,
            "status":"INVALIDATED" if invalid is not None else "FIRST_LEG_TIMEOUT",
        }

    confirm=None
    cend=min(len(bars)-2,touch+confirm_bars)
    for i in range(touch,cend+1):
        b=bars[i]
        invalidated=(
            float(b.close)>s.zone.high
            if s.zone.direction=="SHORT"
            else float(b.close)<s.zone.low
        )
        if invalidated:
            break
        if _m15_engulfing_rejection(bars,i,s.zone):
            confirm=i;break

    if confirm is None:
        return {
            "map_at":ensure_utc(s.map_at).isoformat(),
            "first_leg_hit":True,"confirmed":False,
            "tp1":None,"terminal":None,"status":"ZONE_HIT_NO_CONFIRM",
        }

    entry_i=confirm+1
    if entry_i>=len(bars):
        return {
            "map_at":ensure_utc(s.map_at).isoformat(),
            "first_leg_hit":True,"confirmed":True,
            "tp1":None,"terminal":None,"status":"NO_ENTRY_BAR",
        }

    entry=float(bars[entry_i].open)
    stop=_zone_stop(s.zone)
    target=_published_round_target(entry,stop,s.continuation_direction)
    if target is None:
        return {
            "map_at":ensure_utc(s.map_at).isoformat(),
            "first_leg_hit":True,"confirmed":True,
            "tp1":None,"terminal":None,"status":"NO_TARGET_GEOMETRY",
        }

    _,terminal,ladder=target
    tp1=float(ladder[0])
    max_i=min(len(bars)-1,entry_i+outcome_bars)
    tp1_hit=False
    terminal_hit=False
    for i in range(entry_i,max_i+1):
        b=bars[i]
        if s.continuation_direction=="SHORT":
            stop_hit=float(b.high)>=stop
            hit1=float(b.low)<=tp1
            hit_terminal=float(b.low)<=terminal
        else:
            stop_hit=float(b.low)<=stop
            hit1=float(b.high)>=tp1
            hit_terminal=float(b.high)>=terminal

        # Conservative same-bar ambiguity before TP1.
        if not tp1_hit and stop_hit:
            return {
                "map_at":ensure_utc(s.map_at).isoformat(),
                "first_leg_hit":True,"confirmed":True,
                "tp1":False,"terminal":False,"status":"STOP_BEFORE_TP1",
            }
        if hit1:
            tp1_hit=True
        if hit_terminal:
            terminal_hit=True
            break
        if tp1_hit and stop_hit:
            break

    return {
        "map_at":ensure_utc(s.map_at).isoformat(),
        "first_leg_hit":True,"confirmed":True,
        "tp1":tp1_hit,"terminal":terminal_hit,
        "status":"TERMINAL" if terminal_hit else ("TP1" if tp1_hit else "TIME"),
    }


def _metrics(records):
    n=len(records)
    hit=[x for x in records if x["first_leg_hit"]]
    confirmed=[x for x in records if x["confirmed"]]
    outcomes=[x for x in confirmed if x["tp1"] is not None]
    return {
        "scenarios":n,
        "first_leg_zone_hit_rate":None if not n else len(hit)/n,
        "confirmation_rate_given_hit":None if not hit else len(confirmed)/len(hit),
        "confirmed_count":len(confirmed),
        "outcome_geometry_count":len(outcomes),
        "tp1_rate_given_confirm":None if not outcomes else sum(bool(x["tp1"]) for x in outcomes)/len(outcomes),
        "terminal_rate_given_confirm":None if not outcomes else sum(bool(x["terminal"]) for x in outcomes)/len(outcomes),
    }


def evaluate_v162(m1_rows:Sequence[Bar],*,evaluation_end)->dict[str,Any]:
    end=ensure_utc(evaluation_end)
    m15=resample_bars(m1_rows,minutes=15,timeframe="M15")
    m12=resample_bars(m1_rows,minutes=12,timeframe="M12")
    m15_bars,selected=_selected_scenarios(m15,end)

    r15=[_m15_record(s,m15_bars) for s,_ in selected]
    r12=[_m12_record(s,m12) for s,_ in selected]

    c15={x["map_at"] for x in r15 if x["confirmed"]}
    c12={x["map_at"] for x in r12 if x["confirmed"]}

    return {
        "research_version":RESEARCH_VERSION,
        "artifact_contract":ARTIFACT_CONTRACT,
        "policy_effect":POLICY_EFFECT,
        "execution_influence":EXECUTION_INFLUENCE,
        "promotion_eligible":PROMOTION_ELIGIBLE,
        "live_execution_enabled":LIVE_EXECUTION_ENABLED,
        "evaluation_window":{
            "start":EVAL_START.isoformat(),
            "end":end.isoformat(),
        },
        "selector":"V161 primary NEAR_WEAK_H4_CLOSE; identical map/zone set for both execution timeframes",
        "M15_PUBLIC_CONTROL":_metrics(r15),
        "M12_SCREENSHOT_HYPOTHESIS":_metrics(r12),
        "confirmation_overlap":{
            "both":len(c15 & c12),
            "m15_only":len(c15-c12),
            "m12_only":len(c12-c15),
            "neither":len(selected)-len(c15|c12),
        },
        "contracts":{
            "m12_alignment":"12-minute bars anchored to UTC start-of-day: :00/:12/:24/:36/:48",
            "m15_alignment":"15-minute bars anchored to UTC start-of-day",
            "first_leg_horizon_hours":FIRST_LEG_HOURS,
            "confirm_window_hours":CONFIRM_WINDOW_HOURS,
            "second_leg_horizon_hours":SECOND_LEG_HOURS,
            "same_bar_ambiguity":"STOP_FIRST before TP1",
            "no_threshold_retuning":True,
            "interpretation":"M15 is public-text control; M12 is user-supplied AFIC screenshot hypothesis.",
        },
        "m12_status_counts":{
            k:sum(x["status"]==k for x in r12)
            for k in sorted({x["status"] for x in r12})
        },
    }

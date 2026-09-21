from __future__ import annotations

from bisect import bisect_left
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Sequence

import numpy as np

from .models import Bar, ensure_utc
from .research_xau_hierarchical_regime_router_v35 import _resample_completed
from .research_xau_afic_displacement_origin_v154 import (
    OriginZone,
    _h1_origin_zones,
    _published_round_target,
    _zone_stop,
)
from .research_xau_afic_public_path_state_v155 import _m15_engulfing_rejection

RESEARCH_VERSION="XAU_AFIC_PLANB_REMAP_V159"
ARTIFACT_CONTRACT="XAU_AFIC_PLANB_REMAP_V159_EVIDENCE_1"
POLICY_EFFECT="SHADOW_ONLY"
EXECUTION_INFLUENCE=False
PROMOTION_ELIGIBLE=False
LIVE_EXECUTION_ENABLED=False

ZONE_MAX_AGE_HOURS=24
FIRST_LEG_HORIZON_M15=64   # 16h
CONFIRM_WINDOW_M15=8       # 2h after zone touch
SECOND_LEG_HORIZON_M15=32  # 8h after confirmation

ERA_WINDOWS=(
    ("2012_2018",datetime(2012,1,1,tzinfo=timezone.utc),datetime(2019,1,1,tzinfo=timezone.utc)),
    ("2019_2024",datetime(2019,1,1,tzinfo=timezone.utc),datetime(2025,1,1,tzinfo=timezone.utc)),
    ("2025_2026YTD",datetime(2025,1,1,tzinfo=timezone.utc),datetime(2026,9,20,tzinfo=timezone.utc)),
)


@dataclass(frozen=True)
class PathScenario:
    map_at:datetime
    continuation_direction:str
    first_leg_direction:str
    zone:OriginZone
    map_price:float
    first_touch_at:datetime|None
    first_touch_index:int|None
    confirm_at:datetime|None
    confirm_index:int|None
    entry_at:datetime|None
    entry:float|None
    stop:float|None
    tp1:float|None
    terminal:float|None
    primary_status:str
    failure_at:datetime|None
    failure_reason:str|None
    remap_parent_at:datetime|None

    def payload(self)->dict[str,Any]:
        x=asdict(self)
        for k in ("map_at","first_touch_at","confirm_at","entry_at","failure_at","remap_parent_at"):
            if x[k] is not None:
                x[k]=ensure_utc(x[k]).isoformat()
        x["zone"]["available_at"]=ensure_utc(self.zone.available_at).isoformat()
        x["zone"]["bos_at"]=ensure_utc(self.zone.bos_at).isoformat()
        x["zone"]["origin_at"]=ensure_utc(self.zone.origin_at).isoformat()
        return x


def _bar_times(bars:Sequence[Bar]):
    return [ensure_utc(b.timestamp) for b in bars]


def _index_at_or_after(times,timestamp)->int:
    return bisect_left(times,ensure_utc(timestamp))


def _available_zones(zones:Sequence[OriginZone],timestamp)->tuple[OriginZone,...]:
    t=ensure_utc(timestamp)
    out=[]
    for z in zones:
        at=ensure_utc(z.available_at)
        if at>t:
            continue
        if t-at>timedelta(hours=ZONE_MAX_AGE_HOURS):
            continue
        out.append(z)
    return tuple(out)


def _choose_reaction_zone(
    zones:Sequence[OriginZone],*,timestamp,price:float,h4_direction:str
)->OriginZone|None:
    available=_available_zones(zones,timestamp)

    # AFIC public-path interpretation:
    # bearish H4 close -> expect countertrend BUY/pullback into supply, then SELL;
    # bullish H4 close -> expect countertrend SELL/pullback into demand, then BUY.
    if h4_direction=="SHORT":
        c=[z for z in available if z.direction=="SHORT" and z.low>price]
        return None if not c else min(c,key=lambda z:z.low-price)

    c=[z for z in available if z.direction=="LONG" and z.high<price]
    return None if not c else min(c,key=lambda z:price-z.high)


def _touch(row:Bar,zone:OriginZone)->bool:
    return float(row.low)<=zone.high and float(row.high)>=zone.low


def _zone_invalidated(row:Bar,zone:OriginZone)->bool:
    if zone.direction=="SHORT":
        return float(row.close)>zone.high
    return float(row.close)<zone.low


def _second_leg_outcome(
    *,f:PathScenario,bars:Sequence[Bar],confirm_index:int
)->dict[str,Any]:
    if f.entry is None or f.stop is None or f.tp1 is None or f.terminal is None:
        return {
            "tp1_hit":False,"terminal_hit":False,"stop_hit":False,
            "resolved":"NO_GEOMETRY",
        }

    max_i=min(len(bars)-1,confirm_index+1+SECOND_LEG_HORIZON_M15)
    for j in range(confirm_index+1,max_i+1):
        b=bars[j]
        if f.continuation_direction=="SHORT":
            stop_hit=float(b.high)>=f.stop
            tp1_hit=float(b.low)<=f.tp1
            terminal=float(b.low)<=f.terminal
        else:
            stop_hit=float(b.low)<=f.stop
            tp1_hit=float(b.high)>=f.tp1
            terminal=float(b.high)>=f.terminal

        # Conservative same-bar ambiguity: stop dominates.
        if stop_hit:
            return {"tp1_hit":False,"terminal_hit":False,"stop_hit":True,"resolved":"STOP"}
        if terminal:
            return {"tp1_hit":True,"terminal_hit":True,"stop_hit":False,"resolved":"TERMINAL"}
        if tp1_hit:
            # Keep scanning for terminal but retain TP1 if terminal never arrives.
            for k in range(j+1,max_i+1):
                bb=bars[k]
                if f.continuation_direction=="SHORT":
                    if float(bb.high)>=f.stop:
                        return {"tp1_hit":True,"terminal_hit":False,"stop_hit":False,"resolved":"TP1_THEN_BE_OR_STOP"}
                    if float(bb.low)<=f.terminal:
                        return {"tp1_hit":True,"terminal_hit":True,"stop_hit":False,"resolved":"TERMINAL"}
                else:
                    if float(bb.low)<=f.stop:
                        return {"tp1_hit":True,"terminal_hit":False,"stop_hit":False,"resolved":"TP1_THEN_BE_OR_STOP"}
                    if float(bb.high)>=f.terminal:
                        return {"tp1_hit":True,"terminal_hit":True,"stop_hit":False,"resolved":"TERMINAL"}
            return {"tp1_hit":True,"terminal_hit":False,"stop_hit":False,"resolved":"TP1_ONLY"}

    return {"tp1_hit":False,"terminal_hit":False,"stop_hit":False,"resolved":"TIME"}


def _build_one(
    *,bars:Sequence[Bar],times,zones,h4_row,h4_index:int,remap_parent_at=None
)->PathScenario|None:
    map_at=ensure_utc(h4_row["time"].to_pydatetime() if hasattr(h4_row["time"],"to_pydatetime") else h4_row["time"])
    price=float(h4_row["close"])
    o=float(h4_row["open"]);c=float(h4_row["close"])
    if c==o:
        return None
    continuation="LONG" if c>o else "SHORT"
    first_leg="SHORT" if continuation=="LONG" else "LONG"
    zone=_choose_reaction_zone(zones,timestamp=map_at,price=price,h4_direction=continuation)
    if zone is None:
        return None

    start_i=_index_at_or_after(times,map_at)
    if start_i>=len(bars):
        return None
    end_i=min(len(bars)-1,start_i+FIRST_LEG_HORIZON_M15)

    touch_i=None
    invalid_i=None
    for i in range(start_i,end_i+1):
        b=bars[i]
        if _zone_invalidated(b,zone):
            invalid_i=i
            break
        if _touch(b,zone):
            touch_i=i
            break

    if touch_i is None:
        failure_i=invalid_i if invalid_i is not None else end_i
        return PathScenario(
            map_at,continuation,first_leg,zone,price,
            None,None,None,None,None,None,None,None,None,
            "FAILED",
            ensure_utc(bars[failure_i].timestamp),
            "ZONE_INVALIDATED" if invalid_i is not None else "FIRST_LEG_TIMEOUT",
            remap_parent_at,
        )

    confirm_i=None
    c_end=min(len(bars)-2,touch_i+CONFIRM_WINDOW_M15)
    for i in range(touch_i,c_end+1):
        if _zone_invalidated(bars[i],zone):
            invalid_i=i
            break
        if _m15_engulfing_rejection(bars,i,zone):
            confirm_i=i
            break

    if confirm_i is None:
        failure_i=invalid_i if invalid_i is not None else c_end
        return PathScenario(
            map_at,continuation,first_leg,zone,price,
            ensure_utc(bars[touch_i].timestamp),touch_i,
            None,None,None,None,None,None,None,
            "ZONE_HIT_NO_CONFIRM",
            ensure_utc(bars[failure_i].timestamp),
            "ZONE_INVALIDATED_AFTER_TOUCH" if invalid_i is not None else "CONFIRM_TIMEOUT",
            remap_parent_at,
        )

    entry_i=confirm_i+1
    if entry_i>=len(bars):
        return None
    entry=float(bars[entry_i].open)
    stop=_zone_stop(zone)
    target=_published_round_target(entry,stop,continuation)
    if target is None:
        return PathScenario(
            map_at,continuation,first_leg,zone,price,
            ensure_utc(bars[touch_i].timestamp),touch_i,
            ensure_utc(bars[confirm_i].timestamp),confirm_i,
            ensure_utc(bars[entry_i].timestamp),entry,stop,None,None,
            "CONFIRMED_NO_TARGET_GEOMETRY",
            ensure_utc(bars[entry_i].timestamp),
            "NO_PUBLISHED_TARGET_GEOMETRY",
            remap_parent_at,
        )

    _,terminal,ladder=target
    return PathScenario(
        map_at,continuation,first_leg,zone,price,
        ensure_utc(bars[touch_i].timestamp),touch_i,
        ensure_utc(bars[confirm_i].timestamp),confirm_i,
        ensure_utc(bars[entry_i].timestamp),entry,stop,float(ladder[0]),float(terminal),
        "CONFIRMED",
        None,None,remap_parent_at,
    )


def build_scenarios(rows:Sequence[Bar],*,evaluation_end)->tuple[PathScenario,...]:
    bars=tuple(sorted(rows,key=lambda x:ensure_utc(x.timestamp)))
    times=_bar_times(bars)
    zones=_h1_origin_zones(bars)
    h4=_resample_completed(bars,"4h")
    end=ensure_utc(evaluation_end)

    scenarios=[]
    blocked_until=None
    remap_parent=None

    for hi,(_,row) in enumerate(h4.iterrows()):
        map_at=ensure_utc(row["time"].to_pydatetime() if hasattr(row["time"],"to_pydatetime") else row["time"])
        if map_at>=end:
            break
        if blocked_until is not None and map_at<blocked_until:
            continue

        s=_build_one(
            bars=bars,times=times,zones=zones,h4_row=row,h4_index=hi,
            remap_parent_at=remap_parent,
        )
        if s is None:
            continue
        scenarios.append(s)

        if s.primary_status=="CONFIRMED" and s.confirm_index is not None:
            blocked_i=min(len(bars)-1,s.confirm_index+1+SECOND_LEG_HORIZON_M15)
            blocked_until=ensure_utc(bars[blocked_i].timestamp)
            remap_parent=None
        else:
            # Public AFIC behavior: failed path is remapped only after a fresh
            # completed H4 close. Preserve parent id for scenario-recovery stats.
            failure=s.failure_at or map_at
            blocked_until=failure
            remap_parent=s.map_at

    return tuple(scenarios)


def _summarize(rows:Sequence[Bar],scenarios:Sequence[PathScenario],start,end)->dict[str,Any]:
    bars=tuple(sorted(rows,key=lambda x:ensure_utc(x.timestamp)))
    ss=tuple(s for s in scenarios if ensure_utc(start)<=ensure_utc(s.map_at)<ensure_utc(end))

    first_hit=[s for s in ss if s.first_touch_at is not None]
    confirmed=[s for s in ss if s.primary_status=="CONFIRMED"]

    outcomes=[]
    for s in confirmed:
        outcomes.append((s,_second_leg_outcome(f=s,bars=bars,confirm_index=int(s.confirm_index))))

    remaps=[s for s in ss if s.remap_parent_at is not None]
    remap_first=[s for s in remaps if s.first_touch_at is not None]
    remap_confirm=[s for s in remaps if s.primary_status=="CONFIRMED"]

    full_sequence=[
        (s,o) for s,o in outcomes
        if s.first_touch_at is not None and o["terminal_hit"]
    ]

    return {
        "scenarios":len(ss),
        "first_leg_zone_hit_rate":None if not ss else len(first_hit)/len(ss),
        "zone_confirmation_rate_given_hit":None if not first_hit else len(confirmed)/len(first_hit),
        "second_leg_tp1_rate_given_confirm":None if not outcomes else sum(o["tp1_hit"] for _,o in outcomes)/len(outcomes),
        "second_leg_terminal_rate_given_confirm":None if not outcomes else sum(o["terminal_hit"] for _,o in outcomes)/len(outcomes),
        "full_sequence_terminal_rate":None if not ss else len(full_sequence)/len(ss),
        "primary_failure_rate":None if not ss else sum(s.primary_status!="CONFIRMED" for s in ss)/len(ss),
        "remap_count":len(remaps),
        "remap_first_leg_recovery_rate":None if not remaps else len(remap_first)/len(remaps),
        "remap_confirm_recovery_rate":None if not remaps else len(remap_confirm)/len(remaps),
        "direction_counts":{
            "CONT_LONG":sum(s.continuation_direction=="LONG" for s in ss),
            "CONT_SHORT":sum(s.continuation_direction=="SHORT" for s in ss),
        },
        "status_counts":{
            k:sum(s.primary_status==k for s in ss)
            for k in sorted({s.primary_status for s in ss})
        },
        "examples":[s.payload() for s in ss[:10]],
    }


def evaluate_v159(rows:Sequence[Bar],*,evaluation_end)->dict[str,Any]:
    bars=tuple(sorted(rows,key=lambda x:ensure_utc(x.timestamp)))
    end=ensure_utc(evaluation_end)
    scenarios=build_scenarios(bars,evaluation_end=end)

    full_start=datetime(2012,1,1,tzinfo=timezone.utc)
    full=_summarize(bars,scenarios,full_start,end)
    eras={}
    for label,a,b in ERA_WINDOWS:
        bb=min(ensure_utc(b),end)
        if ensure_utc(a)<bb:
            eras[label]=_summarize(bars,scenarios,a,bb)

    return {
        "research_version":RESEARCH_VERSION,
        "artifact_contract":ARTIFACT_CONTRACT,
        "policy_effect":POLICY_EFFECT,
        "execution_influence":EXECUTION_INFLUENCE,
        "promotion_eligible":PROMOTION_ELIGIBLE,
        "live_execution_enabled":LIVE_EXECUTION_ENABLED,
        "contract":{
            "map_clock":"completed H4 close only",
            "bearish_h4_path":"countertrend first leg up into nearest active H1 supply origin; then M15 bearish engulf/rejection for continuation sell",
            "bullish_h4_path":"countertrend first leg down into nearest active H1 demand origin; then M15 bullish engulf/rejection for continuation buy",
            "zone_max_age_hours":ZONE_MAX_AGE_HOURS,
            "first_leg_horizon":"16h",
            "confirmation_window":"2h after first zone touch",
            "second_leg_horizon":"8h after confirmation",
            "second_leg_target":"frozen V154 psychological-liquidity ladder/terminal",
            "plan_b":"failed primary scenario is remapped only on a later completed H4 close; remap recovery scored separately",
            "forecast_node_not_execution_node":True,
            "no_parameter_grid":True,
            "no_execution_authority":True,
        },
        "full":full,
        "eras":eras,
        "note":"V159 is a path forecast/state-machine test. It does not equate forecast-node accuracy with trade win rate.",
    }

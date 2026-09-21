from __future__ import annotations

from bisect import bisect_left
from datetime import datetime, timezone
from math import isfinite
from typing import Any, Sequence

import numpy as np
import pandas as pd

from .models import Bar, ensure_utc
from .research_xau_afic_displacement_origin_v154 import _published_round_target, _zone_stop
from .research_xau_afic_h4_map_selector_v161 import PRIMARY_SELECTOR
from .research_xau_afic_m12_vs_m15_v162 import (
    resample_bars,
    _selected_scenarios,
)

RESEARCH_VERSION="XAU_AFIC_M12_STOP_GEOMETRY_V163"
ARTIFACT_CONTRACT="XAU_AFIC_M12_STOP_GEOMETRY_V163_EVIDENCE_1"
POLICY_EFFECT="SHADOW_ONLY"
EXECUTION_INFLUENCE=False
PROMOTION_ELIGIBLE=False
LIVE_EXECUTION_ENABLED=False

EVAL_START=datetime(2025,1,1,tzinfo=timezone.utc)
SECOND_LEG_HOURS=8
CONFIRM_WINDOW_HOURS=2
FIRST_LEG_HOURS=16
LOCAL_BUFFER_ATR=0.05

STOP_VARIANTS=(
    "H1_ORIGIN_DISTAL_CONTROL",
    "M12_TOUCH_CONFIRM_EXTREME",
    "M12_CONFIRM_BAR_EXTREME",
    "M12_LOCAL3_EXTREME",
)

WINDOWS=(
    ("2025",datetime(2025,1,1,tzinfo=timezone.utc),datetime(2026,1,1,tzinfo=timezone.utc)),
    ("2026YTD",datetime(2026,1,1,tzinfo=timezone.utc),datetime(2026,9,20,tzinfo=timezone.utc)),
    ("2025_2026YTD",datetime(2025,1,1,tzinfo=timezone.utc),datetime(2026,9,20,tzinfo=timezone.utc)),
)


def _atr14(rows:Sequence[Bar])->list[float]:
    if not rows:
        return []
    high=np.array([float(x.high) for x in rows],dtype=float)
    low=np.array([float(x.low) for x in rows],dtype=float)
    close=np.array([float(x.close) for x in rows],dtype=float)
    prev=np.r_[np.nan,close[:-1]]
    tr=np.nanmax(np.vstack([high-low,np.abs(high-prev),np.abs(low-prev)]),axis=0)
    s=pd.Series(tr)
    return list(s.ewm(alpha=1/14,adjust=False,min_periods=14).mean().to_numpy())


def _touch(row:Bar,zone)->bool:
    return float(row.low)<=float(zone.high) and float(row.high)>=float(zone.low)


def _invalidated(row:Bar,zone)->bool:
    if zone.direction=="SHORT":
        return float(row.close)>float(zone.high)
    return float(row.close)<float(zone.low)


def _engulf_reject(rows:Sequence[Bar],i:int,zone)->bool:
    if i<=0 or not _touch(rows[i],zone):
        return False
    prev=rows[i-1];row=rows[i]
    po,pc=float(prev.open),float(prev.close)
    o,c=float(row.open),float(row.close)
    if zone.direction=="SHORT":
        return bool(pc>po and c<o and o>=pc and c<=po and c<=float(zone.low))
    return bool(pc<po and c>o and o<=pc and c>=po and c>=float(zone.high))


def _collect_confirmations(m15:Sequence[Bar],m12:Sequence[Bar],*,evaluation_end):
    _,selected=_selected_scenarios(m15,evaluation_end)
    m12=tuple(sorted(m12,key=lambda x:ensure_utc(x.timestamp)))
    times=[ensure_utc(x.timestamp) for x in m12]
    atr=_atr14(m12)

    first_leg_bars=int(FIRST_LEG_HOURS*60/12)
    confirm_bars=int(CONFIRM_WINDOW_HOURS*60/12)
    out=[]

    for scenario,_ in selected:
        if ensure_utc(scenario.map_at)<EVAL_START:
            continue
        start=bisect_left(times,ensure_utc(scenario.map_at))
        if start>=len(m12):
            continue

        touch_i=None
        end=min(len(m12)-1,start+first_leg_bars)
        for i in range(start,end+1):
            if _invalidated(m12[i],scenario.zone):
                break
            if _touch(m12[i],scenario.zone):
                touch_i=i
                break
        if touch_i is None:
            continue

        confirm_i=None
        cend=min(len(m12)-2,touch_i+confirm_bars)
        for i in range(touch_i,cend+1):
            if _invalidated(m12[i],scenario.zone):
                break
            if _engulf_reject(m12,i,scenario.zone):
                confirm_i=i
                break
        if confirm_i is None:
            continue

        entry_i=confirm_i+1
        if entry_i>=len(m12):
            continue
        a=atr[confirm_i] if confirm_i<len(atr) else np.nan
        if not isfinite(float(a)) or float(a)<=0:
            continue

        out.append({
            "scenario":scenario,
            "touch_i":touch_i,
            "confirm_i":confirm_i,
            "entry_i":entry_i,
            "entry":float(m12[entry_i].open),
            "atr14":float(a),
            "m12":m12,
        })

    return tuple(out)


def _stop_for(c:dict[str,Any],variant:str)->float:
    s=c["scenario"];rows=c["m12"]
    touch_i=int(c["touch_i"]);confirm_i=int(c["confirm_i"])
    atr=float(c["atr14"])
    buf=LOCAL_BUFFER_ATR*atr

    if variant=="H1_ORIGIN_DISTAL_CONTROL":
        return float(_zone_stop(s.zone))

    if variant=="M12_TOUCH_CONFIRM_EXTREME":
        segment=rows[touch_i:confirm_i+1]
        if s.continuation_direction=="SHORT":
            return max(float(x.high) for x in segment)+buf
        return min(float(x.low) for x in segment)-buf

    if variant=="M12_CONFIRM_BAR_EXTREME":
        b=rows[confirm_i]
        return float(b.high)+buf if s.continuation_direction=="SHORT" else float(b.low)-buf

    if variant=="M12_LOCAL3_EXTREME":
        lo=max(touch_i,confirm_i-2)
        segment=rows[lo:confirm_i+1]
        if s.continuation_direction=="SHORT":
            return max(float(x.high) for x in segment)+buf
        return min(float(x.low) for x in segment)-buf

    raise ValueError(f"V163_UNKNOWN_STOP:{variant}")


def _evaluate(c:dict[str,Any],variant:str)->dict[str,Any]:
    s=c["scenario"];rows=c["m12"]
    entry=float(c["entry"]);entry_i=int(c["entry_i"])
    stop=_stop_for(c,variant)
    sign=1.0 if s.continuation_direction=="LONG" else -1.0
    risk=(entry-stop)*sign
    if risk<=0:
        return {
            "geometry_feasible":False,"reason":"INVALID_STOP_SIDE",
            "risk_usd":abs(entry-stop),"risk_atr":abs(entry-stop)/float(c["atr14"]),
        }

    target=_published_round_target(entry,stop,s.continuation_direction)
    base={
        "geometry_feasible":target is not None,
        "risk_usd":abs(entry-stop),
        "risk_atr":abs(entry-stop)/float(c["atr14"]),
        "entry":entry,
        "stop":stop,
        "direction":s.continuation_direction,
        "map_at":ensure_utc(s.map_at).isoformat(),
        "confirm_at":ensure_utc(rows[int(c["confirm_i"])].timestamp).isoformat(),
    }
    if target is None:
        return base|{"reason":"NO_PUBLISHED_TARGET_GEOMETRY"}

    round_level,terminal,ladder=target
    tp1=float(ladder[0])
    max_i=min(len(rows)-1,entry_i+int(SECOND_LEG_HOURS*60/12))
    tp1_hit=False
    terminal_hit=False
    stop_before_tp1=False
    be_after_tp1=False

    for i in range(entry_i,max_i+1):
        b=rows[i]
        if s.continuation_direction=="SHORT":
            stop_hit=float(b.high)>=stop
            h1=float(b.low)<=tp1
            ht=float(b.low)<=terminal
            be=float(b.high)>=entry
        else:
            stop_hit=float(b.low)<=stop
            h1=float(b.high)>=tp1
            ht=float(b.high)>=terminal
            be=float(b.low)<=entry

        # Conservative same-bar ambiguity before first target.
        if not tp1_hit and stop_hit:
            stop_before_tp1=True
            break
        if h1:
            tp1_hit=True
        if ht:
            terminal_hit=True
            break
        # Once TP1 is reached, AFIC-public management moves runner toward BE.
        if tp1_hit and be:
            be_after_tp1=True
            break

    rr=abs(float(terminal)-entry)/abs(entry-stop)
    return base|{
        "reason":"OK",
        "round_liquidity":float(round_level),
        "tp1":tp1,
        "terminal":float(terminal),
        "published_rr":rr,
        "tp1_hit":tp1_hit,
        "terminal_hit":terminal_hit,
        "stop_before_tp1":stop_before_tp1,
        "be_after_tp1":be_after_tp1,
        "ladder_steps":len(ladder),
    }


def _summarize(rows:list[dict[str,Any]])->dict[str,Any]:
    n=len(rows)
    feasible=[x for x in rows if x.get("geometry_feasible")]
    if not n:
        return {"confirmed":0,"geometry_feasible":0}
    return {
        "confirmed":n,
        "geometry_feasible":len(feasible),
        "geometry_feasible_rate":len(feasible)/n,
        "median_risk_usd":float(np.median([x["risk_usd"] for x in rows])),
        "median_risk_atr":float(np.median([x["risk_atr"] for x in rows])),
        "median_published_rr":None if not feasible else float(np.median([x["published_rr"] for x in feasible])),
        "tp1_hit_rate":None if not feasible else sum(bool(x["tp1_hit"]) for x in feasible)/len(feasible),
        "terminal_hit_rate":None if not feasible else sum(bool(x["terminal_hit"]) for x in feasible)/len(feasible),
        "stop_before_tp1_rate":None if not feasible else sum(bool(x["stop_before_tp1"]) for x in feasible)/len(feasible),
        "be_after_tp1_rate":None if not feasible else sum(bool(x["be_after_tp1"]) for x in feasible)/len(feasible),
    }


def evaluate_v163(m1_rows:Sequence[Bar],*,evaluation_end)->dict[str,Any]:
    end=ensure_utc(evaluation_end)
    m15=resample_bars(m1_rows,minutes=15,timeframe="M15")
    m12=resample_bars(m1_rows,minutes=12,timeframe="M12")
    confirmations=_collect_confirmations(m15,m12,evaluation_end=end)

    details={v:[_evaluate(c,v) for c in confirmations] for v in STOP_VARIANTS}

    windows={}
    for label,start,stop in WINDOWS:
        bb=min(ensure_utc(stop),end)
        if ensure_utc(start)>=bb:
            continue
        windows[label]={}
        for variant,vals in details.items():
            sub=[
                x for x in vals
                if ensure_utc(start)<=datetime.fromisoformat(x["map_at"])<bb
            ]
            windows[label][variant]=_summarize(sub)

    return {
        "research_version":RESEARCH_VERSION,
        "artifact_contract":ARTIFACT_CONTRACT,
        "policy_effect":POLICY_EFFECT,
        "execution_influence":EXECUTION_INFLUENCE,
        "promotion_eligible":PROMOTION_ELIGIBLE,
        "live_execution_enabled":LIVE_EXECUTION_ENABLED,
        "selector":f"V161 {PRIMARY_SELECTOR}",
        "confirmation":"M12 engulf/rejection; identical H4 map/zone set",
        "stop_variants":{
            "H1_ORIGIN_DISTAL_CONTROL":"frozen V154/V162 H1 origin-zone distal stop",
            "M12_TOUCH_CONFIRM_EXTREME":"extreme from first M12 zone touch through M12 confirmation + 0.05 M12 ATR14",
            "M12_CONFIRM_BAR_EXTREME":"confirmation-bar extreme + 0.05 M12 ATR14",
            "M12_LOCAL3_EXTREME":"last up-to-3 M12 bars ending at confirmation + 0.05 M12 ATR14",
        },
        "local_buffer_atr":LOCAL_BUFFER_ATR,
        "windows":windows,
        "confirmation_count":len(confirmations),
        "details":details,
        "interpretation_contract":{
            "diagnostic_only":True,
            "public_afic_exact_sl_formula_known":False,
            "no_stop_variant_promotion_from_same_sample":True,
            "map_zone_confirmation_frozen":True,
            "next_if_local_geometry_plausible":"validate on a larger predeclared historical/forward sample before changing DEMO observer",
        },
    }

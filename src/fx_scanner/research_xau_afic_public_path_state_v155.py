from __future__ import annotations

from bisect import bisect_left
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Sequence

import numpy as np

from .models import Bar, ensure_utc
from .research_xau_hierarchical_regime_router_v35 import _resample_completed
from .research_xau_afic_liquidity_forecast_v152 import (
    Forecast,
    FORECAST_HORIZONS,
    _Asof,
    _PivotAsof,
    _confirmed_pivots,
)
from .research_xau_afic_displacement_origin_v154 import (
    OriginZone,
    _ZoneAsof,
    _h1_origin_zones,
    _h4_location_ok,
    _published_round_target,
    _zone_stop,
    _external_beyond_published,
)

RESEARCH_VERSION="XAU_AFIC_PUBLIC_PATH_STATE_V155"
ARTIFACT_CONTRACT="XAU_AFIC_PUBLIC_PATH_STATE_V155_EVIDENCE_1"
POLICY_EFFECT="SHADOW_ONLY"
EXECUTION_INFLUENCE=False
PROMOTION_ELIGIBLE=False

ZONE_MAX_AGE_HOURS=24
H1_BREAK_WAIT_M15_BARS=16
M15_CONFIRM_WAIT_BARS=8

VARIANTS=(
    "PUBLIC_SHORT_M15_ENGULF",
    "MIRROR_BIDIR_M15_ENGULF",
    "MIRROR_BIDIR_H1_BREAK",
    "MIRROR_BIDIR_H1_BREAK_EXTERNAL",
)

ERA_WINDOWS=(
    ("2012_2018",datetime(2012,1,1,tzinfo=timezone.utc),datetime(2019,1,1,tzinfo=timezone.utc)),
    ("2019_2024",datetime(2019,1,1,tzinfo=timezone.utc),datetime(2025,1,1,tzinfo=timezone.utc)),
    ("2025_2026YTD",datetime(2025,1,1,tzinfo=timezone.utc),datetime(2026,9,20,tzinfo=timezone.utc)),
)

PUBLIC_EVIDENCE=(
    "H4 close is used to update/remap forecast",
    "forecast zone can be liquidity before continuation",
    "do not enter immediately at target zone; wait for confirmation",
    "monitor confirmation on M15",
    "bearish engulfing after rejection is cited as strong seller confirmation",
    "H1 breakdown is cited as strengthening sell continuation",
    "after profit, take some layers and move upper sell layer to BE",
    "failed setup can switch to alternate plans rather than forcing the original path",
)

LOCKED_PROSPECTIVE_FIXTURE={
    "reference_zone":[4323.05,4328.64],
    "first_liquidity":4304.55,
    "reaction_supply":[4350.24,4359.0],
    "bearish_invalidation":[4368.0,4373.0],
    "downside_objective":4290.0,
    "deep_demand":[4257.30,4275.05],
    "path":[
        "4323-4328 reference",
        "4304.55 liquidity/sweep",
        "4350.24-4359 reaction supply",
        "~4290 downside objective",
        "4275.05-4257.30 deep demand if continuation persists",
    ],
    "status":"locked before subsequent path; fixture is evaluation evidence, not a fitted threshold",
}


@dataclass(frozen=True)
class PublicCandidate:
    direction:str
    zone:OriginZone
    confirm_at:datetime
    confirm_index:int
    h1_break_level:float|None
    h1_break_at:datetime|None
    h1_break_index:int|None
    external_ok:bool
    external_source:str|None
    external_price:float|None


def _touches_zone(row:Bar,zone:OriginZone)->bool:
    return float(row.low)<=zone.high and float(row.high)>=zone.low


def _m15_engulfing_rejection(rows:Sequence[Bar],i:int,zone:OriginZone)->bool:
    if i<=0:
        return False
    row=rows[i];prev=rows[i-1]
    if not _touches_zone(row,zone):
        return False

    po,pc=float(prev.open),float(prev.close)
    o,c=float(row.open),float(row.close)

    if zone.direction=="SHORT":
        prev_bull=pc>po
        current_bear=c<o
        engulf=o>=pc and c<=po
        rejected=c<=zone.low
        return bool(prev_bull and current_bear and engulf and rejected)

    prev_bear=pc<po
    current_bull=c>o
    engulf=o<=pc and c>=po
    rejected=c>=zone.high
    return bool(prev_bear and current_bull and engulf and rejected)


def _latest_h1_break_level(h1p:_PivotAsof,timestamp,direction:str)->float|None:
    available=h1p.available(timestamp)
    if direction=="SHORT":
        lows=[x.price for x in available if x.kind=="LOW"]
        return None if not lows else float(lows[-1])
    highs=[x.price for x in available if x.kind=="HIGH"]
    return None if not highs else float(highs[-1])


def _find_h1_break(
    *,bars:Sequence[Bar],h1,confirm_at:datetime,confirm_index:int,
    direction:str,level:float|None,
)->tuple[datetime|None,int|None]:
    if level is None:
        return None,None

    h1_rows=h1[h1["time"]>confirm_at]
    limit=ensure_utc(bars[min(len(bars)-1,confirm_index+H1_BREAK_WAIT_M15_BARS)].timestamp)
    for _,row in h1_rows.iterrows():
        t=ensure_utc(row["time"].to_pydatetime() if hasattr(row["time"],"to_pydatetime") else row["time"])
        if t>limit:
            break
        close=float(row["close"])
        passed=(direction=="SHORT" and close<level) or (direction=="LONG" and close>level)
        if not passed:
            continue
        times=[ensure_utc(x.timestamp) for x in bars]
        idx=bisect_left(times,t)
        if idx>=len(bars):
            return None,None
        return t,idx
    return None,None


def _candidate_stream(rows:Sequence[Bar],*,evaluation_end)->tuple[PublicCandidate,...]:
    bars=tuple(sorted(rows,key=lambda x:ensure_utc(x.timestamp)))
    end=ensure_utc(evaluation_end)
    zones=_ZoneAsof(_h1_origin_zones(bars))

    h4=_resample_completed(bars,"4h")
    h4p=_PivotAsof(_confirmed_pivots(h4))
    h1=_resample_completed(bars,"1h")
    h1p=_PivotAsof(_confirmed_pivots(h1))
    daily=_resample_completed(bars,"1D")
    weekly=_resample_completed(bars,"W-SUN")
    daily_lookup=_Asof(daily);weekly_lookup=_Asof(weekly)

    out=[]
    seen_zone_confirm=set()

    for i,row in enumerate(bars[:-1]):
        t=ensure_utc(row.timestamp)
        if t>=end:
            break
        zone=zones.latest(t)
        if zone is None:
            continue
        age=t-ensure_utc(zone.available_at)
        if age<timedelta(0) or age>timedelta(hours=ZONE_MAX_AGE_HOURS):
            continue
        hp4=h4p.available(t)
        if not _h4_location_ok(float(row.close),zone.direction,hp4):
            continue
        if not _m15_engulfing_rejection(bars,i,zone):
            continue

        key=(ensure_utc(zone.origin_at),zone.direction)
        if key in seen_zone_confirm:
            continue
        seen_zone_confirm.add(key)

        level=_latest_h1_break_level(h1p,t,zone.direction)
        h1_break_at,h1_break_idx=_find_h1_break(
            bars=bars,h1=h1,confirm_at=t,confirm_index=i,
            direction=zone.direction,level=level,
        )

        dl=daily_lookup.row(t);wl=weekly_lookup.row(t)
        provisional_entry=float(bars[i+1].open)
        stop=_zone_stop(zone)
        target=_published_round_target(provisional_entry,stop,zone.direction)
        ext_ok=False;ext_src=None;ext_px=None
        if target is not None:
            _,published,_=target
            ext_ok,ext_src,ext_px=_external_beyond_published(
                entry=provisional_entry,published=published,direction=zone.direction,
                h4_pivots=hp4,daily=dl,weekly=wl,
            )

        out.append(
            PublicCandidate(
                direction=zone.direction,
                zone=zone,
                confirm_at=t,
                confirm_index=i,
                h1_break_level=level,
                h1_break_at=h1_break_at,
                h1_break_index=h1_break_idx,
                external_ok=bool(ext_ok),
                external_source=ext_src,
                external_price=ext_px,
            )
        )
    return tuple(out)


def _forecast_from_candidate(
    bars:Sequence[Bar],candidate:PublicCandidate,*,variant:str
)->Forecast|None:
    if variant=="PUBLIC_SHORT_M15_ENGULF" and candidate.direction!="SHORT":
        return None
    if variant=="MIRROR_BIDIR_H1_BREAK_EXTERNAL" and not candidate.external_ok:
        return None

    use_h1_break=variant in {"MIRROR_BIDIR_H1_BREAK","MIRROR_BIDIR_H1_BREAK_EXTERNAL"}
    if use_h1_break:
        if candidate.h1_break_index is None:
            return None
        entry_index=int(candidate.h1_break_index)
        signal_at=ensure_utc(candidate.h1_break_at)
    else:
        entry_index=candidate.confirm_index+1
        signal_at=ensure_utc(candidate.confirm_at)

    if entry_index>=len(bars):
        return None
    entry_at=ensure_utc(bars[entry_index].timestamp)
    entry=float(bars[entry_index].open)
    stop=_zone_stop(candidate.zone)
    target=_published_round_target(entry,stop,candidate.direction)
    if target is None:
        return None
    round_level,published,ladder=target

    source=f"PUBLIC_AFIC|ROUND_{round_level:g}"
    if candidate.external_source is not None:
        source+=f"|EXT_{candidate.external_source}_{candidate.external_price:g}|OK_{int(candidate.external_ok)}"
    if use_h1_break:
        source+="|H1_BREAK_AUTH"
    else:
        source+="|M15_ENGULF_AUTH"

    return Forecast(
        variant=variant,
        direction=candidate.direction,
        signal_at=signal_at,
        entry_at=entry_at,
        entry=entry,
        stop=stop,
        terminal_target=published,
        terminal_source=source,
        ladder=ladder,
        d1_side=0,
        h4_side=0,
        h1_side=1 if candidate.direction=="LONG" else -1,
        dealing_location="H4_LOCATION+ORIGIN_ZONE",
        m15_sweep=True,
    )


def build_forecasts(rows:Sequence[Bar],*,variant:str,evaluation_end)->tuple[Forecast,...]:
    if variant not in VARIANTS:
        raise ValueError("V155_UNKNOWN_VARIANT")
    bars=tuple(sorted(rows,key=lambda x:ensure_utc(x.timestamp)))
    candidates=_candidate_stream(bars,evaluation_end=evaluation_end)
    raw=[]
    for c in candidates:
        f=_forecast_from_candidate(bars,c,variant=variant)
        if f is not None:
            raw.append(f)

    # Public channel behavior is one active scenario/route at a time. A new
    # forecast is allowed only after stop/terminal/16h timeout of prior one.
    accepted=[]
    blocked_until_index=-1
    by_time={ensure_utc(b.timestamp):i for i,b in enumerate(bars)}
    for f in sorted(raw,key=lambda x:ensure_utc(x.entry_at)):
        idx=by_time.get(ensure_utc(f.entry_at))
        if idx is None or idx<=blocked_until_index:
            continue
        accepted.append(f)
        end_idx=min(len(bars)-1,idx+max(FORECAST_HORIZONS))
        for j in range(idx,end_idx+1):
            b=bars[j]
            if f.direction=="LONG":
                resolved=float(b.low)<=f.stop or float(b.high)>=f.terminal_target
            else:
                resolved=float(b.high)>=f.stop or float(b.low)<=f.terminal_target
            if resolved:
                end_idx=j
                break
        blocked_until_index=end_idx
    return tuple(accepted)


def _management_eval(f:Forecast,bars:Sequence[Bar],entry_index:int,horizon:int)->dict[str,Any]:
    max_i=min(len(bars)-1,entry_index+horizon)
    tp1=float(f.ladder[0])
    tp1_at=None
    stop_before_tp1=False
    be_after_tp1=False
    terminal_after_tp1=False

    for j in range(entry_index,max_i+1):
        b=bars[j]
        if f.direction=="LONG":
            stop_hit=float(b.low)<=f.stop
            tp1_hit=float(b.high)>=tp1
        else:
            stop_hit=float(b.high)>=f.stop
            tp1_hit=float(b.low)<=tp1

        # Conservative ambiguity before TP1.
        if tp1_at is None:
            if stop_hit:
                stop_before_tp1=True
                break
            if tp1_hit:
                tp1_at=j
                continue
        else:
            if f.direction=="LONG":
                terminal=float(b.high)>=f.terminal_target
                be=float(b.low)<=f.entry
            else:
                terminal=float(b.low)<=f.terminal_target
                be=float(b.high)>=f.entry
            # After partial, runner BE is conservative before terminal if same bar.
            if be:
                be_after_tp1=True
                break
            if terminal:
                terminal_after_tp1=True
                break

    return {
        "tp1_hit":tp1_at is not None,
        "stop_before_tp1":stop_before_tp1,
        "be_after_tp1":be_after_tp1,
        "terminal_after_tp1":terminal_after_tp1,
    }


def _summarize(rows:Sequence[Bar],forecasts:Sequence[Forecast],start,end)->dict[str,Any]:
    bars=tuple(sorted(rows,key=lambda x:ensure_utc(x.timestamp)))
    by_time={ensure_utc(b.timestamp):i for i,b in enumerate(bars)}
    fs=tuple(f for f in forecasts if ensure_utc(start)<=ensure_utc(f.entry_at)<ensure_utc(end))
    horizons={}

    for h in FORECAST_HORIZONS:
        evals=[]
        for f in fs:
            idx=by_time.get(ensure_utc(f.entry_at))
            if idx is not None:
                evals.append((f,_management_eval(f,bars,idx,h)))
        n=len(evals)
        by_direction={}
        for side in ("LONG","SHORT"):
            e=[x for f,x in evals if f.direction==side]
            by_direction[side]={
                "n":len(e),
                "tp1_hit_rate":None if not e else sum(x["tp1_hit"] for x in e)/len(e),
                "stop_before_tp1_rate":None if not e else sum(x["stop_before_tp1"] for x in e)/len(e),
                "runner_be_rate_after_tp1":None if not e else sum(x["be_after_tp1"] for x in e)/len(e),
                "runner_terminal_rate_after_tp1":None if not e else sum(x["terminal_after_tp1"] for x in e)/len(e),
            }

        horizons[str(h)]={
            "n":n,
            "tp1_hit_rate":None if n==0 else sum(x["tp1_hit"] for _,x in evals)/n,
            "stop_before_tp1_rate":None if n==0 else sum(x["stop_before_tp1"] for _,x in evals)/n,
            "runner_be_rate_after_tp1":None if n==0 else sum(x["be_after_tp1"] for _,x in evals)/n,
            "runner_terminal_rate_after_tp1":None if n==0 else sum(x["terminal_after_tp1"] for _,x in evals)/n,
            "median_published_rr":None if n==0 else float(np.median([
                abs(f.terminal_target-f.entry)/abs(f.entry-f.stop) for f,_ in evals
            ])),
            "direction":by_direction,
        }

    return {
        "forecasts":len(fs),
        "direction_counts":{
            "LONG":sum(f.direction=="LONG" for f in fs),
            "SHORT":sum(f.direction=="SHORT" for f in fs),
        },
        "h1_break_authorized":sum("H1_BREAK_AUTH" in f.terminal_source for f in fs),
        "external_confirmed":sum("|OK_1" in f.terminal_source for f in fs),
        "horizons":horizons,
        "examples":[{
            "direction":f.direction,
            "signal_at":ensure_utc(f.signal_at).isoformat(),
            "entry_at":ensure_utc(f.entry_at).isoformat(),
            "entry":f.entry,
            "stop":f.stop,
            "tp1":f.ladder[0],
            "terminal":f.terminal_target,
            "source":f.terminal_source,
        } for f in fs[:12]],
    }


def evaluate_v155(rows:Sequence[Bar],*,evaluation_end)->dict[str,Any]:
    bars=tuple(sorted(rows,key=lambda x:ensure_utc(x.timestamp)))
    end=ensure_utc(evaluation_end)
    streams={v:build_forecasts(bars,variant=v,evaluation_end=end) for v in VARIANTS}

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
        "public_evidence":list(PUBLIC_EVIDENCE),
        "locked_prospective_fixture":LOCKED_PROSPECTIVE_FIXTURE,
        "contract":{
            "map":"H4 is scenario/remap context; H4 premium/discount required",
            "zone":"frozen V154 causal displacement-origin zone",
            "entry_confirmation":"M15 directional engulfing after touching/rejecting the zone",
            "continuation_confirmation":"H1 break of latest confirmed swing tested as separate authorization variant",
            "short_exact_vs_long_inference":"bearish engulfing + H1 breakdown are public exact examples; LONG is a mirrored research inference",
            "target":"frozen V154 psychological-liquidity target geometry",
            "management":"after TP1 partial, runner stop modeled at BE; same-bar BE beats terminal",
            "scenario_lifecycle":"only one forecast active until stop/terminal/16h timeout",
            "h1_break_wait_m15_bars":H1_BREAK_WAIT_M15_BARS,
            "forecast_horizons_m15_bars":list(FORECAST_HORIZONS),
            "no_parameter_grid":True,
            "no_execution_authority":True,
        },
        "full":full,
        "eras":eras,
        "note":"V155 encodes public AFIC process statements as a state machine and keeps mirrored LONG logic explicitly separate from the exact public bearish examples.",
    }

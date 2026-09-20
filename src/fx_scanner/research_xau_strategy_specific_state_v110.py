from __future__ import annotations

from bisect import bisect_left, bisect_right
from datetime import datetime, time
from typing import Any, Mapping, Sequence

import pandas as pd

from .demo_donchian_adaptive_tournament import TournamentTrade, compute_metrics
from .models import Bar, ensure_utc
from .research_xau_100usd_stopout_v23 import _cash_path_stopout_safe
from .research_xau_changepoint_reset_router_v87 import (
    MIN_COMPLETED_TRADES,
    _date_cutoff,
    _trailing_health,
    build_regime_feature_frame,
    detect_change_points,
)
from .research_xau_era_robustness_v31 import _dedupe_with_classic
from .research_xau_margin_leverage_v21 import LeverageTier
from .research_xau_multihorizon_100usd_v20 import BrokerLotSpec, _limit_concurrency, _trading_dates
from .research_xau_m15_dual_strategy import M15ResearchCosts
from .research_xau_causal_era_selector_v98 import (
    ACCOUNT_LEVERAGE,
    MARGIN_FLOOR_PCT,
    SATELLITES,
    _strategy_streams,
)
from .research_xau_m15_exceptional_expansion_audit_v109 import build_exceptional_frame
from .research_xau_recency_witness_era_selector_v105 import _witness_cutoff
from .research_xau_stale_reentry_probation_v106 import (
    PROBATION_COMPLETIONS_REQUIRED,
    gate_with_stale_reentry_probation,
)

RESEARCH_VERSION="XAU_STRATEGY_SPECIFIC_STATE_V110"
ARTIFACT_CONTRACT="XAU_STRATEGY_SPECIFIC_STATE_V110_EVIDENCE_1"
POLICY_EFFECT="SHADOW_ONLY"
EXECUTION_INFLUENCE=False
PROMOTION_ELIGIBLE=False
M15_STRATEGIES=("M15_L12","M15_L20")


class _Asof:
    def __init__(self,frame):
        self.frame=frame.reset_index(drop=True)
        self.times=[ensure_utc(x) for x in self.frame["available_at"]]
    def row(self,timestamp):
        i=bisect_right(self.times,ensure_utc(timestamp))-1
        if i<0:return None
        return self.frame.iloc[i].to_dict()


def _period(trades:Sequence[TournamentTrade],a,b)->tuple[TournamentTrade,...]:
    aa=ensure_utc(a);bb=ensure_utc(b)
    return tuple(t for t in trades if aa<=ensure_utc(t.entry_at)<bb)


def _metrics(trades)->dict[str,Any]:
    return compute_metrics(tuple(trades)).payload()


def _extreme_label(row:Mapping[str,Any]|None)->str|None:
    if row is None or not bool(row.get("unanimous_extreme_expansion")):
        return None
    state=str(row.get("state") or "")
    if state=="BULL_EXPANSION":return "BULL_UNANIMOUS_EXTREME"
    if state=="BEAR_EXPANSION":return "BEAR_UNANIMOUS_EXTREME"
    return None


def _direction_matches(label:str|None,direction:str)->bool:
    d=str(direction).upper()
    return (label=="BULL_UNANIMOUS_EXTREME" and d=="LONG") or (label=="BEAR_UNANIMOUS_EXTREME" and d=="SHORT")


def gate_m15_exceptional_health(
    strategy_name:str,
    trades:Sequence[TournamentTrade],*,exceptional_frame,
    trading_dates:Sequence[Any],change_points:Sequence[Mapping[str,Any]],
)->tuple[tuple[TournamentTrade,...],dict[str,Any]]:
    lookup=_Asof(exceptional_frame)
    ordered=tuple(sorted(trades,key=lambda t:ensure_utc(t.signal_at)))
    if not ordered:
        return (),{"candidate_trades":0,"kept_trades":0,"tier_counts":{}}

    label_by_id={}
    for t in ordered:
        label_by_id[id(t)]=_extreme_label(lookup.row(t.signal_at))

    ordered_exit=tuple(sorted(ordered,key=lambda t:ensure_utc(t.exit_at)))
    exit_times=tuple(ensure_utc(t.exit_at) for t in ordered_exit)
    cp_times=tuple(ensure_utc(pd.Timestamp(x["effective_at"]).to_pydatetime()) for x in change_points)
    first_date=trading_dates[0] if trading_dates else ensure_utc(ordered[0].signal_at).date()
    first_epoch=datetime.combine(first_date,time.min,tzinfo=ensure_utc(ordered[0].signal_at).tzinfo)

    kept=[]
    probation_start={}
    tier_counts={}
    state_checks={}
    probation_events=[]
    last_decision={}

    for trade in ordered:
        signal=ensure_utc(trade.signal_at)
        label=label_by_id[id(trade)]
        if label is None or not _direction_matches(label,trade.direction):
            continue

        cp_pos=bisect_right(cp_times,signal)
        epoch_start=first_epoch if cp_pos==0 else cp_times[cp_pos-1]
        rolling_date=_date_cutoff(signal,trading_dates)
        rolling_start=datetime.combine(rolling_date,time.min,tzinfo=signal.tzinfo)
        recent_start=max(epoch_start,rolling_start)

        completed_end=bisect_left(exit_times,signal)
        completed=ordered_exit[:completed_end]

        exact_recent=[
            x for x in completed
            if ensure_utc(x.exit_at)>=recent_start
            and label_by_id[id(x)]==label
            and _direction_matches(label,x.direction)
        ]
        exact_epoch=[
            x for x in completed
            if ensure_utc(x.exit_at)>=epoch_start
            and label_by_id[id(x)]==label
            and _direction_matches(label,x.direction)
        ]

        tier="OFF_INSUFFICIENT";history=()
        witness_cutoff=_witness_cutoff(signal,trading_dates)
        last_exact_exit=None if not exact_epoch else ensure_utc(exact_epoch[-1].exit_at)
        pkey=(epoch_start.isoformat(),label)
        probation_completed=0

        if len(exact_recent)>=MIN_COMPLETED_TRADES:
            tier="EXACT_RECENT"
            history=tuple(exact_recent)
        elif len(exact_epoch)>=MIN_COMPLETED_TRADES:
            fresh=last_exact_exit is not None and last_exact_exit.date()>=witness_cutoff
            if fresh:
                tier="EXACT_EPOCH_FRESH"
                history=tuple(exact_epoch)
            else:
                if pkey not in probation_start:
                    probation_start[pkey]=signal
                    probation_events.append({
                        "strategy":strategy_name,
                        "label":label,
                        "epoch_start":epoch_start.isoformat(),
                        "probation_started_at":signal.isoformat(),
                    })
                pstart=ensure_utc(probation_start[pkey])
                trial_completed=[
                    x for x in exact_epoch
                    if ensure_utc(x.signal_at)>=pstart
                    and ensure_utc(x.exit_at)<signal
                    and label_by_id[id(x)]==label
                    and _direction_matches(label,x.direction)
                ]
                probation_completed=len(trial_completed)
                if probation_completed>=PROBATION_COMPLETIONS_REQUIRED:
                    tier="EXACT_EPOCH_AFTER_PROBATION"
                    history=tuple(exact_epoch)
                else:
                    tier="PROBATION_STALE_REENTRY"

        health=_trailing_health(history)
        tier_counts[tier]=tier_counts.get(tier,0)+1
        st=state_checks.setdefault(label,{"checks":0,"kept":0})
        st["checks"]+=1
        last_decision[label]={
            "tier":tier,
            "completed_trades":health["completed_trades"],
            "profit_factor":health["profit_factor"],
            "expectancy_r":health["expectancy_r"],
            "active":health["active"],
            "last_exact_exit":None if last_exact_exit is None else last_exact_exit.isoformat(),
            "probation_completed":probation_completed,
        }
        if health["active"]:
            kept.append(trade)
            st["kept"]+=1

    return tuple(kept),{
        "strategy":strategy_name,
        "state_abstraction":"direction-matched unanimous extreme expansion",
        "candidate_trades":len(ordered),
        "kept_trades":len(kept),
        "tier_counts":tier_counts,
        "state_checks":state_checks,
        "probation_events":probation_events,
        "last_decision_by_state":last_decision,
        "health_thresholds":"frozen V40/V47",
        "minimum_completed_trades":MIN_COMPLETED_TRADES,
        "stale_reentry_probation":True,
        "broad_fallback_allowed":False,
    }


def _selected_by_strategy_era(selected:Mapping[str,Sequence[TournamentTrade]],a,b)->dict[str,Any]:
    return {name:_metrics(_period(trades,a,b)) for name,trades in selected.items()}


def evaluate_v110(
    bars:Sequence[Bar],*,evaluation_start,evaluation_end,pip_size:float,costs:M15ResearchCosts,
    broker_spec:BrokerLotSpec,leverage_tiers:Sequence[LeverageTier],
    era_windows:Mapping[str,tuple[Any,Any]],
)->dict[str,Any]:
    rows=tuple(sorted(bars,key=lambda x:ensure_utc(x.timestamp)))
    start=ensure_utc(evaluation_start);end=ensure_utc(evaluation_end)
    exceptional=build_exceptional_frame(rows)
    change_points=detect_change_points(build_regime_feature_frame(rows))
    dates=_trading_dates(rows,start=ensure_utc(rows[0].timestamp),end=end)
    streams=_strategy_streams(rows,costs=costs,pip_size=pip_size)

    selected={};gates={}
    from .research_xau_expansion_species_v99 import build_species_frame
    species=build_species_frame(rows)
    selected["D1_STAGGERED"],gates["D1_STAGGERED"]=gate_with_stale_reentry_probation(
        "D1_STAGGERED",streams["D1_STAGGERED"],species_frame=species,trading_dates=dates,change_points=change_points
    )

    for name in M15_STRATEGIES:
        selected[name],gates[name]=gate_m15_exceptional_health(
            name,streams[name],exceptional_frame=exceptional,trading_dates=dates,change_points=change_points
        )

    core=tuple(t for t in streams["D1_CLASSIC"] if start<=ensure_utc(t.entry_at)<end)
    sats=tuple(t for name in SATELLITES for t in selected[name] if start<=ensure_utc(t.entry_at)<end)
    selector=_limit_concurrency(_dedupe_with_classic((*core,*sats)))

    era_out={}
    for era,(a,b) in era_windows.items():
        aa=ensure_utc(a);bb=ensure_utc(b)
        edates=_trading_dates(rows,start=aa,end=bb)
        core_e=_period(core,aa,bb)
        sel_e=_period(selector,aa,bb)
        era_out[era]={
            "core":_metrics(core_e),
            "selector":_metrics(sel_e),
            "selected_strategy_contribution":_selected_by_strategy_era(selected,aa,bb),
            "cash_fresh_100":{
                "core":_cash_path_stopout_safe(core_e,spec=broker_spec,tiers=leverage_tiers,account_leverage=ACCOUNT_LEVERAGE,stopout_pct=MARGIN_FLOOR_PCT,trading_dates=edates),
                "selector":_cash_path_stopout_safe(sel_e,spec=broker_spec,tiers=leverage_tiers,account_leverage=ACCOUNT_LEVERAGE,stopout_pct=MARGIN_FLOOR_PCT,trading_dates=edates),
            },
        }

    return {
        "research_version":RESEARCH_VERSION,
        "artifact_contract":ARTIFACT_CONTRACT,
        "policy_effect":POLICY_EFFECT,
        "execution_influence":EXECUTION_INFLUENCE,
        "promotion_eligible":PROMOTION_ELIGIBLE,
        "live_execution_enabled":False,
        "contract":{
            "D1_STAGGERED_state":"V106 structural/shock species + stale re-entry probation",
            "M15_state":"direction-matched unanimous extreme expansion",
            "M15_threshold":"all four frozen V98 ranks individually >= same 75th percentile",
            "new_numeric_threshold":False,
            "health_thresholds_unchanged":True,
            "V87_change_point_reset":True,
            "calendar_year_used":False,
            "threshold_grid_search":False,
        },
        "change_points":list(change_points),
        "strategy_state_gates":gates,
        "full_period":{"core":_metrics(core),"selector":_metrics(selector)},
        "eras":era_out,
        "note":"V110 assigns state abstractions by strategy family: D1 retains V106 structural/shock routing, while M15 L12/L20 use the stricter unanimous-extreme state discovered in V109, with the same causal health and stale-evidence controls.",
    }

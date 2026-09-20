from __future__ import annotations

from bisect import bisect_left, bisect_right
from datetime import datetime, time
from typing import Any, Mapping, Sequence

import pandas as pd

from .demo_donchian_adaptive_tournament import TournamentTrade, compute_metrics
from .models import Bar, ensure_utc
from .research_xau_100usd_stopout_v23 import _cash_path_stopout_safe
from .research_xau_changepoint_reset_router_v87 import (
    LOOKBACK_TRADING_DAYS,
    MIN_COMPLETED_TRADES,
    _date_cutoff,
    _trailing_health,
    detect_change_points,
)
from .research_xau_era_fingerprint_v97 import build_fingerprint_frame
from .research_xau_era_robustness_v31 import _dedupe_with_classic
from .research_xau_expansion_species_v99 import build_species_frame
from .research_xau_margin_leverage_v21 import LeverageTier
from .research_xau_multihorizon_100usd_v20 import BrokerLotSpec, _limit_concurrency, _trading_dates
from .research_xau_m15_dual_strategy import M15ResearchCosts
from .research_xau_causal_era_selector_v98 import (
    ACCOUNT_LEVERAGE,
    MARGIN_FLOOR_PCT,
    SATELLITES,
    _strategy_streams,
)

RESEARCH_VERSION="XAU_STATE_STRATEGY_MATRIX_V101"
ARTIFACT_CONTRACT="XAU_STATE_STRATEGY_MATRIX_V101_EVIDENCE_1"
POLICY_EFFECT="SHADOW_ONLY"
EXECUTION_INFLUENCE=False
PROMOTION_ELIGIBLE=False

EXPANSION_SPECIES=(
    "BULL_STRUCTURAL_EXPANSION",
    "BULL_SHOCK_EXPANSION",
    "BEAR_STRUCTURAL_EXPANSION",
    "BEAR_SHOCK_EXPANSION",
)


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


def _species_side(species:str)->str|None:
    if species.startswith("BULL_"): return "LONG"
    if species.startswith("BEAR_"): return "SHORT"
    return None


def _broad_expansion(species:str)->str|None:
    if species.startswith("BULL_") and species.endswith("_EXPANSION"): return "BULL_EXPANSION"
    if species.startswith("BEAR_") and species.endswith("_EXPANSION"): return "BEAR_EXPANSION"
    return None


def gate_strategy_hierarchically(
    trades:Sequence[TournamentTrade],*,species_frame,
    trading_dates:Sequence[Any],change_points:Sequence[Mapping[str,Any]],
)->tuple[tuple[TournamentTrade,...],dict[str,Any]]:
    lookup=_Asof(species_frame)
    ordered=tuple(sorted(trades,key=lambda t:ensure_utc(t.signal_at)))
    if not ordered:
        return (),{"candidate_trades":0,"kept_trades":0,"tier_counts":{}}

    species_by_id={}
    for t in ordered:
        row=lookup.row(t.signal_at)
        species_by_id[id(t)]="UNCLASSIFIED" if row is None else str(row.get("species") or "UNCLASSIFIED")

    ordered_exit=tuple(sorted(ordered,key=lambda t:ensure_utc(t.exit_at)))
    exit_times=tuple(ensure_utc(t.exit_at) for t in ordered_exit)
    cp_times=tuple(
        ensure_utc(pd.Timestamp(x["effective_at"]).to_pydatetime())
        for x in change_points
    )
    first_date=trading_dates[0] if trading_dates else ensure_utc(ordered[0].signal_at).date()
    first_epoch=datetime.combine(first_date,time.min,tzinfo=ensure_utc(ordered[0].signal_at).tzinfo)

    kept=[]
    tier_counts:dict[str,int]={}
    state_checks:dict[str,dict[str,int]]={}
    last_decision_by_state:dict[str,Any]={}

    for trade in ordered:
        signal=ensure_utc(trade.signal_at)
        sp=species_by_id[id(trade)]
        side=_species_side(sp)
        broad=_broad_expansion(sp)
        if sp not in EXPANSION_SPECIES or side!=str(trade.direction).upper() or broad is None:
            continue

        cp_pos=bisect_right(cp_times,signal)
        epoch_start=first_epoch if cp_pos==0 else cp_times[cp_pos-1]
        rolling_date=_date_cutoff(signal,trading_dates)
        rolling_start=datetime.combine(rolling_date,time.min,tzinfo=signal.tzinfo)

        completed_end=bisect_left(exit_times,signal)
        completed=ordered_exit[:completed_end]

        exact_recent=[
            x for x in completed
            if ensure_utc(x.exit_at)>=max(epoch_start,rolling_start)
            and species_by_id[id(x)]==sp
            and str(x.direction).upper()==side
        ]
        exact_epoch=[
            x for x in completed
            if ensure_utc(x.exit_at)>=epoch_start
            and species_by_id[id(x)]==sp
            and str(x.direction).upper()==side
        ]
        broad_recent=[
            x for x in completed
            if ensure_utc(x.exit_at)>=max(epoch_start,rolling_start)
            and _broad_expansion(species_by_id[id(x)])==broad
            and str(x.direction).upper()==side
        ]

        tier="OFF_INSUFFICIENT"
        history=()
        if len(exact_recent)>=MIN_COMPLETED_TRADES:
            tier="EXACT_RECENT"
            history=tuple(exact_recent)
        elif len(exact_epoch)>=MIN_COMPLETED_TRADES:
            tier="EXACT_EPOCH"
            history=tuple(exact_epoch)
        elif len(broad_recent)>=MIN_COMPLETED_TRADES:
            tier="BROAD_RECENT"
            history=tuple(broad_recent)

        health=_trailing_health(history)
        tier_counts[tier]=tier_counts.get(tier,0)+1
        st=state_checks.setdefault(sp,{"checks":0,"kept":0})
        st["checks"]+=1
        last_decision_by_state[sp]={
            "tier":tier,
            "completed_trades":health["completed_trades"],
            "profit_factor":health["profit_factor"],
            "expectancy_r":health["expectancy_r"],
            "active":health["active"],
        }
        if health["active"]:
            kept.append(trade)
            st["kept"]+=1

    return tuple(kept),{
        "candidate_trades":len(ordered),
        "kept_trades":len(kept),
        "tier_counts":tier_counts,
        "state_checks":state_checks,
        "last_decision_by_state":last_decision_by_state,
        "hierarchy":[
            "EXACT_SPECIES_RECENT_126D",
            "EXACT_SPECIES_POST_CHANGEPOINT_EPOCH",
            "BROAD_DIRECTIONAL_EXPANSION_RECENT_126D",
            "OFF_IF_STILL_INSUFFICIENT",
        ],
        "health_thresholds":"frozen V40/V47 via _trailing_health",
        "minimum_completed_trades":MIN_COMPLETED_TRADES,
        "change_point_reset":True,
    }


def _state_attribution(trades:Sequence[TournamentTrade],species_frame)->dict[str,Any]:
    lookup=_Asof(species_frame)
    buckets={sp:[] for sp in EXPANSION_SPECIES}
    buckets["OTHER"]=[]
    for t in trades:
        row=lookup.row(t.signal_at)
        sp="UNCLASSIFIED" if row is None else str(row.get("species") or "UNCLASSIFIED")
        if sp in buckets and _species_side(sp)==str(t.direction).upper():
            buckets[sp].append(t)
        else:
            buckets["OTHER"].append(t)
    return {k:_metrics(v) for k,v in buckets.items()}


def evaluate_v101(
    bars:Sequence[Bar],*,evaluation_start,evaluation_end,pip_size:float,costs:M15ResearchCosts,
    broker_spec:BrokerLotSpec,leverage_tiers:Sequence[LeverageTier],
    era_windows:Mapping[str,tuple[Any,Any]],
)->dict[str,Any]:
    rows=tuple(sorted(bars,key=lambda x:ensure_utc(x.timestamp)))
    start=ensure_utc(evaluation_start);end=ensure_utc(evaluation_end)
    species=build_species_frame(rows)
    change_points=detect_change_points(build_fingerprint_frame(rows))
    dates=_trading_dates(rows,start=ensure_utc(rows[0].timestamp),end=end)
    streams=_strategy_streams(rows,costs=costs,pip_size=pip_size)

    selected={};gates={}
    for name in SATELLITES:
        selected[name],gates[name]=gate_strategy_hierarchically(
            streams[name],species_frame=species,trading_dates=dates,change_points=change_points
        )

    core=tuple(t for t in streams["D1_CLASSIC"] if start<=ensure_utc(t.entry_at)<end)
    sats=tuple(
        t for name in SATELLITES for t in selected[name]
        if start<=ensure_utc(t.entry_at)<end
    )
    selector=_limit_concurrency(_dedupe_with_classic((*core,*sats)))

    era_out={}
    for era,(a,b) in era_windows.items():
        aa=ensure_utc(a);bb=ensure_utc(b)
        edates=_trading_dates(rows,start=aa,end=bb)
        core_e=_period(core,aa,bb)
        sel_e=_period(selector,aa,bb)
        attrs={
            name:_state_attribution(_period(streams[name],aa,bb),species)
            for name in SATELLITES
        }
        era_out[era]={
            "core":_metrics(core_e),
            "selector":_metrics(sel_e),
            "raw_state_attribution":attrs,
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
            "selector_unit":"strategy_x_market_species",
            "eligible_species":list(EXPANSION_SPECIES),
            "year_or_calendar_input":False,
            "threshold_grid_search":False,
            "health_thresholds_unchanged":True,
            "hierarchical_backoff_changes_sample_scope_not_thresholds":True,
            "exploratory_after_v100":True,
        },
        "change_points":list(change_points),
        "strategy_state_gates":gates,
        "full_period":{
            "core":_metrics(core),
            "selector":_metrics(selector),
        },
        "eras":era_out,
        "note":"V101 selects each strategy independently conditional on the current expansion species. Exact-state evidence is preferred; sparse states back off causally to broader directional-expansion health without changing the frozen PF/expectancy/sample thresholds.",
    }

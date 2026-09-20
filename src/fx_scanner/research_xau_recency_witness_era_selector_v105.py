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
from .research_xau_state_strategy_matrix_v101 import EXPANSION_SPECIES, _species_side

RESEARCH_VERSION="XAU_RECENCY_WITNESS_ERA_SELECTOR_V105"
ARTIFACT_CONTRACT="XAU_RECENCY_WITNESS_ERA_SELECTOR_V105_EVIDENCE_1"
POLICY_EFFECT="SHADOW_ONLY"
EXECUTION_INFLUENCE=False
PROMOTION_ELIGIBLE=False

RECENCY_WITNESS_DAYS=LOOKBACK_TRADING_DAYS//2


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


def _witness_cutoff(signal_at,trading_dates:Sequence[Any]):
    signal_date=ensure_utc(signal_at).date()
    dates=tuple(trading_dates)
    pos=bisect_left(dates,signal_date)
    if not dates:
        return signal_date
    return dates[max(0,pos-RECENCY_WITNESS_DAYS)]


def gate_exact_state_with_recency(
    strategy_name:str,
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
    stale_epoch_blocks=0
    last_decision={}

    for trade in ordered:
        signal=ensure_utc(trade.signal_at)
        sp=species_by_id[id(trade)]
        side=_species_side(sp)
        if sp not in EXPANSION_SPECIES or side!=str(trade.direction).upper():
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
            and species_by_id[id(x)]==sp
            and str(x.direction).upper()==side
        ]
        exact_epoch=[
            x for x in completed
            if ensure_utc(x.exit_at)>=epoch_start
            and species_by_id[id(x)]==sp
            and str(x.direction).upper()==side
        ]

        tier="OFF_INSUFFICIENT"
        history=()
        witness_ok=False
        witness_cutoff=_witness_cutoff(signal,trading_dates)
        last_exact_exit=None if not exact_epoch else ensure_utc(exact_epoch[-1].exit_at)
        if len(exact_recent)>=MIN_COMPLETED_TRADES:
            tier="EXACT_RECENT"
            history=tuple(exact_recent)
            witness_ok=True
        elif len(exact_epoch)>=MIN_COMPLETED_TRADES:
            witness_ok=(
                last_exact_exit is not None
                and last_exact_exit.date()>=witness_cutoff
            )
            if witness_ok:
                tier="EXACT_EPOCH_RECENT_WITNESS"
                history=tuple(exact_epoch)
            else:
                tier="OFF_STALE_EPOCH"
                stale_epoch_blocks+=1

        health=_trailing_health(history)
        tier_counts[tier]=tier_counts.get(tier,0)+1
        st=state_checks.setdefault(sp,{"checks":0,"kept":0})
        st["checks"]+=1
        last_decision[sp]={
            "tier":tier,
            "completed_trades":health["completed_trades"],
            "profit_factor":health["profit_factor"],
            "expectancy_r":health["expectancy_r"],
            "active":health["active"],
            "witness_ok":witness_ok,
            "last_exact_exit":None if last_exact_exit is None else last_exact_exit.isoformat(),
            "witness_cutoff":str(witness_cutoff),
        }
        if health["active"]:
            kept.append(trade)
            st["kept"]+=1

    return tuple(kept),{
        "strategy":strategy_name,
        "candidate_trades":len(ordered),
        "kept_trades":len(kept),
        "tier_counts":tier_counts,
        "state_checks":state_checks,
        "stale_epoch_blocks":stale_epoch_blocks,
        "last_decision_by_state":last_decision,
        "hierarchy":[
            "EXACT_RECENT_126D",
            "EXACT_POST_CHANGEPOINT_EPOCH_WITH_63D_WITNESS",
            "OFF_IF_INSUFFICIENT_OR_STALE",
        ],
        "recency_witness_days":RECENCY_WITNESS_DAYS,
        "broad_fallback_allowed":False,
        "health_thresholds":"frozen V40/V47 via _trailing_health",
        "minimum_completed_trades":MIN_COMPLETED_TRADES,
        "change_point_reset":True,
    }


def _selected_by_strategy_era(selected:Mapping[str,Sequence[TournamentTrade]],a,b)->dict[str,Any]:
    return {name:_metrics(_period(trades,a,b)) for name,trades in selected.items()}


def evaluate_v105(
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
        selected[name],gates[name]=gate_exact_state_with_recency(
            name,streams[name],species_frame=species,trading_dates=dates,change_points=change_points
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
            "eligible_species":list(EXPANSION_SPECIES),
            "exact_recent_available":True,
            "exact_epoch_requires_recency_witness":True,
            "recency_witness_days":RECENCY_WITNESS_DAYS,
            "recency_witness_derivation":"half_of_frozen_126_trading_day_health_window",
            "broad_fallback_allowed":False,
            "health_thresholds_unchanged":True,
            "calendar_year_used":False,
            "threshold_grid_search":False,
            "exploratory_after_v104_audit":True,
        },
        "change_points":list(change_points),
        "strategy_state_gates":gates,
        "full_period":{"core":_metrics(core),"selector":_metrics(selector)},
        "eras":era_out,
        "note":"V105 keeps V103 exact-state health but blocks stale post-change-point epoch fallback unless the same state has a completed trade within the last 63 trading days. PF, expectancy, sample, regime, and strategy thresholds are unchanged.",
    }

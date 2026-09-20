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
    detect_change_points,
)
from .research_xau_changepoint_reset_router_v87 import build_regime_feature_frame
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
from .research_xau_recency_witness_era_selector_v105 import _witness_cutoff
from .research_xau_stale_reentry_probation_v106 import (
    PROBATION_COMPLETIONS_REQUIRED,
    gate_with_stale_reentry_probation,
)

RESEARCH_VERSION="XAU_M15_FORWARD_WITNESS_V108"
ARTIFACT_CONTRACT="XAU_M15_FORWARD_WITNESS_V108_EVIDENCE_1"
POLICY_EFFECT="SHADOW_ONLY"
EXECUTION_INFLUENCE=False
PROMOTION_ELIGIBLE=False

M15_WITNESS_STRATEGIES=("M15_L12","M15_L20")
D1_STRATEGIES=("D1_STAGGERED",)


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


def gate_m15_with_forward_witness(
    strategy_name:str,
    trades:Sequence[TournamentTrade],*,species_frame,
    trading_dates:Sequence[Any],change_points:Sequence[Mapping[str,Any]],
)->tuple[tuple[TournamentTrade,...],dict[str,Any]]:
    lookup=_Asof(species_frame)
    ordered=tuple(sorted(trades,key=lambda t:ensure_utc(t.signal_at)))
    if not ordered:
        return (),{"candidate_trades":0,"kept_trades":0}

    species_by_id={}
    for t in ordered:
        row=lookup.row(t.signal_at)
        species_by_id[id(t)]="UNCLASSIFIED" if row is None else str(row.get("species") or "UNCLASSIFIED")

    ordered_exit=tuple(sorted(ordered,key=lambda t:ensure_utc(t.exit_at)))
    exit_times=tuple(ensure_utc(t.exit_at) for t in ordered_exit)
    cp_times=tuple(ensure_utc(pd.Timestamp(x["effective_at"]).to_pydatetime()) for x in change_points)
    first_date=trading_dates[0] if trading_dates else ensure_utc(ordered[0].signal_at).date()
    first_epoch=datetime.combine(first_date,time.min,tzinfo=ensure_utc(ordered[0].signal_at).tzinfo)

    kept=[]
    probation_start={}
    prev_base_active={}
    cohort_start={}
    tier_counts={}
    witness_blocks=0
    cohort_reactivations=0
    last_witness={}
    activation_events=[]

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
        witness_cutoff=_witness_cutoff(signal,trading_dates)
        last_exact_exit=None if not exact_epoch else ensure_utc(exact_epoch[-1].exit_at)
        pkey=(epoch_start.isoformat(),sp)
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
                pstart=ensure_utc(probation_start[pkey])
                trial_completed=[
                    x for x in exact_epoch
                    if ensure_utc(x.signal_at)>=pstart
                    and ensure_utc(x.exit_at)<signal
                    and species_by_id[id(x)]==sp
                    and str(x.direction).upper()==side
                ]
                probation_completed=len(trial_completed)
                if probation_completed>=PROBATION_COMPLETIONS_REQUIRED:
                    tier="EXACT_EPOCH_AFTER_PROBATION"
                    history=tuple(exact_epoch)
                else:
                    tier="PROBATION_STALE_REENTRY"

        base_health=_trailing_health(history)
        base_active=bool(base_health["active"])
        key=(epoch_start.isoformat(),sp)
        was_active=bool(prev_base_active.get(key,False))

        if base_active and not was_active:
            cohort_start[key]=signal
            activation_events.append({
                "strategy":strategy_name,
                "species":sp,
                "activated_at":signal.isoformat(),
                "tier":tier,
                "base_pf":base_health["profit_factor"],
                "base_exp":base_health["expectancy_r"],
                "base_n":base_health["completed_trades"],
            })
        if not base_active:
            prev_base_active[key]=False
            tier_counts[tier]=tier_counts.get(tier,0)+1
            continue
        prev_base_active[key]=True

        cstart=ensure_utc(cohort_start[key])
        cohort_completed=[
            x for x in completed
            if ensure_utc(x.signal_at)>=cstart
            and species_by_id[id(x)]==sp
            and str(x.direction).upper()==side
        ]
        cohort_n=len(cohort_completed)
        cohort_net=float(sum(float(x.net_r) for x in cohort_completed))
        authority=cohort_n>=1 and cohort_net>0.0

        prev_auth=bool(last_witness.get(key,{}).get("authority",False))
        if authority and not prev_auth and cohort_n>=1:
            cohort_reactivations+=1
        if not authority:
            witness_blocks+=1
        last_witness[key]={
            "authority":authority,
            "cohort_n":cohort_n,
            "cohort_net_r":cohort_net,
            "cohort_start":cstart.isoformat(),
            "tier":tier,
            "base_pf":base_health["profit_factor"],
            "base_exp":base_health["expectancy_r"],
        }
        tier_counts[tier]=tier_counts.get(tier,0)+1

        if authority:
            kept.append(trade)

    return tuple(kept),{
        "strategy":strategy_name,
        "candidate_trades":len(ordered),
        "kept_trades":len(kept),
        "witness_blocks":witness_blocks,
        "cohort_reactivations":cohort_reactivations,
        "tier_counts":tier_counts,
        "activation_events":activation_events,
        "last_witness_by_state":{f"{k[0]}|{k[1]}":v for k,v in last_witness.items()},
        "forward_witness_contract":{
            "minimum_completed_shadow_candidates":1,
            "authority_condition":"cumulative_post_activation_net_r > 0",
            "zero_r_boundary":True,
            "cohort_resets_on_base_health_off_to_on":True,
            "base_health":"V106 stale-reentry probation + frozen V40/V47 thresholds",
        },
    }


def _selected_by_strategy_era(selected:Mapping[str,Sequence[TournamentTrade]],a,b)->dict[str,Any]:
    return {name:_metrics(_period(trades,a,b)) for name,trades in selected.items()}


def evaluate_v108(
    bars:Sequence[Bar],*,evaluation_start,evaluation_end,pip_size:float,costs:M15ResearchCosts,
    broker_spec:BrokerLotSpec,leverage_tiers:Sequence[LeverageTier],
    era_windows:Mapping[str,tuple[Any,Any]],
)->dict[str,Any]:
    rows=tuple(sorted(bars,key=lambda x:ensure_utc(x.timestamp)))
    start=ensure_utc(evaluation_start);end=ensure_utc(evaluation_end)
    species=build_species_frame(rows)
    change_points=detect_change_points(build_regime_feature_frame(rows))
    dates=_trading_dates(rows,start=ensure_utc(rows[0].timestamp),end=end)
    streams=_strategy_streams(rows,costs=costs,pip_size=pip_size)

    selected={};gates={}
    selected["D1_STAGGERED"],gates["D1_STAGGERED"]=gate_with_stale_reentry_probation(
        "D1_STAGGERED",streams["D1_STAGGERED"],species_frame=species,trading_dates=dates,change_points=change_points
    )
    for name in M15_WITNESS_STRATEGIES:
        selected[name],gates[name]=gate_m15_with_forward_witness(
            name,streams[name],species_frame=species,trading_dates=dates,change_points=change_points
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
            "d1_policy":"unchanged V106 stale-reentry probation",
            "m15_forward_witness_strategies":list(M15_WITNESS_STRATEGIES),
            "m15_authority_condition":"at least one completed post-activation shadow candidate and cumulative cohort net R > 0",
            "witness_threshold_optimized":False,
            "health_thresholds_unchanged":True,
            "calendar_year_used":False,
            "threshold_grid_search":False,
            "exploratory_after_v107":True,
        },
        "change_points":list(change_points),
        "strategy_state_gates":gates,
        "full_period":{"core":_metrics(core),"selector":_metrics(selector)},
        "eras":era_out,
        "note":"V108 keeps V106 for D1 and adds a parameter-free zero-R contemporaneous forward witness to M15 L12/L20. Base historical health grants eligibility; fresh post-activation cohort PnL grants execution authority.",
    }

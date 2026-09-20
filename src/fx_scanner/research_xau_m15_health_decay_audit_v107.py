from __future__ import annotations

from bisect import bisect_left, bisect_right
from datetime import datetime, time
from typing import Any, Sequence

import pandas as pd

from .models import Bar, ensure_utc
from .research_xau_changepoint_reset_router_v87 import (
    MIN_COMPLETED_TRADES,
    _date_cutoff,
    _trailing_health,
    detect_change_points,
)
from .research_xau_era_fingerprint_v97 import build_fingerprint_frame
from .research_xau_expansion_species_v99 import build_species_frame
from .research_xau_multihorizon_100usd_v20 import _trading_dates
from .research_xau_m15_dual_strategy import M15ResearchCosts
from .research_xau_causal_era_selector_v98 import _strategy_streams
from .research_xau_state_strategy_matrix_v101 import EXPANSION_SPECIES, _species_side
from .research_xau_recency_witness_era_selector_v105 import _witness_cutoff
from .research_xau_stale_reentry_probation_v106 import PROBATION_COMPLETIONS_REQUIRED

RESEARCH_VERSION="XAU_M15_HEALTH_DECAY_AUDIT_V107"
ARTIFACT_CONTRACT="XAU_M15_HEALTH_DECAY_AUDIT_V107_EVIDENCE_1"
POLICY_EFFECT="SHADOW_ONLY"
EXECUTION_INFLUENCE=False
PROMOTION_ELIGIBLE=False
AUDIT_STRATEGIES=("M15_L12","M15_L20")


class _Asof:
    def __init__(self,frame):
        self.frame=frame.reset_index(drop=True)
        self.times=[ensure_utc(x) for x in self.frame["available_at"]]
    def row(self,timestamp):
        i=bisect_right(self.times,ensure_utc(timestamp))-1
        if i<0:return None
        return self.frame.iloc[i].to_dict()


def _metrics(values):
    h=_trailing_health(tuple(values))
    return {
        "n":h["completed_trades"],
        "pf":h["profit_factor"],
        "exp":h["expectancy_r"],
        "net_r":h["net_r"],
        "active":h["active"],
    }


def audit_m15_decay(
    rows:Sequence[Bar],*,costs:M15ResearchCosts,pip_size:float,evaluation_end
)->dict[str,Any]:
    bars=tuple(sorted(rows,key=lambda x:ensure_utc(x.timestamp)))
    species_frame=build_species_frame(bars)
    lookup=_Asof(species_frame)
    change_points=detect_change_points(build_fingerprint_frame(bars))
    dates=_trading_dates(bars,start=ensure_utc(bars[0].timestamp),end=ensure_utc(evaluation_end))
    streams=_strategy_streams(bars,costs=costs,pip_size=pip_size)

    out={}
    for strategy_name in AUDIT_STRATEGIES:
        trades=tuple(sorted(streams[strategy_name],key=lambda t:ensure_utc(t.signal_at)))
        species_by_id={}
        for t in trades:
            row=lookup.row(t.signal_at)
            species_by_id[id(t)]="UNCLASSIFIED" if row is None else str(row.get("species") or "UNCLASSIFIED")

        by_exit=tuple(sorted(trades,key=lambda t:ensure_utc(t.exit_at)))
        exit_times=tuple(ensure_utc(t.exit_at) for t in by_exit)
        cp_times=tuple(ensure_utc(pd.Timestamp(x["effective_at"]).to_pydatetime()) for x in change_points)
        first_date=dates[0]
        first_epoch=datetime.combine(first_date,time.min,tzinfo=ensure_utc(trades[0].signal_at).tzinfo)

        probation_start={}
        selected=[]
        activations=[]
        deactivations=[]
        prev_active={}
        active_since={}
        for t in trades:
            signal=ensure_utc(t.signal_at)
            if not (datetime(2019,1,1,tzinfo=signal.tzinfo)<=signal<datetime(2025,1,1,tzinfo=signal.tzinfo)):
                continue
            sp=species_by_id[id(t)]
            side=_species_side(sp)
            if sp not in EXPANSION_SPECIES or side!=str(t.direction).upper():
                continue

            cp_pos=bisect_right(cp_times,signal)
            epoch_start=first_epoch if cp_pos==0 else cp_times[cp_pos-1]
            rolling_date=_date_cutoff(signal,dates)
            rolling_start=datetime.combine(rolling_date,time.min,tzinfo=signal.tzinfo)
            recent_start=max(epoch_start,rolling_start)

            completed_end=bisect_left(exit_times,signal)
            completed=by_exit[:completed_end]
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

            tier="OFF_INSUFFICIENT"; history=()
            witness_cutoff=_witness_cutoff(signal,dates)
            last_exact_exit=None if not exact_epoch else ensure_utc(exact_epoch[-1].exit_at)
            pkey=(epoch_start.isoformat(),sp)
            probation_completed=0

            if len(exact_recent)>=MIN_COMPLETED_TRADES:
                tier="EXACT_RECENT"
                history=tuple(exact_recent)
            elif len(exact_epoch)>=MIN_COMPLETED_TRADES:
                witness_ok=last_exact_exit is not None and last_exact_exit.date()>=witness_cutoff
                if witness_ok:
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

            health=_trailing_health(history)
            key=sp
            now=bool(health["active"])
            before=bool(prev_active.get(key,False))
            if now and not before:
                active_since[key]=signal
                activations.append({
                    "strategy":strategy_name,
                    "activated_at":signal.isoformat(),
                    "species":sp,
                    "tier":tier,
                    "health":_metrics(history),
                    "last_exact_exit":None if last_exact_exit is None else last_exact_exit.isoformat(),
                })
            if before and not now:
                since=active_since.get(key)
                deactivations.append({
                    "strategy":strategy_name,
                    "deactivated_at":signal.isoformat(),
                    "species":sp,
                    "tier":tier,
                    "health":_metrics(history),
                    "active_since":None if since is None else ensure_utc(since).isoformat(),
                })
            prev_active[key]=now

            if now:
                since=active_since.get(key,signal)
                selected_since=[
                    x for x in trades
                    if ensure_utc(x.signal_at)>=since
                    and ensure_utc(x.exit_at)<signal
                    and species_by_id[id(x)]==sp
                    and str(x.direction).upper()==side
                ]
                selected.append({
                    "strategy":strategy_name,
                    "signal_at":signal.isoformat(),
                    "entry_at":ensure_utc(t.entry_at).isoformat(),
                    "exit_at":ensure_utc(t.exit_at).isoformat(),
                    "species":sp,
                    "tier":tier,
                    "pre_health":_metrics(history),
                    "since_activation_completed":_metrics(selected_since),
                    "net_r":float(t.net_r),
                    "exit_reason":str(t.exit_reason),
                })

        out[strategy_name]={
            "activations":activations,
            "deactivations":deactivations,
            "selected_trades":selected,
        }

    return {
        "research_version":RESEARCH_VERSION,
        "artifact_contract":ARTIFACT_CONTRACT,
        "policy_effect":POLICY_EFFECT,
        "execution_influence":EXECUTION_INFLUENCE,
        "promotion_eligible":PROMOTION_ELIGIBLE,
        "strategies":out,
        "change_points":list(change_points),
        "note":"V107 is forensic only. It reconstructs V106-style M15 activations during 2019-2024 and records causal pre-trade health plus completed outcomes since each activation.",
    }

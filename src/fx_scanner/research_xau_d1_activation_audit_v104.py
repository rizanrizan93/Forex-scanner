from __future__ import annotations

from bisect import bisect_left, bisect_right
from datetime import datetime, time
from typing import Any, Mapping, Sequence

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

RESEARCH_VERSION="XAU_D1_ACTIVATION_AUDIT_V104"
ARTIFACT_CONTRACT="XAU_D1_ACTIVATION_AUDIT_V104_EVIDENCE_1"
POLICY_EFFECT="SHADOW_ONLY"
EXECUTION_INFLUENCE=False
PROMOTION_ELIGIBLE=False


class _Asof:
    def __init__(self,frame):
        self.frame=frame.reset_index(drop=True)
        self.times=[ensure_utc(x) for x in self.frame["available_at"]]
    def row(self,timestamp):
        i=bisect_right(self.times,ensure_utc(timestamp))-1
        if i<0:return None
        return self.frame.iloc[i].to_dict()


def audit_d1(
    rows:Sequence[Bar],*,costs:M15ResearchCosts,pip_size:float,evaluation_end
)->dict[str,Any]:
    bars=tuple(sorted(rows,key=lambda x:ensure_utc(x.timestamp)))
    species_frame=build_species_frame(bars)
    lookup=_Asof(species_frame)
    change_points=detect_change_points(build_fingerprint_frame(bars))
    dates=_trading_dates(bars,start=ensure_utc(bars[0].timestamp),end=ensure_utc(evaluation_end))
    trades=tuple(sorted(
        _strategy_streams(bars,costs=costs,pip_size=pip_size)["D1_STAGGERED"],
        key=lambda t:ensure_utc(t.signal_at),
    ))

    species_by_id={}
    for t in trades:
        row=lookup.row(t.signal_at)
        species_by_id[id(t)]="UNCLASSIFIED" if row is None else str(row.get("species") or "UNCLASSIFIED")

    by_exit=tuple(sorted(trades,key=lambda t:ensure_utc(t.exit_at)))
    exit_times=tuple(ensure_utc(t.exit_at) for t in by_exit)
    cp_times=tuple(ensure_utc(pd.Timestamp(x["effective_at"]).to_pydatetime()) for x in change_points)
    first_date=dates[0]
    first_epoch=datetime.combine(first_date,time.min,tzinfo=ensure_utc(trades[0].signal_at).tzinfo)

    selected=[]
    activations=[]
    last_active={}
    for t in trades:
        signal=ensure_utc(t.signal_at)
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

        tier="OFF_INSUFFICIENT"; hist=()
        if len(exact_recent)>=MIN_COMPLETED_TRADES:
            tier="EXACT_RECENT"; hist=tuple(exact_recent)
        elif len(exact_epoch)>=MIN_COMPLETED_TRADES:
            tier="EXACT_EPOCH"; hist=tuple(exact_epoch)

        health=_trailing_health(hist)
        key=sp
        prev=last_active.get(key,False)
        now=bool(health["active"])
        if now and not prev:
            activations.append({
                "activated_at":signal.isoformat(),
                "species":sp,
                "tier":tier,
                "completed_trades":health["completed_trades"],
                "profit_factor":health["profit_factor"],
                "expectancy_r":health["expectancy_r"],
                "epoch_start":epoch_start.isoformat(),
                "recent_start":recent_start.isoformat(),
                "prior_last_5":[
                    {
                        "signal_at":ensure_utc(x.signal_at).isoformat(),
                        "exit_at":ensure_utc(x.exit_at).isoformat(),
                        "net_r":float(x.net_r),
                        "species":species_by_id[id(x)],
                    }
                    for x in hist[-5:]
                ],
            })
        last_active[key]=now

        if now:
            selected.append({
                "signal_at":signal.isoformat(),
                "entry_at":ensure_utc(t.entry_at).isoformat(),
                "exit_at":ensure_utc(t.exit_at).isoformat(),
                "species":sp,
                "direction":str(t.direction),
                "tier":tier,
                "health_n":health["completed_trades"],
                "health_pf":health["profit_factor"],
                "health_exp":health["expectancy_r"],
                "net_r":float(t.net_r),
                "reason":str(t.exit_reason),
            })

    return {
        "research_version":RESEARCH_VERSION,
        "artifact_contract":ARTIFACT_CONTRACT,
        "policy_effect":POLICY_EFFECT,
        "execution_influence":EXECUTION_INFLUENCE,
        "promotion_eligible":PROMOTION_ELIGIBLE,
        "selected_trades":selected,
        "activations":activations,
        "change_points":list(change_points),
    }

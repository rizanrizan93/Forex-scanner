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
from .research_xau_expansion_species_v99 import build_species_frame
from .research_xau_m15_exceptional_expansion_audit_v109 import build_exceptional_frame
from .research_xau_multihorizon_100usd_v20 import _limit_concurrency, _trading_dates
from .research_xau_causal_era_selector_v98 import SATELLITES, _strategy_streams
from .research_xau_recency_witness_era_selector_v105 import (
    RECENCY_WITNESS_DAYS,
    _witness_cutoff,
)
from .research_xau_v110_100usd_no_risk_v112 import _cash_path_dynamic_no_risk

RESEARCH_VERSION="XAU_CAPITAL_PRESERVATION_V114"
ARTIFACT_CONTRACT="XAU_CAPITAL_PRESERVATION_V114_EVIDENCE_1"
POLICY_EFFECT="SHADOW_ONLY"
EXECUTION_INFLUENCE=False
PROMOTION_ELIGIBLE=False


class _Asof:
    def __init__(self,frame:pd.DataFrame):
        self.frame=frame.reset_index(drop=True)
        self.times=[ensure_utc(x) for x in self.frame["available_at"]]

    def row(self,timestamp):
        i=bisect_right(self.times,ensure_utc(timestamp))-1
        if i<0:
            return None
        return self.frame.iloc[i].to_dict()


D1_ELIGIBLE_SPECIES=(
    "BULL_STRUCTURAL_EXPANSION",
    "BULL_SHOCK_EXPANSION",
    "BEAR_STRUCTURAL_EXPANSION",
    "BEAR_SHOCK_EXPANSION",
)


def _species_label(row:Mapping[str,Any]|None)->str|None:
    if row is None:
        return None
    label=str(row.get("species") or "UNCLASSIFIED")
    return label if label in D1_ELIGIBLE_SPECIES else None


def _m15_label(row:Mapping[str,Any]|None)->str|None:
    if row is None or not bool(row.get("unanimous_extreme_expansion")):
        return None
    state=str(row.get("state") or "")
    if state=="BULL_EXPANSION":
        return "BULL_UNANIMOUS_EXTREME"
    if state=="BEAR_EXPANSION":
        return "BEAR_UNANIMOUS_EXTREME"
    return None


def _label_side(label:str|None)->str|None:
    if not label:
        return None
    if str(label).startswith("BULL_"):
        return "LONG"
    if str(label).startswith("BEAR_"):
        return "SHORT"
    return None


def _trade_label(trade:TournamentTrade, *, lookup:_Asof, mode:str)->str|None:
    row=lookup.row(trade.signal_at)
    if mode=="D1":
        return _species_label(row)
    if mode=="M15":
        return _m15_label(row)
    raise ValueError(mode)


def _proven_edge_at(
    *,
    as_of,
    desired_direction:str,
    trades:Sequence[TournamentTrade],
    lookup:_Asof,
    mode:str,
    trading_dates:Sequence[Any],
    change_points:Sequence[Mapping[str,Any]],
)->dict[str,Any]:
    now=ensure_utc(as_of)
    row=lookup.row(now)
    label=_species_label(row) if mode=="D1" else _m15_label(row)
    side=_label_side(label)
    if side is None or side!=str(desired_direction).upper():
        return {
            "proven":False,
            "label":label,
            "tier":"OFF_STATE_OR_DIRECTION",
            "n":0,
            "pf":None,
            "exp":None,
        }

    ordered=tuple(sorted(trades,key=lambda t:ensure_utc(t.signal_at)))
    labels={id(t):_trade_label(t,lookup=lookup,mode=mode) for t in ordered}

    cp_times=tuple(
        ensure_utc(pd.Timestamp(x["effective_at"]).to_pydatetime())
        for x in change_points
        if ensure_utc(pd.Timestamp(x["effective_at"]).to_pydatetime())<=now
    )
    first_date=trading_dates[0] if trading_dates else now.date()
    first_epoch=datetime.combine(first_date,time.min,tzinfo=now.tzinfo)
    epoch_start=first_epoch if not cp_times else cp_times[-1]

    rolling_date=_date_cutoff(now,trading_dates)
    rolling_start=datetime.combine(rolling_date,time.min,tzinfo=now.tzinfo)
    recent_start=max(epoch_start,rolling_start)

    completed=[
        t for t in ordered
        if ensure_utc(t.exit_at)<now
        and labels[id(t)]==label
        and str(t.direction).upper()==side
    ]
    recent=[t for t in completed if ensure_utc(t.exit_at)>=recent_start]
    epoch=[t for t in completed if ensure_utc(t.exit_at)>=epoch_start]

    tier="OFF_INSUFFICIENT"
    history=()
    if len(recent)>=MIN_COMPLETED_TRADES:
        tier="EXACT_RECENT"
        history=tuple(recent)
    elif len(epoch)>=MIN_COMPLETED_TRADES:
        cutoff=_witness_cutoff(now,trading_dates)
        last_exit=ensure_utc(epoch[-1].exit_at) if epoch else None
        if last_exit is not None and last_exit.date()>=cutoff:
            tier="EXACT_EPOCH_FRESH"
            history=tuple(epoch)
        else:
            return {
                "proven":False,
                "label":label,
                "tier":"OFF_STALE_EPOCH",
                "n":len(epoch),
                "pf":None,
                "exp":None,
                "last_exact_exit":None if last_exit is None else last_exit.isoformat(),
                "witness_cutoff":str(cutoff),
            }

    health=_trailing_health(history)
    return {
        "proven":bool(health["active"]),
        "label":label,
        "tier":tier,
        "n":health["completed_trades"],
        "pf":health["profit_factor"],
        "exp":health["expectancy_r"],
        "net_r":health["net_r"],
    }


def build_capital_preservation_portfolio(
    rows:Sequence[Bar],*,costs,pip_size:float,evaluation_end
)->tuple[
    tuple[TournamentTrade,...],
    tuple[TournamentTrade,...],
    tuple[TournamentTrade,...],
    dict[str,Any],
]:
    bars=tuple(sorted(rows,key=lambda x:ensure_utc(x.timestamp)))
    end=ensure_utc(evaluation_end)

    species=build_species_frame(bars)
    exceptional=build_exceptional_frame(bars)
    species_lookup=_Asof(species)
    exceptional_lookup=_Asof(exceptional)
    change_points=detect_change_points(build_regime_feature_frame(bars))
    dates=_trading_dates(bars,start=ensure_utc(bars[0].timestamp),end=end)
    streams=_strategy_streams(bars,costs=costs,pip_size=pip_size)

    # Frozen V110 satellites are reproduced using their existing selectors.
    from .research_xau_stale_reentry_probation_v106 import gate_with_stale_reentry_probation
    from .research_xau_strategy_specific_state_v110 import gate_m15_exceptional_health

    selected={}
    selected["D1_STAGGERED"],_=gate_with_stale_reentry_probation(
        "D1_STAGGERED",
        streams["D1_STAGGERED"],
        species_frame=species,
        trading_dates=dates,
        change_points=change_points,
    )
    for name in ("M15_L12","M15_L20"):
        selected[name],_=gate_m15_exceptional_health(
            name,
            streams[name],
            exceptional_frame=exceptional,
            trading_dates=dates,
            change_points=change_points,
        )

    satellites=tuple(t for name in SATELLITES for t in selected[name])

    kept_core=[]
    suppressed=[]
    permission_counts={"D1_STAGGERED":0,"M15_L12":0,"M15_L20":0}
    for trade in sorted(streams["D1_CLASSIC"],key=lambda t:ensure_utc(t.signal_at)):
        checks={
            "D1_STAGGERED":_proven_edge_at(
                as_of=trade.signal_at,
                desired_direction=trade.direction,
                trades=streams["D1_STAGGERED"],
                lookup=species_lookup,
                mode="D1",
                trading_dates=dates,
                change_points=change_points,
            ),
            "M15_L12":_proven_edge_at(
                as_of=trade.signal_at,
                desired_direction=trade.direction,
                trades=streams["M15_L12"],
                lookup=exceptional_lookup,
                mode="M15",
                trading_dates=dates,
                change_points=change_points,
            ),
            "M15_L20":_proven_edge_at(
                as_of=trade.signal_at,
                desired_direction=trade.direction,
                trades=streams["M15_L20"],
                lookup=exceptional_lookup,
                mode="M15",
                trading_dates=dates,
                change_points=change_points,
            ),
        }
        proven=[name for name,x in checks.items() if x["proven"]]
        if proven:
            kept_core.append(trade)
            for name in proven:
                permission_counts[name]+=1
        else:
            suppressed.append({
                "signal_at":ensure_utc(trade.signal_at).isoformat(),
                "direction":str(trade.direction),
                "reason":"CASH_NO_PROVEN_EDGE",
                "state_checks":checks,
            })

    gated_core=tuple(kept_core)
    portfolio=_limit_concurrency(_dedupe_with_classic((*gated_core,*satellites)))
    diagnostics={
        "raw_core_trades":len(streams["D1_CLASSIC"]),
        "kept_core_trades":len(gated_core),
        "suppressed_core_trades":len(suppressed),
        "permission_counts":permission_counts,
        "suppressed_examples":suppressed[:20],
        "capital_preservation_rule":"D1 core executes only when at least one V110 family has same-direction proven causal edge with frozen health thresholds and fresh evidence; otherwise CASH. Frozen V110 satellites remain unchanged.",
        "shadow_learning_continues_while_cash":True,
    }
    return tuple(streams["D1_CLASSIC"]),gated_core,portfolio,diagnostics


def _period(trades:Sequence[TournamentTrade],start,end)->tuple[TournamentTrade,...]:
    a=ensure_utc(start);b=ensure_utc(end)
    return tuple(t for t in trades if a<=ensure_utc(t.entry_at)<b)


def evaluate_v114(
    rows:Sequence[Bar],*,
    evaluation_start,
    evaluation_end,
    pip_size:float,
    cost_scenarios:Mapping[str,Any],
    broker_spec,
    leverage_tiers,
)->dict[str,Any]:
    bars=tuple(sorted(rows,key=lambda x:ensure_utc(x.timestamp)))
    start=ensure_utc(evaluation_start);end=ensure_utc(evaluation_end)
    dates=_trading_dates(bars,start=start,end=end)

    scenarios={}
    for cost_id,costs in cost_scenarios.items():
        raw_core,gated_core,portfolio,diag=build_capital_preservation_portfolio(
            bars,costs=costs,pip_size=pip_size,evaluation_end=end
        )
        p=_period(portfolio,start,end)
        gc=_period(gated_core,start,end)
        rc=_period(raw_core,start,end)

        fixed=_cash_path_stopout_safe(
            p,
            spec=broker_spec,
            tiers=leverage_tiers,
            account_leverage=100.0,
            stopout_pct=50.0,
            trading_dates=dates,
        )
        dynamic=_cash_path_dynamic_no_risk(
            p,
            spec=broker_spec,
            tiers=leverage_tiers,
            trading_dates=dates,
            evaluation_start=start,
            evaluation_end=end,
        )

        eras={}
        for era,a,b in (
            ("2012_2018",datetime(2012,1,1,tzinfo=start.tzinfo),datetime(2019,1,1,tzinfo=start.tzinfo)),
            ("2019_2024",datetime(2019,1,1,tzinfo=start.tzinfo),datetime(2025,1,1,tzinfo=start.tzinfo)),
            ("2025_2026YTD",datetime(2025,1,1,tzinfo=start.tzinfo),end),
        ):
            eras[era]={
                "raw_core":compute_metrics(_period(rc,a,b)).payload(),
                "gated_core":compute_metrics(_period(gc,a,b)).payload(),
                "capital_preservation_portfolio":compute_metrics(_period(p,a,b)).payload(),
            }

        scenarios[cost_id]={
            "diagnostics":diag,
            "full_metrics":{
                "raw_core":compute_metrics(rc).payload(),
                "gated_core":compute_metrics(gc).payload(),
                "capital_preservation_portfolio":compute_metrics(p).payload(),
            },
            "era_metrics":eras,
            "cash_fixed_001_no_risk_cap":fixed,
            "cash_dynamic_001_to_050_no_risk_cap":dynamic,
        }

    return {
        "research_version":RESEARCH_VERSION,
        "artifact_contract":ARTIFACT_CONTRACT,
        "policy_effect":POLICY_EFFECT,
        "execution_influence":EXECUTION_INFLUENCE,
        "promotion_eligible":PROMOTION_ELIGIBLE,
        "live_execution_enabled":False,
        "contract":{
            "base_selector":"frozen V110",
            "starting_balance_usd":100.0,
            "account_leverage":100.0,
            "risk_pct_filter":None,
            "broker_stopout_pct":50.0,
            "capital_preservation_state":"CASH_NO_PROVEN_EDGE",
            "core_permission":"same-direction proven causal edge from D1 staggered or M15 L12/L20",
            "satellite_policy":"unchanged frozen V110",
            "health_thresholds_unchanged":True,
            "recency_witness_days":RECENCY_WITNESS_DAYS,
            "calendar_year_used_for_routing":False,
            "parameter_search":False,
        },
        "scenarios":scenarios,
        "note":"V114 tests whether a causal CASH state can preserve a tiny $100 XAU account across hostile eras. All strategy histories continue in shadow while cash, so later reactivation uses information that would have been observable prospectively.",
    }

from __future__ import annotations

from bisect import bisect_right
from typing import Any, Mapping, Sequence

from .demo_donchian_adaptive_tournament import TournamentTrade, compute_metrics
from .models import Bar, ensure_utc
from .research_xau_100usd_stopout_v23 import _cash_path_stopout_safe
from .research_xau_changepoint_reset_router_v87 import detect_change_points
from .research_xau_era_fingerprint_v97 import build_fingerprint_frame
from .research_xau_era_robustness_v31 import _dedupe_with_classic
from .research_xau_margin_leverage_v21 import LeverageTier
from .research_xau_multihorizon_100usd_v20 import BrokerLotSpec, _limit_concurrency, _trading_dates
from .research_xau_m15_dual_strategy import M15ResearchCosts
from .research_xau_causal_era_selector_v98 import (
    ACCOUNT_LEVERAGE,
    MARGIN_FLOOR_PCT,
    SATELLITES,
    _strategy_streams,
    build_causal_state_frame,
    gate_strategy_by_state_health,
)
from .research_xau_expansion_species_v99 import (
    build_species_frame,
    _dir_matches_species,
)

RESEARCH_VERSION="XAU_HYBRID_ERA_SELECTOR_V100"
ARTIFACT_CONTRACT="XAU_HYBRID_ERA_SELECTOR_V100_EVIDENCE_1"
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


def _period(trades:Sequence[TournamentTrade],a,b)->tuple[TournamentTrade,...]:
    aa=ensure_utc(a);bb=ensure_utc(b)
    return tuple(t for t in trades if aa<=ensure_utc(t.entry_at)<bb)


def _metrics(trades)->dict[str,Any]:
    return compute_metrics(tuple(trades)).payload()


def _filter_structural_permission(
    trades:Sequence[TournamentTrade],species_frame
)->tuple[tuple[TournamentTrade,...],dict[str,Any]]:
    lookup=_Asof(species_frame)
    kept=[]
    by_species:dict[str,dict[str,int]]={}
    first_kept:dict[str,str]={}
    for t in sorted(trades,key=lambda x:ensure_utc(x.signal_at)):
        row=lookup.row(t.signal_at)
        sp="UNCLASSIFIED" if row is None else str(row.get("species") or "UNCLASSIFIED")
        st=by_species.setdefault(sp,{"seen":0,"kept":0})
        st["seen"]+=1
        if _dir_matches_species(t,sp):
            kept.append(t)
            st["kept"]+=1
            first_kept.setdefault(sp,ensure_utc(t.signal_at).isoformat())
    return tuple(kept),{
        "input_v98_approved_trades":len(trades),
        "kept_structural_direction_matched":len(kept),
        "suppressed_by_species_mask":len(trades)-len(kept),
        "by_species":by_species,
        "first_kept_by_species":first_kept,
    }


def _raw_species_attribution(
    trades:Sequence[TournamentTrade],species_frame
)->dict[str,Any]:
    lookup=_Asof(species_frame)
    buckets={"STRUCTURAL_MATCH":[],"SHOCK_MATCH":[],"OTHER":[]}
    for t in trades:
        row=lookup.row(t.signal_at)
        sp="UNCLASSIFIED" if row is None else str(row.get("species") or "UNCLASSIFIED")
        d=str(t.direction).upper()
        structural=(
            (sp=="BULL_STRUCTURAL_EXPANSION" and d=="LONG")
            or (sp=="BEAR_STRUCTURAL_EXPANSION" and d=="SHORT")
        )
        shock=(
            (sp=="BULL_SHOCK_EXPANSION" and d=="LONG")
            or (sp=="BEAR_SHOCK_EXPANSION" and d=="SHORT")
        )
        if structural:buckets["STRUCTURAL_MATCH"].append(t)
        elif shock:buckets["SHOCK_MATCH"].append(t)
        else:buckets["OTHER"].append(t)
    return {k:_metrics(v) for k,v in buckets.items()}


def evaluate_v100(
    bars:Sequence[Bar],*,evaluation_start,evaluation_end,pip_size:float,costs:M15ResearchCosts,
    broker_spec:BrokerLotSpec,leverage_tiers:Sequence[LeverageTier],
    era_windows:Mapping[str,tuple[Any,Any]],
)->dict[str,Any]:
    rows=tuple(sorted(bars,key=lambda x:ensure_utc(x.timestamp)))
    start=ensure_utc(evaluation_start);end=ensure_utc(evaluation_end)

    broad_state=build_causal_state_frame(rows)
    species=build_species_frame(rows)
    change_points=detect_change_points(build_fingerprint_frame(rows))
    dates=_trading_dates(rows,start=ensure_utc(rows[0].timestamp),end=end)
    streams=_strategy_streams(rows,costs=costs,pip_size=pip_size)

    v98_selected={};v98_gates={}
    structural_selected={};species_masks={}
    for name in SATELLITES:
        v98_selected[name],v98_gates[name]=gate_strategy_by_state_health(
            streams[name],
            state_frame=broad_state,
            trading_dates=dates,
            change_points=change_points,
        )
        structural_selected[name],species_masks[name]=_filter_structural_permission(
            v98_selected[name],species
        )

    core=tuple(t for t in streams["D1_CLASSIC"] if start<=ensure_utc(t.entry_at)<end)

    v98_sats=tuple(
        t for name in SATELLITES for t in v98_selected[name]
        if start<=ensure_utc(t.entry_at)<end
    )
    v98_selector=_limit_concurrency(_dedupe_with_classic((*core,*v98_sats)))

    hybrid_sats=tuple(
        t for name in SATELLITES for t in structural_selected[name]
        if start<=ensure_utc(t.entry_at)<end
    )
    hybrid=_limit_concurrency(_dedupe_with_classic((*core,*hybrid_sats)))

    raw_attr={}
    for name in SATELLITES:
        eligible=tuple(t for t in streams[name] if start<=ensure_utc(t.entry_at)<end)
        raw_attr[name]=_raw_species_attribution(eligible,species)

    era_out={}
    for era,(a,b) in era_windows.items():
        aa=ensure_utc(a);bb=ensure_utc(b)
        edates=_trading_dates(rows,start=aa,end=bb)
        core_e=_period(core,aa,bb)
        v98_e=_period(v98_selector,aa,bb)
        hybrid_e=_period(hybrid,aa,bb)
        raw_by_strategy={}
        for name in SATELLITES:
            raw_by_strategy[name]=_raw_species_attribution(_period(streams[name],aa,bb),species)
        era_out[era]={
            "core":_metrics(core_e),
            "v98_selector":_metrics(v98_e),
            "hybrid_selector":_metrics(hybrid_e),
            "raw_species_attribution":raw_by_strategy,
            "cash_fresh_100":{
                "core":_cash_path_stopout_safe(core_e,spec=broker_spec,tiers=leverage_tiers,account_leverage=ACCOUNT_LEVERAGE,stopout_pct=MARGIN_FLOOR_PCT,trading_dates=edates),
                "v98_selector":_cash_path_stopout_safe(v98_e,spec=broker_spec,tiers=leverage_tiers,account_leverage=ACCOUNT_LEVERAGE,stopout_pct=MARGIN_FLOOR_PCT,trading_dates=edates),
                "hybrid_selector":_cash_path_stopout_safe(hybrid_e,spec=broker_spec,tiers=leverage_tiers,account_leverage=ACCOUNT_LEVERAGE,stopout_pct=MARGIN_FLOOR_PCT,trading_dates=edates),
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
            "market_health_order":"V98 broad expansion health first, V99 structural species mask second",
            "v98_thresholds_unchanged":True,
            "v99_quality_thresholds_unchanged":True,
            "species_specific_health_reestimated":False,
            "calendar_year_used":False,
            "threshold_grid_search":False,
            "exploratory_followup_after_v99":True,
        },
        "change_points":list(change_points),
        "v98_gates":v98_gates,
        "species_masks":species_masks,
        "raw_species_attribution_full":raw_attr,
        "full_period":{
            "core":_metrics(core),
            "v98_selector":_metrics(v98_selector),
            "hybrid_selector":_metrics(hybrid),
        },
        "eras":era_out,
        "note":"V100 preserves V98's broader causal strategy-health sample and uses V99 structural expansion only as a second market-quality permission mask. It does not loosen any health or state threshold.",
    }

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Sequence

from .demo_donchian_adaptive_tournament import TournamentTrade, compute_metrics
from .models import Bar, ensure_utc
from .research_xau_100usd_stopout_v23 import _cash_path_stopout_safe
from .research_xau_changepoint_reset_router_v87 import build_regime_feature_frame, detect_change_points
from .research_xau_expansion_species_v99 import build_species_frame
from .research_xau_era_robustness_v31 import _dedupe_with_classic
from .research_xau_multihorizon_100usd_v20 import _limit_concurrency, _trading_dates
from .research_xau_causal_era_selector_v98 import (
    ACCOUNT_LEVERAGE,
    MARGIN_FLOOR_PCT,
    SATELLITES,
    _strategy_streams,
)
from .research_xau_m15_exceptional_expansion_audit_v109 import build_exceptional_frame
from .research_xau_stale_reentry_probation_v106 import gate_with_stale_reentry_probation
from .research_xau_strategy_specific_state_v110 import gate_m15_exceptional_health

RESEARCH_VERSION="XAU_V110_ROBUSTNESS_V111"
ARTIFACT_CONTRACT="XAU_V110_ROBUSTNESS_V111_EVIDENCE_1"
POLICY_EFFECT="SHADOW_ONLY"
EXECUTION_INFLUENCE=False
PROMOTION_ELIGIBLE=False

START_SENSITIVITY_YEARS=(2012,2015,2019,2022,2025)


def _metrics(trades:Sequence[TournamentTrade])->dict[str,Any]:
    return compute_metrics(tuple(trades)).payload()


def _period(trades:Sequence[TournamentTrade],start,end)->tuple[TournamentTrade,...]:
    a=ensure_utc(start);b=ensure_utc(end)
    return tuple(t for t in trades if a<=ensure_utc(t.entry_at)<b)


def _net_r(metric:Mapping[str,Any])->float:
    return float(metric.get("gross_profit_r") or 0.0)-float(metric.get("gross_loss_r") or 0.0)


def assemble_v110_selector(rows:Sequence[Bar],*,costs,pip_size:float,evaluation_end):
    bars=tuple(sorted(rows,key=lambda x:ensure_utc(x.timestamp)))
    end=ensure_utc(evaluation_end)
    exceptional=build_exceptional_frame(bars)
    species=build_species_frame(bars)
    change_points=detect_change_points(build_regime_feature_frame(bars))
    dates=_trading_dates(bars,start=ensure_utc(bars[0].timestamp),end=end)
    streams=_strategy_streams(bars,costs=costs,pip_size=pip_size)

    selected={}
    selected["D1_STAGGERED"],_=gate_with_stale_reentry_probation(
        "D1_STAGGERED",streams["D1_STAGGERED"],species_frame=species,trading_dates=dates,change_points=change_points
    )
    for name in ("M15_L12","M15_L20"):
        selected[name],_=gate_m15_exceptional_health(
            name,streams[name],exceptional_frame=exceptional,trading_dates=dates,change_points=change_points
        )

    core=tuple(streams["D1_CLASSIC"])
    sats=tuple(t for name in SATELLITES for t in selected[name])
    selector=_limit_concurrency(_dedupe_with_classic((*core,*sats)))
    return core,selector,selected


def evaluate_v111(
    rows:Sequence[Bar],*,evaluation_start,evaluation_end,pip_size:float,
    cost_scenarios:Mapping[str,Any],
)->dict[str,Any]:
    start=ensure_utc(evaluation_start);end=ensure_utc(evaluation_end)
    bars=tuple(sorted(rows,key=lambda x:ensure_utc(x.timestamp)))
    scenario_results={}

    for cost_id,costs in cost_scenarios.items():
        core_all,selector_all,selected=assemble_v110_selector(
            bars,costs=costs,pip_size=pip_size,evaluation_end=end
        )
        core=_period(core_all,start,end)
        selector=_period(selector_all,start,end)

        annual={}
        for y in range(start.year,end.year+1):
            ys=datetime(y,1,1,tzinfo=start.tzinfo)
            ye=min(datetime(y+1,1,1,tzinfo=start.tzinfo),end)
            if ys>=end:continue
            annual[str(y)]={
                "core":_metrics(_period(core_all,ys,ye)),
                "selector":_metrics(_period(selector_all,ys,ye)),
                "selected_contribution":{
                    name:_metrics(_period(trades,ys,ye))
                    for name,trades in selected.items()
                },
            }

        start_sensitivity={}
        for y in START_SENSITIVITY_YEARS:
            ss=max(start,datetime(y,1,1,tzinfo=start.tzinfo))
            if ss>=end:continue
            start_sensitivity[str(y)]={
                "core":_metrics(_period(core_all,ss,end)),
                "selector":_metrics(_period(selector_all,ss,end)),
            }

        yearly_net={y:_net_r(x["selector"]) for y,x in annual.items()}
        positive_total=sum(v for v in yearly_net.values() if v>0.0)
        best_year=max(yearly_net,key=yearly_net.get) if yearly_net else None
        best_net=None if best_year is None else yearly_net[best_year]
        concentration={
            "yearly_selector_net_r":yearly_net,
            "best_year":best_year,
            "best_year_net_r":best_net,
            "best_year_share_of_positive_net_r":(
                None if best_net is None or positive_total<=0 else float(best_net/positive_total)
            ),
            "positive_years":sum(1 for v in yearly_net.values() if v>0),
            "negative_years":sum(1 for v in yearly_net.values() if v<0),
        }

        y2025=datetime(2025,1,1,tzinfo=start.tzinfo)
        cash_2025=None
        if y2025<end:
            # Keep optional market-data runtime dependencies out of import-time
            # paths used by the pure selector and the normal unit-test suite.
            from .research_xau_hierarchical_regime_router_v35_runtime import BROKER_SPEC, LEVERAGE_TIERS
            trades_2025=_period(selector_all,y2025,end)
            dates_2025=_trading_dates(bars,start=y2025,end=end)
            cash_2025=_cash_path_stopout_safe(
                trades_2025,spec=BROKER_SPEC,tiers=LEVERAGE_TIERS,
                account_leverage=ACCOUNT_LEVERAGE,stopout_pct=MARGIN_FLOOR_PCT,
                trading_dates=dates_2025,
            )

        scenario_results[cost_id]={
            "full":{"core":_metrics(core),"selector":_metrics(selector)},
            "annual":annual,
            "start_sensitivity":start_sensitivity,
            "profit_concentration":concentration,
            "cash_fresh_100_2025YTD":cash_2025,
        }

    return {
        "research_version":RESEARCH_VERSION,
        "artifact_contract":ARTIFACT_CONTRACT,
        "policy_effect":POLICY_EFFECT,
        "execution_influence":EXECUTION_INFLUENCE,
        "promotion_eligible":PROMOTION_ELIGIBLE,
        "live_execution_enabled":False,
        "contract":{
            "selector_rules":"frozen V110",
            "strategy_changes":False,
            "cost_scenarios":list(cost_scenarios.keys()),
            "start_sensitivity_years":list(START_SENSITIVITY_YEARS),
            "calendar_years":"evaluation attribution only",
            "parameter_search":False,
        },
        "scenario_results":scenario_results,
        "note":"V111 changes no selector rule. It evaluates frozen V110 under existing cost scenarios, yearly slices, start-date sensitivity, and profit concentration.",
    }

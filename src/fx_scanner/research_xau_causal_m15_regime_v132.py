from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Sequence

import pandas as pd

from .demo_donchian_adaptive_tournament import TournamentTrade, compute_metrics
from .models import Bar, ensure_utc
from .research_xau_2025_bootstrap_onset_forensic_v122 import build_v122_feature_frame
from .research_xau_capital_compatibility_v129 import _simulate
from .research_xau_champion_onset_reaccel_v123 import build_reaccel_route_frame
from .research_xau_false_onset_forensic_v125 import annotate_compressed_epochs
from .research_xau_multihorizon_100usd_v20 import _dedupe, _limit_concurrency, _portfolio_candidates
from .research_xau_qualitative_reaccel_gate_v126 import passes_qualitative_gate
from .research_xau_v110_robustness_v111 import assemble_v110_selector

RESEARCH_VERSION="XAU_CAUSAL_M15_REGIME_V132"
ARTIFACT_CONTRACT="XAU_CAUSAL_M15_REGIME_V132_EVIDENCE_1"
POLICY_EFFECT="SHADOW_ONLY"
EXECUTION_INFLUENCE=False
PROMOTION_ELIGIBLE=False

START=datetime(2012,1,1,tzinfo=timezone.utc)
ERA_WINDOWS=(
    ("2012_2018",datetime(2012,1,1,tzinfo=timezone.utc),datetime(2019,1,1,tzinfo=timezone.utc)),
    ("2019_2024",datetime(2019,1,1,tzinfo=timezone.utc),datetime(2025,1,1,tzinfo=timezone.utc)),
)
START_SENSITIVITY=(
    ("2012",datetime(2012,1,1,tzinfo=timezone.utc)),
    ("2019",datetime(2019,1,1,tzinfo=timezone.utc)),
    ("2022",datetime(2022,1,1,tzinfo=timezone.utc)),
    ("2025",datetime(2025,1,1,tzinfo=timezone.utc)),
)


def _f(rec: Mapping[str,Any], key: str) -> float:
    try:
        return float(rec.get(key))
    except (TypeError, ValueError):
        return float("nan")


def _triple_contraction(rec: Mapping[str,Any]) -> bool:
    return (
        _f(rec,"d20_pct_atr14_pct") < 0.0
        and _f(rec,"d20_pct_atr_ratio_252") < 0.0
        and _f(rec,"d20_pct_range20_atr") < 0.0
    )


def _candidate_predicates() -> dict[str,Callable[[Mapping[str,Any]],bool]]:
    return {
        # Forensic finding only: shorts were destructive in V131.
        "C0_V126_LONG_ONLY": lambda r: str(r.get("side","")).upper()=="LONG",
        # Symmetric control: asks whether contraction itself, not direction, is sufficient.
        "C1_V126_SYMMETRIC_20D_TRIPLE_CONTRACTION": lambda r: _triple_contraction(r),
        # Direction + contraction mechanistic hypothesis.
        "C2_V126_LONG_20D_TRIPLE_CONTRACTION": lambda r: (
            str(r.get("side","")).upper()=="LONG" and _triple_contraction(r)
        ),
        # Add only a structural median-percentile distance condition, not a tuned value.
        "C3_V126_LONG_20D_TRIPLE_CONTRACTION_DISTANCE50": lambda r: (
            str(r.get("side","")).upper()=="LONG"
            and _triple_contraction(r)
            and _f(r,"pct_ema200_distance_atr") >= 0.50
        ),
    }


def _metrics(trades: Sequence[TournamentTrade]) -> dict[str,Any]:
    return compute_metrics(tuple(trades)).payload()


def _period(trades: Sequence[TournamentTrade], start, end) -> tuple[TournamentTrade,...]:
    a=ensure_utc(start); b=ensure_utc(end)
    return tuple(t for t in trades if a<=ensure_utc(t.entry_at)<b)


def _epoch_window(rec: Mapping[str,Any], end) -> tuple:
    a=ensure_utc(pd.Timestamp(rec["start"]).to_pydatetime())
    b=ensure_utc(end) if rec.get("end_exclusive") is None else ensure_utc(pd.Timestamp(rec["end_exclusive"]).to_pydatetime())
    return a,b,str(rec.get("side","")).upper()


def _route(
    trades: Sequence[TournamentTrade],
    records: Sequence[Mapping[str,Any]],
    *,
    end,
    predicate: Callable[[Mapping[str,Any]],bool],
) -> tuple[TournamentTrade,...]:
    windows=[]
    for rec in records:
        if not passes_qualitative_gate(rec):
            continue
        if not predicate(rec):
            continue
        windows.append(_epoch_window(rec,end))
    kept=[]
    for t in sorted(trades,key=lambda x:ensure_utc(x.entry_at)):
        at=ensure_utc(t.entry_at)
        side=str(t.direction).upper()
        if any(a<=at<b and side==s for a,b,s in windows):
            kept.append(t)
    return tuple(kept)


def _scenario(
    trades: Sequence[TournamentTrade],
    *,
    broker_spec,
    leverage_tiers,
) -> dict[str,Any]:
    # User-selected active research/runtime policy: margin-free cap 50%.
    return {
        "LIVE_100_1_100_CAP50": _simulate(
            trades,
            spec=broker_spec,
            tiers=leverage_tiers,
            starting_balance=100.0,
            account_leverage=100.0,
            margin_cap_pct=50.0,
        ),
        "DEMO_342_1_30_CAP50": _simulate(
            trades,
            spec=broker_spec,
            tiers=leverage_tiers,
            starting_balance=342.0,
            account_leverage=30.0,
            margin_cap_pct=50.0,
        ),
    }


def _summary(
    trades: Sequence[TournamentTrade],
    *,
    end,
    broker_spec,
    leverage_tiers,
) -> dict[str,Any]:
    full=_period(trades,START,end)
    eras={}
    for label,a,b in ERA_WINDOWS:
        vals=_period(trades,a,b)
        eras[label]={"metrics":_metrics(vals),"scenarios":_scenario(vals,broker_spec=broker_spec,leverage_tiers=leverage_tiers)}
    recent=_period(trades,datetime(2025,1,1,tzinfo=timezone.utc),end)
    eras["2025_2026YTD"]={"metrics":_metrics(recent),"scenarios":_scenario(recent,broker_spec=broker_spec,leverage_tiers=leverage_tiers)}
    starts={}
    for label,start in START_SENSITIVITY:
        vals=_period(trades,start,end)
        starts[label]={"metrics":_metrics(vals),"scenarios":_scenario(vals,broker_spec=broker_spec,leverage_tiers=leverage_tiers)}
    return {
        "full_metrics":_metrics(full),
        "full_scenarios":_scenario(full,broker_spec=broker_spec,leverage_tiers=leverage_tiers),
        "eras":eras,
        "start_sensitivity":starts,
    }


def evaluate_v132(
    rows: Sequence[Bar],
    *,
    evaluation_end,
    pip_size: float,
    costs,
    broker_spec,
    leverage_tiers,
) -> dict[str,Any]:
    bars=tuple(sorted(rows,key=lambda x:ensure_utc(x.timestamp)))
    end=ensure_utc(evaluation_end)

    candidates=_portfolio_candidates(
        bars,base_costs=costs,stressed_costs=costs,pip_size=pip_size
    )
    raw_l12=tuple(candidates["M15_L12_ONLY"]["stress"])
    raw_l20=tuple(candidates["M15_L20_ONLY"]["stress"])
    raw_combined=_limit_concurrency(_dedupe((*raw_l12,*raw_l20)))

    frame=build_v122_feature_frame(bars)
    _,epoch_defs=build_reaccel_route_frame(frame,route_id="COMPRESSED_REACCEL")
    _,selector_all,_=assemble_v110_selector(
        bars,costs=costs,pip_size=pip_size,evaluation_end=end
    )
    records=annotate_compressed_epochs(frame,epoch_defs,selector_all)

    preds=_candidate_predicates()
    routed={
        cid:_route(raw_combined,records,end=end,predicate=pred)
        for cid,pred in preds.items()
    }

    return {
        "research_version":RESEARCH_VERSION,
        "artifact_contract":ARTIFACT_CONTRACT,
        "policy_effect":POLICY_EFFECT,
        "execution_influence":EXECUTION_INFLUENCE,
        "promotion_eligible":PROMOTION_ELIGIBLE,
        "live_execution_enabled":False,
        "contract":{
            "source":"V131 forensic hypotheses; frozen before V132 results",
            "signal_family":"exact V24 raw M15 L12+L20 combined",
            "base_gate":"exact frozen V126 causal epoch gate",
            "candidate_count":len(preds),
            "threshold_grid_search":False,
            "calendar_routing":False,
            "future_outcome_routing":False,
            "margin_free_usage_cap_pct":50.0,
            "per_trade_risk_pct":20.0,
            "aggregate_risk_pct":20.0,
            "minimum_lot":0.01,
            "execution_authority":False,
        },
        "acceptance_criteria":{
            "full_min_trades":100,
            "full_min_pf":1.15,
            "full_min_expectancy_r":0.05,
            "full_max_drawdown_r":20.0,
            "each_pre2025_era_min_expectancy_r":0.0,
            "recent_min_pf":1.30,
            "recent_min_expectancy_r":0.10,
            "live100_recent_min_opened":30,
            "live100_recent_min_pf":1.20,
            "live100_recent_min_expectancy_r":0.0,
            "live100_recent_min_ending_balance":100.0,
        },
        "candidates":{
            cid:{
                "epoch_count":sum(
                    1 for rec in records
                    if passes_qualitative_gate(rec) and preds[cid](rec)
                ),
                **_summary(
                    trades,end=end,broker_spec=broker_spec,leverage_tiers=leverage_tiers
                ),
            }
            for cid,trades in routed.items()
        },
        "note":"V132 is falsification only. Passing criteria creates a candidate for later walk-forward/prospective validation, not promotion.",
    }

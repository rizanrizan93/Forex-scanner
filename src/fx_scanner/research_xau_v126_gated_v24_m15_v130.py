from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

import pandas as pd

from .demo_donchian_adaptive_tournament import TournamentTrade, compute_metrics
from .models import Bar, ensure_utc
from .research_xau_2025_bootstrap_onset_forensic_v122 import build_v122_feature_frame
from .research_xau_capital_compatibility_v129 import _simulate
from .research_xau_champion_onset_reaccel_v123 import build_reaccel_route_frame
from .research_xau_false_onset_forensic_v125 import annotate_compressed_epochs
from .research_xau_multihorizon_100usd_v20 import (
    M15_VARIANTS,
    _dedupe,
    _limit_concurrency,
    _portfolio_candidates,
)
from .research_xau_qualitative_reaccel_gate_v126 import passes_qualitative_gate
from .research_xau_v110_robustness_v111 import assemble_v110_selector

RESEARCH_VERSION="XAU_V126_GATED_V24_M15_V130"
ARTIFACT_CONTRACT="XAU_V126_GATED_V24_M15_V130_EVIDENCE_1"
POLICY_EFFECT="SHADOW_ONLY"
EXECUTION_INFLUENCE=False
PROMOTION_ELIGIBLE=False

START=datetime(2012,1,1,tzinfo=timezone.utc)
CAPS=(25.0,50.0)
ACCOUNT_SCENARIOS=(
    ("LIVE_100_1_100",100.0,100.0),
    ("DEMO_342_1_30",342.0,30.0),
)
WINDOWS=(
    ("2012_2018",datetime(2012,1,1,tzinfo=timezone.utc),datetime(2019,1,1,tzinfo=timezone.utc)),
    ("2019_2024",datetime(2019,1,1,tzinfo=timezone.utc),datetime(2025,1,1,tzinfo=timezone.utc)),
)
START_SENSITIVITY=(
    ("2012",datetime(2012,1,1,tzinfo=timezone.utc)),
    ("2019",datetime(2019,1,1,tzinfo=timezone.utc)),
    ("2022",datetime(2022,1,1,tzinfo=timezone.utc)),
    ("2025",datetime(2025,1,1,tzinfo=timezone.utc)),
)


def _metrics(trades:Sequence[TournamentTrade])->dict[str,Any]:
    return compute_metrics(tuple(trades)).payload()


def _period(trades:Sequence[TournamentTrade],start,end)->tuple[TournamentTrade,...]:
    a=ensure_utc(start);b=ensure_utc(end)
    return tuple(t for t in trades if a<=ensure_utc(t.entry_at)<b)


def _route_raw_m15(
    trades:Sequence[TournamentTrade],
    epoch_records:Sequence[Mapping[str,Any]],
    *,
    end,
)->tuple[TournamentTrade,...]:
    finish=ensure_utc(end)
    windows=[]
    for rec in epoch_records:
        if not passes_qualitative_gate(rec):
            continue
        a=ensure_utc(pd.Timestamp(rec["start"]).to_pydatetime())
        b=finish if rec.get("end_exclusive") is None else ensure_utc(pd.Timestamp(rec["end_exclusive"]).to_pydatetime())
        side=str(rec["side"]).upper()
        windows.append((a,b,side))

    kept=[]
    for t in sorted(trades,key=lambda x:ensure_utc(x.entry_at)):
        at=ensure_utc(t.entry_at)
        side=str(t.direction).upper()
        if any(a<=at<b and side==s for a,b,s in windows):
            kept.append(t)
    return tuple(kept)


def _scenario_matrix(
    trades:Sequence[TournamentTrade],
    *,
    broker_spec,
    leverage_tiers,
)->dict[str,Any]:
    out={}
    for aid,balance,lev in ACCOUNT_SCENARIOS:
        out[aid]={}
        for cap in CAPS:
            out[aid][str(int(cap))]=_simulate(
                trades,
                spec=broker_spec,
                tiers=leverage_tiers,
                starting_balance=balance,
                account_leverage=lev,
                margin_cap_pct=cap,
            )
    return out


def _summary(
    trades:Sequence[TournamentTrade],
    *,
    end,
    broker_spec,
    leverage_tiers,
)->dict[str,Any]:
    eras={}
    for label,a,b in WINDOWS:
        vals=_period(trades,a,b)
        eras[label]={
            "metrics":_metrics(vals),
            "scenarios":_scenario_matrix(vals,broker_spec=broker_spec,leverage_tiers=leverage_tiers),
        }
    vals=_period(trades,datetime(2025,1,1,tzinfo=timezone.utc),end)
    eras["2025_2026YTD"]={
        "metrics":_metrics(vals),
        "scenarios":_scenario_matrix(vals,broker_spec=broker_spec,leverage_tiers=leverage_tiers),
    }

    start_sensitivity={}
    for label,start in START_SENSITIVITY:
        vals=_period(trades,start,end)
        start_sensitivity[label]={
            "metrics":_metrics(vals),
            "scenarios":_scenario_matrix(vals,broker_spec=broker_spec,leverage_tiers=leverage_tiers),
        }

    return {
        "full_metrics":_metrics(_period(trades,START,end)),
        "full_scenarios":_scenario_matrix(
            _period(trades,START,end),
            broker_spec=broker_spec,
            leverage_tiers=leverage_tiers,
        ),
        "eras":eras,
        "start_sensitivity":start_sensitivity,
    }


def evaluate_v130(
    rows:Sequence[Bar],
    *,
    evaluation_end,
    pip_size:float,
    costs,
    broker_spec,
    leverage_tiers,
)->dict[str,Any]:
    bars=tuple(sorted(rows,key=lambda x:ensure_utc(x.timestamp)))
    end=ensure_utc(evaluation_end)

    candidates=_portfolio_candidates(
        bars,base_costs=costs,stressed_costs=costs,pip_size=pip_size
    )
    exact_all=candidates["D1_PLUS_L12_L20"]["stress"]
    l12_id=M15_VARIANTS[0].variant_id
    l20_id=M15_VARIANTS[1].variant_id
    raw_l12=tuple(t for t in exact_all if str(t.strategy_id)==l12_id)
    raw_l20=tuple(t for t in exact_all if str(t.strategy_id)==l20_id)

    frame=build_v122_feature_frame(bars)
    _,epoch_defs=build_reaccel_route_frame(frame,route_id="COMPRESSED_REACCEL")
    # V110 is used only to annotate the already-frozen V126 epoch records.
    # Trade outcomes in those annotations do not participate in gate decisions.
    _,selector_all,_=assemble_v110_selector(
        bars,costs=costs,pip_size=pip_size,evaluation_end=end
    )
    epoch_records=annotate_compressed_epochs(frame,epoch_defs,selector_all)
    eligible_epochs=tuple(r for r in epoch_records if passes_qualitative_gate(r))

    gated_l12=_route_raw_m15(raw_l12,epoch_records,end=end)
    gated_l20=_route_raw_m15(raw_l20,epoch_records,end=end)

    raw_combined=_limit_concurrency(_dedupe((*raw_l12,*raw_l20)))
    gated_combined=_limit_concurrency(_dedupe((*gated_l12,*gated_l20)))

    portfolios={
        "RAW_V24_M15_L12":raw_l12,
        "RAW_V24_M15_L20":raw_l20,
        "RAW_V24_M15_COMBINED":raw_combined,
        "V126_GATED_RAW_L12":gated_l12,
        "V126_GATED_RAW_L20":gated_l20,
        "V126_GATED_RAW_M15_COMBINED":gated_combined,
    }

    result={
        pid:_summary(
            trades,end=end,broker_spec=broker_spec,leverage_tiers=leverage_tiers
        )
        for pid,trades in portfolios.items()
    }

    return {
        "research_version":RESEARCH_VERSION,
        "artifact_contract":ARTIFACT_CONTRACT,
        "policy_effect":POLICY_EFFECT,
        "execution_influence":EXECUTION_INFLUENCE,
        "promotion_eligible":PROMOTION_ELIGIBLE,
        "live_execution_enabled":False,
        "contract":{
            "execution_family":"M15 only; D1 never executed in V130",
            "raw_signal_source":"exact frozen V24 M15 L12/L20",
            "causal_gate":"exact frozen V126 MEDIAN_COMPRESSION_REACCEL epochs",
            "gate_thresholds_changed":False,
            "v110_health_gate_used_for_raw_m15":False,
            "d1_state_used_only_as_context_gate":True,
            "margin_caps_pct":[25,50],
            "margin_cap_50_is_diagnostic_only":True,
            "per_trade_risk_pct":20.0,
            "aggregate_risk_pct":20.0,
            "minimum_lot":0.01,
            "parameter_grid_search":False,
            "calendar_year_used_for_routing":False,
            "future_outcomes_used_for_routing":False,
            "execution_authority":False,
        },
        "eligible_v126_epoch_count":len(eligible_epochs),
        "eligible_v126_epochs":[
            {"start":r["start"],"end_exclusive":r["end_exclusive"],"side":r["side"]}
            for r in eligible_epochs
        ],
        "portfolios":result,
        "note":(
            "V130 tests whether the already-frozen V126 market-state gate can make the exact raw "
            "V24 M15 family robust enough for small-account use without executing D1 trades. "
            "No margin-cap or strategy change receives promotion authority here."
        ),
    }

from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from .demo_donchian_adaptive_tournament import TournamentTrade, compute_metrics
from .models import Bar, ensure_utc
from .research_xau_2025_bootstrap_onset_forensic_v122 import build_v122_feature_frame
from .research_xau_champion_onset_reaccel_v123 import build_reaccel_route_frame
from .research_xau_false_onset_forensic_v125 import (
    LEVEL_FEATURES,
    NORMALIZED_FEATURES,
    TRAJECTORY_LAGS,
    annotate_compressed_epochs,
)
from .research_xau_multihorizon_100usd_v20 import (
    _dedupe,
    _limit_concurrency,
    _portfolio_candidates,
)
from .research_xau_qualitative_reaccel_gate_v126 import passes_qualitative_gate
from .research_xau_v110_robustness_v111 import assemble_v110_selector

RESEARCH_VERSION="XAU_V130_EPOCH_FORENSIC_V131"
ARTIFACT_CONTRACT="XAU_V130_EPOCH_FORENSIC_V131_EVIDENCE_1"
POLICY_EFFECT="SHADOW_ONLY"
EXECUTION_INFLUENCE=False
PROMOTION_ELIGIBLE=False

FEATURE_KEYS=tuple(LEVEL_FEATURES)+tuple(
    f"d{lag}_{feature}"
    for lag in TRAJECTORY_LAGS
    for feature in NORMALIZED_FEATURES
)


def _metrics(trades:Sequence[TournamentTrade])->dict[str,Any]:
    return compute_metrics(tuple(trades)).payload()


def _net(m:Mapping[str,Any])->float:
    return float(m.get("gross_profit_r",0.0))-float(m.get("gross_loss_r",0.0))


def _finite(x:Any)->float|None:
    try:
        v=float(x)
    except (TypeError,ValueError):
        return None
    return v if isfinite(v) else None


def _robust_effect(
    a:Sequence[Mapping[str,Any]],
    b:Sequence[Mapping[str,Any]],
    key:str,
)->float|None:
    xa=np.asarray([v for v in (_finite(r.get(key)) for r in a) if v is not None],dtype=float)
    xb=np.asarray([v for v in (_finite(r.get(key)) for r in b) if v is not None],dtype=float)
    if len(xa)==0 or len(xb)==0:
        return None
    pooled=np.concatenate([xa,xb])
    med=float(np.median(pooled))
    mad=float(np.median(np.abs(pooled-med)))
    if not isfinite(mad) or mad<=1e-12:
        return None
    return float((np.median(xa)-np.median(xb))/(1.4826*mad))


def _era(ts)->str:
    t=ensure_utc(ts)
    if t<datetime(2019,1,1,tzinfo=timezone.utc):
        return "2012_2018"
    if t<datetime(2025,1,1,tzinfo=timezone.utc):
        return "2019_2024"
    return "2025_2026YTD"


def _epoch_trades(
    trades:Sequence[TournamentTrade],
    rec:Mapping[str,Any],
    *,
    end,
)->tuple[TournamentTrade,...]:
    a=ensure_utc(pd.Timestamp(rec["start"]).to_pydatetime())
    b=ensure_utc(end) if rec.get("end_exclusive") is None else ensure_utc(pd.Timestamp(rec["end_exclusive"]).to_pydatetime())
    side=str(rec["side"]).upper()
    return tuple(
        t for t in trades
        if a<=ensure_utc(t.entry_at)<b and str(t.direction).upper()==side
    )


def evaluate_v131(
    rows:Sequence[Bar],
    *,
    evaluation_end,
    pip_size:float,
    costs,
)->dict[str,Any]:
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
    eligible=tuple(r for r in records if passes_qualitative_gate(r))

    epoch_rows=[]
    for rec in eligible:
        vals=_epoch_trades(raw_combined,rec,end=end)
        m=_metrics(vals)
        start=ensure_utc(pd.Timestamp(rec["start"]).to_pydatetime())
        finish=end if rec.get("end_exclusive") is None else ensure_utc(pd.Timestamp(rec["end_exclusive"]).to_pydatetime())
        row={
            "start":start.isoformat(),
            "end_exclusive":None if rec.get("end_exclusive") is None else finish.isoformat(),
            "duration_days":float((finish-start).total_seconds()/86400.0),
            "side":str(rec["side"]).upper(),
            "era":_era(start),
            "trade_count":int(m["completed_trades"]),
            "profit_factor":m["profit_factor"],
            "expectancy_r":m["expectancy_r"],
            "net_r":_net(m),
            "max_drawdown_r":m["max_drawdown_r"],
            "outcome":(
                "NO_TRADES" if int(m["completed_trades"])==0
                else ("POSITIVE" if _net(m)>0 else "NONPOSITIVE")
            ),
            "state":rec.get("state"),
            "species":rec.get("species"),
            "raw_state":rec.get("raw_state"),
            "direction_state":rec.get("direction_state"),
        }
        for key in FEATURE_KEYS:
            row[key]=rec.get(key)
        epoch_rows.append(row)

    by_side={}
    for side in ("LONG","SHORT"):
        vals=[]
        for rec in eligible:
            if str(rec["side"]).upper()!=side:
                continue
            vals.extend(_epoch_trades(raw_combined,rec,end=end))
        by_side[side]=_metrics(tuple(vals))

    by_era={}
    for label in ("2012_2018","2019_2024","2025_2026YTD"):
        vals=[]
        for rec in eligible:
            if _era(pd.Timestamp(rec["start"]).to_pydatetime())!=label:
                continue
            vals.extend(_epoch_trades(raw_combined,rec,end=end))
        by_era[label]=_metrics(tuple(vals))

    categorical={}
    for key in ("state","species","raw_state","direction_state"):
        groups={}
        for value in sorted({str(r.get(key) or "NONE") for r in epoch_rows}):
            subset=[r for r in epoch_rows if str(r.get(key) or "NONE")==value]
            groups[value]={
                "epochs":len(subset),
                "positive_epochs":sum(r["outcome"]=="POSITIVE" for r in subset),
                "nonpositive_epochs":sum(r["outcome"]=="NONPOSITIVE" for r in subset),
                "trades":sum(int(r["trade_count"]) for r in subset),
                "net_r":sum(float(r["net_r"]) for r in subset),
            }
        categorical[key]=groups

    pre=[r for r in epoch_rows if r["era"]!="2025_2026YTD" and r["outcome"]!="NO_TRADES"]
    pre_pos=[r for r in pre if r["outcome"]=="POSITIVE"]
    pre_bad=[r for r in pre if r["outcome"]=="NONPOSITIVE"]
    recent=[r for r in epoch_rows if r["era"]=="2025_2026YTD" and r["outcome"]!="NO_TRADES"]

    effects_pre={
        key:_robust_effect(pre_pos,pre_bad,key)
        for key in FEATURE_KEYS
    }
    ranked_pre=sorted(FEATURE_KEYS,key=lambda k:abs(effects_pre[k] or 0.0),reverse=True)

    effects_recent_vs_prebad={
        key:_robust_effect(recent,pre_bad,key)
        for key in FEATURE_KEYS
    }
    ranked_recent=sorted(FEATURE_KEYS,key=lambda k:abs(effects_recent_vs_prebad[k] or 0.0),reverse=True)

    return {
        "research_version":RESEARCH_VERSION,
        "artifact_contract":ARTIFACT_CONTRACT,
        "policy_effect":POLICY_EFFECT,
        "execution_influence":EXECUTION_INFLUENCE,
        "promotion_eligible":PROMOTION_ELIGIBLE,
        "live_execution_enabled":False,
        "contract":{
            "purpose":"forensic attribution of V130 failure by frozen V126 epoch",
            "signal_family":"exact raw V24 M15 L12+L20 combined",
            "gate":"exact frozen V126 MEDIAN_COMPRESSION_REACCEL",
            "future_outcome_used_only_as_forensic_label":True,
            "threshold_selection":False,
            "parameter_grid_search":False,
            "calendar_year_used_for_execution":False,
            "execution_authority":False,
        },
        "eligible_epoch_count":len(epoch_rows),
        "counts":{
            "pre_positive":len(pre_pos),
            "pre_nonpositive":len(pre_bad),
            "recent_epochs_with_trades":len(recent),
            "long_epochs":sum(r["side"]=="LONG" for r in epoch_rows),
            "short_epochs":sum(r["side"]=="SHORT" for r in epoch_rows),
        },
        "by_side":by_side,
        "by_era":by_era,
        "categorical":categorical,
        "effect_pre_positive_vs_nonpositive":effects_pre,
        "ranked_pre_separator_features":ranked_pre,
        "effect_recent_vs_pre_nonpositive":effects_recent_vs_prebad,
        "ranked_recent_vs_prebad_features":ranked_recent,
        "epochs":epoch_rows,
        "note":(
            "V131 is forensic only. It identifies whether V130's historical failure is concentrated "
            "by direction, onset category, or causal normalized feature trajectory. No discovered "
            "feature or side receives routing authority."
        ),
    }

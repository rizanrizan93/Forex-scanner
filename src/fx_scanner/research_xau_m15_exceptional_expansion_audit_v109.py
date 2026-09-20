from __future__ import annotations

from bisect import bisect_right
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from .demo_donchian_adaptive_tournament import TournamentTrade, compute_metrics
from .models import Bar, ensure_utc
from .research_xau_causal_era_selector_v98 import (
    EXPANSION_SCORE_THRESHOLD,
    RANK_LOOKBACK_DAYS,
    RANK_MIN_HISTORY_DAYS,
    STATE_FEATURES,
    _pct_rank,
    _strategy_streams,
    build_causal_state_frame,
)
from .research_xau_m15_dual_strategy import M15ResearchCosts

RESEARCH_VERSION="XAU_M15_EXCEPTIONAL_EXPANSION_AUDIT_V109"
ARTIFACT_CONTRACT="XAU_M15_EXCEPTIONAL_EXPANSION_AUDIT_V109_EVIDENCE_1"
POLICY_EFFECT="SHADOW_ONLY"
EXECUTION_INFLUENCE=False
PROMOTION_ELIGIBLE=False
AUDIT_STRATEGIES=("M15_L12","M15_L20")


class _Asof:
    def __init__(self,frame:pd.DataFrame):
        self.frame=frame.reset_index(drop=True)
        self.times=[ensure_utc(x) for x in self.frame["available_at"]]
    def row(self,timestamp):
        i=bisect_right(self.times,ensure_utc(timestamp))-1
        if i<0:return None
        return self.frame.iloc[i].to_dict()


def build_exceptional_frame(rows:Sequence[Bar])->pd.DataFrame:
    x=build_causal_state_frame(rows).copy().sort_values("available_at").reset_index(drop=True)
    rank_cols={f:[] for f in STATE_FEATURES}
    unanimous=[]
    for i in range(len(x)):
        ranks=[]
        for f in STATE_FEATURES:
            v=float(x.loc[i,f]) if pd.notna(x.loc[i,f]) else float("nan")
            hist=x.loc[max(0,i-RANK_LOOKBACK_DAYS):i-1,f].to_numpy(dtype=float) if i>0 else np.array([])
            r=_pct_rank(v,hist)
            rank_cols[f].append(r)
            if r is not None:ranks.append(r)
        state=str(x.loc[i,"state"])
        is_expansion=state in {"BULL_EXPANSION","BEAR_EXPANSION"}
        unanimous.append(
            bool(
                is_expansion
                and len(ranks)==len(STATE_FEATURES)
                and all(float(r)>=EXPANSION_SCORE_THRESHOLD for r in ranks)
            )
        )
    for f,vals in rank_cols.items():
        x[f"rank_{f}"]=vals
    x["unanimous_extreme_expansion"]=unanimous
    return x


def _metrics(trades:Sequence[TournamentTrade])->dict[str,Any]:
    return compute_metrics(tuple(trades)).payload()


def _bucket_trade(t:TournamentTrade,row:Mapping[str,Any]|None)->str:
    if row is None:return "OTHER"
    state=str(row.get("state") or "")
    direction=str(t.direction).upper()
    direction_match=(state.startswith("BULL_") and direction=="LONG") or (state.startswith("BEAR_") and direction=="SHORT")
    if not direction_match:return "OTHER"
    if bool(row.get("unanimous_extreme_expansion")):
        return "UNANIMOUS_EXTREME"
    if state in {"BULL_EXPANSION","BEAR_EXPANSION"}:
        return "OTHER_EXPANSION"
    return "OTHER"


def audit_v109(
    rows:Sequence[Bar],*,costs:M15ResearchCosts,pip_size:float,evaluation_end,
    era_windows:Mapping[str,tuple[Any,Any]],
)->dict[str,Any]:
    bars=tuple(sorted(rows,key=lambda x:ensure_utc(x.timestamp)))
    frame=build_exceptional_frame(bars)
    lookup=_Asof(frame)
    streams=_strategy_streams(bars,costs=costs,pip_size=pip_size)

    out={}
    for name in AUDIT_STRATEGIES:
        trades=tuple(t for t in streams[name] if ensure_utc(t.entry_at)<ensure_utc(evaluation_end))
        era_out={}
        for era,(a,b) in era_windows.items():
            aa=ensure_utc(a);bb=ensure_utc(b)
            buckets={"UNANIMOUS_EXTREME":[],"OTHER_EXPANSION":[],"OTHER":[]}
            for t in trades:
                if not (aa<=ensure_utc(t.entry_at)<bb):continue
                buckets[_bucket_trade(t,lookup.row(t.signal_at))].append(t)
            era_out[era]={k:_metrics(v) for k,v in buckets.items()}
        out[name]=era_out

    incidence={}
    for era,(a,b) in era_windows.items():
        aa=ensure_utc(a);bb=ensure_utc(b)
        s=frame[(frame["available_at"]>=aa)&(frame["available_at"]<bb)]
        incidence[era]={
            "days":int(len(s)),
            "unanimous_extreme_days":int(s["unanimous_extreme_expansion"].sum()),
            "bull_expansion_days":int((s["state"]=="BULL_EXPANSION").sum()),
            "bear_expansion_days":int((s["state"]=="BEAR_EXPANSION").sum()),
        }

    return {
        "research_version":RESEARCH_VERSION,
        "artifact_contract":ARTIFACT_CONTRACT,
        "policy_effect":POLICY_EFFECT,
        "execution_influence":EXECUTION_INFLUENCE,
        "promotion_eligible":PROMOTION_ELIGIBLE,
        "contract":{
            "state_features":list(STATE_FEATURES),
            "threshold":EXPANSION_SCORE_THRESHOLD,
            "definition":"all four frozen V98 feature percentile ranks >= 0.75, direction-matched expansion",
            "new_numeric_threshold":False,
            "calendar_year_used_for_routing":False,
            "forensic_only":True,
        },
        "incidence_by_era":incidence,
        "strategy_attribution":out,
    }

from __future__ import annotations

from bisect import bisect_right
from datetime import datetime, time
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from .demo_donchian_adaptive_tournament import TournamentTrade, compute_metrics
from .models import Bar, ensure_utc
from .research_xau_100usd_stopout_v23 import _cash_path_stopout_safe
from .research_xau_changepoint_reset_router_v87 import (
    LOOKBACK_TRADING_DAYS,
    _date_cutoff,
    _trailing_health,
    detect_change_points,
)
from .research_xau_era_fingerprint_v97 import build_fingerprint_frame
from .research_xau_era_robustness_v31 import _dedupe_with_classic
from .research_xau_margin_leverage_v21 import LeverageTier
from .research_xau_multihorizon_100usd_v20 import (
    BrokerLotSpec,
    _limit_concurrency,
    _trading_dates,
)
from .research_xau_m15_dual_strategy import M15ResearchCosts
from .research_xau_causal_era_selector_v98 import (
    ACCOUNT_LEVERAGE,
    MARGIN_FLOOR_PCT,
    RANK_LOOKBACK_DAYS,
    RANK_MIN_HISTORY_DAYS,
    SATELLITES,
    _pct_rank,
    _strategy_streams,
    build_causal_state_frame,
)

RESEARCH_VERSION="XAU_EXPANSION_SPECIES_V99"
ARTIFACT_CONTRACT="XAU_EXPANSION_SPECIES_V99_EVIDENCE_1"
POLICY_EFFECT="SHADOW_ONLY"
EXECUTION_INFLUENCE=False
PROMOTION_ELIGIBLE=False

QUALITY_SCORE_THRESHOLD=0.60
QUALITY_CONFIRM_DAYS=3
QUALITY_FEATURES=(
    "efficiency20",
    "h1_adx14",
    "h1_ema20_50_spread_atr",
    "directional_close_position20",
)

class _Asof:
    def __init__(self,frame:pd.DataFrame):
        self.frame=frame.reset_index(drop=True)
        self.times=[ensure_utc(x) for x in self.frame["available_at"]]
    def row(self,timestamp)->Mapping[str,Any]|None:
        i=bisect_right(self.times,ensure_utc(timestamp))-1
        if i<0:return None
        return self.frame.iloc[i].to_dict()


def build_species_frame(rows:Sequence[Bar])->pd.DataFrame:
    base=build_causal_state_frame(rows).copy().sort_values("available_at").reset_index(drop=True)

    directional=[]
    for _,r in base.iterrows():
        state=str(r.get("state") or "")
        pos=float(r.get("close_position20",np.nan))
        if not np.isfinite(pos):
            directional.append(float("nan"))
        elif state.startswith("BULL_"):
            directional.append(pos)
        elif state.startswith("BEAR_"):
            directional.append(1.0-pos)
        else:
            directional.append(float("nan"))
    base["directional_close_position20"]=directional

    qs=[]
    raw_species=[]
    for i in range(len(base)):
        state=str(base.loc[i,"state"])
        if state not in {"BULL_EXPANSION","BEAR_EXPANSION"}:
            qs.append(float("nan"))
            raw_species.append(state)
            continue

        ranks=[]
        for f in QUALITY_FEATURES:
            v=float(base.loc[i,f]) if pd.notna(base.loc[i,f]) else float("nan")
            hist=base.loc[max(0,i-RANK_LOOKBACK_DAYS):i-1,f].to_numpy(dtype=float) if i>0 else np.array([])
            r=_pct_rank(v,hist)
            if r is not None:ranks.append(r)
        score=float(np.mean(ranks)) if len(ranks)==len(QUALITY_FEATURES) else float("nan")
        qs.append(score)
        side="BULL" if state.startswith("BULL_") else "BEAR"
        if not np.isfinite(score):
            raw_species=f"{side}_EXPANSION_UNCLASSIFIED"
        elif score>=QUALITY_SCORE_THRESHOLD:
            raw_species.append(f"{side}_STRUCTURAL_EXPANSION")
            continue
        else:
            raw_species.append(f"{side}_SHOCK_EXPANSION")
            continue

    # Fix append for the unclassified branch consistently.
    if len(raw_species)!=len(base):
        raise ValueError("V99_SPECIES_LENGTH_MISMATCH")

    confirmed=[]
    current="UNCLASSIFIED"
    pending=None
    run=0
    for raw in raw_species:
        if raw==current:
            pending=None;run=0
        elif raw==pending:
            run+=1
            if run>=QUALITY_CONFIRM_DAYS:
                current=raw
                pending=None;run=0
        else:
            pending=raw;run=1
        confirmed.append(current)

    base["quality_score"]=qs
    base["raw_species"]=raw_species
    base["species"]=confirmed
    return base


def _dir_matches_species(trade:TournamentTrade,species:str)->bool:
    d=str(trade.direction).upper()
    return (
        species=="BULL_STRUCTURAL_EXPANSION" and d=="LONG"
    ) or (
        species=="BEAR_STRUCTURAL_EXPANSION" and d=="SHORT"
    )


def gate_strategy_by_species_health(
    trades:Sequence[TournamentTrade],*,species_frame:pd.DataFrame,
    trading_dates:Sequence[Any],change_points:Sequence[Mapping[str,Any]],
)->tuple[tuple[TournamentTrade,...],dict[str,Any]]:
    lookup=_Asof(species_frame)
    ordered=tuple(sorted(trades,key=lambda t:ensure_utc(t.signal_at)))
    species={id(t):("UNCLASSIFIED" if lookup.row(t.signal_at) is None else str(lookup.row(t.signal_at).get("species") or "UNCLASSIFIED")) for t in ordered}
    cp_times=tuple(
        ensure_utc(pd.Timestamp(x["effective_at"]).to_pydatetime())
        for x in change_points
    )
    first_date=trading_dates[0] if trading_dates else ensure_utc(ordered[0].signal_at).date()
    first_epoch=datetime.combine(first_date,time.min,tzinfo=ensure_utc(ordered[0].signal_at).tzinfo)

    kept=[]
    structural_candidates=0
    by_species:dict[str,dict[str,int]]={}
    for trade in ordered:
        signal=ensure_utc(trade.signal_at)
        sp=species[id(trade)]
        if sp not in {"BULL_STRUCTURAL_EXPANSION","BEAR_STRUCTURAL_EXPANSION"} or not _dir_matches_species(trade,sp):
            continue
        structural_candidates+=1

        cp_pos=bisect_right(cp_times,signal)
        epoch_start=first_epoch if cp_pos==0 else cp_times[cp_pos-1]
        rolling_date=_date_cutoff(signal,trading_dates)
        rolling_start=datetime.combine(rolling_date,time.min,tzinfo=signal.tzinfo)
        history_start=max(epoch_start,rolling_start)

        prior=[
            x for x in ordered
            if ensure_utc(x.exit_at)<signal
            and ensure_utc(x.exit_at)>=history_start
            and species[id(x)]==sp
            and _dir_matches_species(x,sp)
        ]
        health=_trailing_health(prior)
        st=by_species.setdefault(sp,{"checks":0,"kept":0})
        st["checks"]+=1
        if health["active"]:
            kept.append(trade)
            st["kept"]+=1

    return tuple(kept),{
        "candidate_trades":len(ordered),
        "structural_direction_matched_candidates":structural_candidates,
        "kept_trades":len(kept),
        "suppressed_after_structural_filter":structural_candidates-len(kept),
        "by_species":by_species,
        "health_contract":{
            "lookback_trading_days":LOOKBACK_TRADING_DAYS,
            "reset_at_v87_change_points":True,
            "thresholds":"frozen V40/V47 via _trailing_health",
        },
    }


def _period(trades:Sequence[TournamentTrade],a,b)->tuple[TournamentTrade,...]:
    aa=ensure_utc(a);bb=ensure_utc(b)
    return tuple(t for t in trades if aa<=ensure_utc(t.entry_at)<bb)


def _metrics(trades)->dict[str,Any]:
    return compute_metrics(tuple(trades)).payload()


def _first_dates(frame:pd.DataFrame,start,end)->dict[str,str|None]:
    aa=ensure_utc(start);bb=ensure_utc(end)
    s=frame[(frame["available_at"]>=aa)&(frame["available_at"]<bb)]
    out={}
    for sp in ("BULL_STRUCTURAL_EXPANSION","BEAR_STRUCTURAL_EXPANSION","BULL_SHOCK_EXPANSION","BEAR_SHOCK_EXPANSION"):
        z=s[s["species"]==sp]
        out[sp]=None if z.empty else ensure_utc(z.iloc[0]["available_at"]).isoformat()
    return out


def evaluate_v99(
    bars:Sequence[Bar],*,evaluation_start,evaluation_end,pip_size:float,costs:M15ResearchCosts,
    broker_spec:BrokerLotSpec,leverage_tiers:Sequence[LeverageTier],
    era_windows:Mapping[str,tuple[Any,Any]],
)->dict[str,Any]:
    rows=tuple(sorted(bars,key=lambda x:ensure_utc(x.timestamp)))
    start=ensure_utc(evaluation_start);end=ensure_utc(evaluation_end)
    species=build_species_frame(rows)
    change_points=detect_change_points(build_fingerprint_frame(rows))
    dates=_trading_dates(rows,start=ensure_utc(rows[0].timestamp),end=end)
    streams=_strategy_streams(rows,costs=costs,pip_size=pip_size)

    selected={};gates={}
    for name in SATELLITES:
        selected[name],gates[name]=gate_strategy_by_species_health(
            streams[name],species_frame=species,trading_dates=dates,change_points=change_points
        )

    core=tuple(t for t in streams["D1_CLASSIC"] if start<=ensure_utc(t.entry_at)<end)
    sats=tuple(
        t for name in SATELLITES for t in selected[name]
        if start<=ensure_utc(t.entry_at)<end
    )
    selector=_limit_concurrency(_dedupe_with_classic((*core,*sats)))

    era_out={};state_counts={};first_species={}
    for era,(a,b) in era_windows.items():
        aa=ensure_utc(a);bb=ensure_utc(b)
        edates=_trading_dates(rows,start=aa,end=bb)
        core_e=_period(core,aa,bb)
        sel_e=_period(selector,aa,bb)
        s=species[(species["available_at"]>=aa)&(species["available_at"]<bb)]
        state_counts[era]={str(k):int(v) for k,v in s["species"].value_counts().to_dict().items()}
        first_species[era]=_first_dates(species,aa,bb)
        era_out[era]={
            "core":_metrics(core_e),
            "selector":_metrics(sel_e),
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
        "quality_contract":{
            "quality_features":list(QUALITY_FEATURES),
            "quality_score_threshold":QUALITY_SCORE_THRESHOLD,
            "quality_confirmation_days":QUALITY_CONFIRM_DAYS,
            "rank_lookback_days":RANK_LOOKBACK_DAYS,
            "rank_min_history_days":RANK_MIN_HISTORY_DAYS,
            "base_expansion_definition":"frozen V98",
            "calendar_year_used":False,
            "threshold_grid_search":False,
            "exploratory_selected_after_v98":True,
        },
        "change_points":list(change_points),
        "species_counts_by_era":state_counts,
        "first_species_date_by_era":first_species,
        "satellite_gates":gates,
        "full_period":{
            "core":_metrics(core),
            "selector":_metrics(selector),
        },
        "eras":era_out,
        "note":"V99 separates V98 expansion into structural-trend versus shock expansion using only prior-relative trend-quality features. Only structural expansion can activate aggressive satellites.",
    }

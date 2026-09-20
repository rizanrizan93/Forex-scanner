from __future__ import annotations

from bisect import bisect_right
from datetime import datetime, time, timezone
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from .demo_donchian_adaptive_tournament import TournamentTrade, compute_metrics
from .models import Bar, ensure_utc
from .research_xau_100usd_stopout_v23 import _cash_path_stopout_safe
from .research_xau_changepoint_reset_router_v87 import (
    LOOKBACK_TRADING_DAYS,
    MIN_COMPLETED_TRADES,
    MIN_TRAILING_EXPECTANCY_R,
    MIN_TRAILING_PF,
    _date_cutoff,
    _trailing_health,
    detect_change_points,
)
from .research_xau_era_fingerprint_v97 import build_fingerprint_frame
from .research_xau_era_robustness_v31 import _dedupe_with_classic, _simulate_d1_classic
from .research_xau_margin_leverage_v21 import LeverageTier
from .research_xau_multihorizon_100usd_v20 import (
    BrokerLotSpec,
    M15_VARIANTS,
    _limit_concurrency,
    _trading_dates,
    simulate_d1_staggered,
)
from .research_multisymbol_m15_breakout_v18 import extract_signals as extract_m15_breakout, simulate as simulate_m15
from .research_xau_m15_dual_strategy import M15ResearchCosts

RESEARCH_VERSION="XAU_CAUSAL_ERA_SELECTOR_V98"
ARTIFACT_CONTRACT="XAU_CAUSAL_ERA_SELECTOR_V98_EVIDENCE_1"
POLICY_EFFECT="SHADOW_ONLY"
EXECUTION_INFLUENCE=False
PROMOTION_ELIGIBLE=False

RANK_LOOKBACK_DAYS=756
RANK_MIN_HISTORY_DAYS=252
EXPANSION_SCORE_THRESHOLD=0.75
NORMAL_SCORE_THRESHOLD=0.50
STATE_CONFIRM_DAYS=3
STATE_FEATURES=(
    "atr14_pct",
    "abs_ema200_distance_atr",
    "atr_ratio_252",
    "abs_trend60_atr",
)
SATELLITES=("D1_STAGGERED","M15_L12","M15_L20")
ACCOUNT_LEVERAGE=100.0
MARGIN_FLOOR_PCT=150.0


class _Asof:
    def __init__(self,frame:pd.DataFrame):
        self.frame=frame.reset_index(drop=True)
        self.times=[ensure_utc(x) for x in self.frame["available_at"]]
    def row(self,timestamp)->Mapping[str,Any]|None:
        i=bisect_right(self.times,ensure_utc(timestamp))-1
        if i<0:return None
        return self.frame.iloc[i].to_dict()


def _pct_rank(value:float,hist:np.ndarray)->float|None:
    x=hist[np.isfinite(hist)]
    if len(x)<RANK_MIN_HISTORY_DAYS or not np.isfinite(value):
        return None
    return float(np.searchsorted(np.sort(x),value,side="right")/len(x))


def build_causal_state_frame(rows:Sequence[Bar])->pd.DataFrame:
    x=build_fingerprint_frame(rows).copy().sort_values("available_at").reset_index(drop=True)
    x["abs_ema200_distance_atr"]=x["ema200_distance_atr"].astype(float).abs()
    x["abs_trend60_atr"]=x["trend60_atr"].astype(float).abs()

    scores=[]
    raw_states=[]
    directions=[]
    for i in range(len(x)):
        ranks=[]
        for f in STATE_FEATURES:
            v=float(x.loc[i,f]) if pd.notna(x.loc[i,f]) else float("nan")
            hist=x.loc[max(0,i-RANK_LOOKBACK_DAYS):i-1,f].to_numpy(dtype=float) if i>0 else np.array([])
            r=_pct_rank(v,hist)
            if r is not None:ranks.append(r)
        score=float(np.mean(ranks)) if len(ranks)==len(STATE_FEATURES) else float("nan")
        scores.append(score)

        trend=float(x.loc[i,"trend60_atr"]) if pd.notna(x.loc[i,"trend60_atr"]) else float("nan")
        dist=float(x.loc[i,"ema200_distance_atr"]) if pd.notna(x.loc[i,"ema200_distance_atr"]) else float("nan")
        if np.isfinite(trend) and np.isfinite(dist) and trend>0 and dist>0:
            direction="BULL"
        elif np.isfinite(trend) and np.isfinite(dist) and trend<0 and dist<0:
            direction="BEAR"
        else:
            direction="MIXED"
        directions.append(direction)

        if not np.isfinite(score) or direction=="MIXED":
            raw="MIXED_OR_UNCLASSIFIED"
        elif score>=EXPANSION_SCORE_THRESHOLD:
            raw=f"{direction}_EXPANSION"
        elif score>=NORMAL_SCORE_THRESHOLD:
            raw=f"{direction}_NORMAL"
        else:
            raw=f"{direction}_COMPRESSED"
        raw_states.append(raw)

    confirmed=[]
    current="UNCLASSIFIED"
    pending=None
    run=0
    for raw in raw_states:
        if raw==current:
            pending=None;run=0
        elif raw==pending:
            run+=1
            if run>=STATE_CONFIRM_DAYS:
                current=raw
                pending=None;run=0
        else:
            pending=raw;run=1
        confirmed.append(current)

    x["era_score"]=scores
    x["raw_state"]=raw_states
    x["state"]=confirmed
    x["direction_state"]=directions
    return x


def _strategy_streams(rows:Sequence[Bar],*,costs:M15ResearchCosts,pip_size:float)->dict[str,tuple[TournamentTrade,...]]:
    bars=tuple(sorted(rows,key=lambda x:ensure_utc(x.timestamp)))
    out={
        "D1_CLASSIC":_simulate_d1_classic(bars,costs=costs,pip_size=pip_size),
        "D1_STAGGERED":simulate_d1_staggered(bars,costs=costs,pip_size=pip_size),
    }
    for variant,name in zip(M15_VARIANTS,("M15_L12","M15_L20")):
        sig=extract_m15_breakout(bars,variant=variant)
        out[name]=simulate_m15(bars,signals=sig,costs=costs,pip_size=pip_size)
    return out


def _trade_state(trade:TournamentTrade,lookup:_Asof)->str:
    row=lookup.row(trade.signal_at)
    return "UNCLASSIFIED" if row is None else str(row.get("state") or "UNCLASSIFIED")


def _dir_matches_state(trade:TournamentTrade,state:str)->bool:
    d=str(trade.direction).upper()
    return (state.startswith("BULL_") and d=="LONG") or (state.startswith("BEAR_") and d=="SHORT")


def gate_strategy_by_state_health(
    trades:Sequence[TournamentTrade],*,state_frame:pd.DataFrame,trading_dates:Sequence[Any],change_points:Sequence[Mapping[str,Any]],
)->tuple[tuple[TournamentTrade,...],dict[str,Any]]:
    lookup=_Asof(state_frame)
    ordered=tuple(sorted(trades,key=lambda t:ensure_utc(t.signal_at)))
    states={id(t):_trade_state(t,lookup) for t in ordered}
    cp_times=tuple(ensure_utc(pd.Timestamp(x["effective_at"]).to_pydatetime()) for x in change_points)
    first_date=trading_dates[0] if trading_dates else ensure_utc(ordered[0].signal_at).date()
    first_epoch=datetime.combine(first_date,time.min,tzinfo=timezone.utc)

    kept=[]
    checks=0
    expansion_candidates=0
    by_state:dict[str,dict[str,int]]={}
    for trade in ordered:
        signal=ensure_utc(trade.signal_at)
        state=states[id(trade)]
        if state not in {"BULL_EXPANSION","BEAR_EXPANSION"} or not _dir_matches_state(trade,state):
            continue
        expansion_candidates+=1
        cp_pos=bisect_right(cp_times,signal)
        epoch_start=first_epoch if cp_pos==0 else cp_times[cp_pos-1]
        rolling_date=_date_cutoff(signal,trading_dates)
        rolling_start=datetime.combine(rolling_date,time.min,tzinfo=timezone.utc)
        history_start=max(epoch_start,rolling_start)

        prior=[
            x for x in ordered
            if ensure_utc(x.exit_at)<signal
            and ensure_utc(x.exit_at)>=history_start
            and states[id(x)]==state
            and _dir_matches_state(x,state)
        ]
        health=_trailing_health(prior)
        checks+=1
        st=by_state.setdefault(state,{"checks":0,"kept":0})
        st["checks"]+=1
        if health["active"]:
            kept.append(trade)
            st["kept"]+=1

    return tuple(kept),{
        "candidate_trades":len(ordered),
        "expansion_direction_matched_candidates":expansion_candidates,
        "health_checks":checks,
        "kept_trades":len(kept),
        "suppressed_after_expansion_filter":expansion_candidates-len(kept),
        "by_state":by_state,
        "health_contract":{
            "lookback_trading_days":LOOKBACK_TRADING_DAYS,
            "min_completed_trades":MIN_COMPLETED_TRADES,
            "min_pf":MIN_TRAILING_PF,
            "min_expectancy_r":MIN_TRAILING_EXPECTANCY_R,
            "reset_at_v87_change_points":True,
        },
    }


def _period(trades:Sequence[TournamentTrade],a,b)->tuple[TournamentTrade,...]:
    aa=ensure_utc(a);bb=ensure_utc(b)
    return tuple(t for t in trades if aa<=ensure_utc(t.entry_at)<bb)


def _metrics(trades)->dict[str,Any]:
    return compute_metrics(tuple(trades)).payload()


def evaluate_v98(
    bars:Sequence[Bar],*,evaluation_start,evaluation_end,pip_size:float,costs:M15ResearchCosts,
    broker_spec:BrokerLotSpec,leverage_tiers:Sequence[LeverageTier],
    era_windows:Mapping[str,tuple[Any,Any]],
)->dict[str,Any]:
    rows=tuple(sorted(bars,key=lambda x:ensure_utc(x.timestamp)))
    start=ensure_utc(evaluation_start);end=ensure_utc(evaluation_end)
    state=build_causal_state_frame(rows)
    change_points=detect_change_points(build_fingerprint_frame(rows))
    dates=_trading_dates(rows,start=ensure_utc(rows[0].timestamp),end=end)
    streams=_strategy_streams(rows,costs=costs,pip_size=pip_size)

    selected={}
    gates={}
    for name in SATELLITES:
        selected[name],gates[name]=gate_strategy_by_state_health(
            streams[name],state_frame=state,trading_dates=dates,change_points=change_points
        )

    core=tuple(t for t in streams["D1_CLASSIC"] if start<=ensure_utc(t.entry_at)<end)
    satellites=tuple(
        t for name in SATELLITES for t in selected[name]
        if start<=ensure_utc(t.entry_at)<end
    )
    selector=_limit_concurrency(_dedupe_with_classic((*core,*satellites)))

    static=_limit_concurrency(_dedupe_with_classic((
        *streams["D1_CLASSIC"],
        *streams["D1_STAGGERED"],
        *streams["M15_L12"],
        *streams["M15_L20"],
    )))
    static=tuple(t for t in static if start<=ensure_utc(t.entry_at)<end)

    era_out={}
    for era,(a,b) in era_windows.items():
        aa=ensure_utc(a);bb=ensure_utc(b)
        edates=_trading_dates(rows,start=aa,end=bb)
        core_e=_period(core,aa,bb)
        sel_e=_period(selector,aa,bb)
        stat_e=_period(static,aa,bb)
        era_out[era]={
            "core":_metrics(core_e),
            "selector":_metrics(sel_e),
            "static_all_aggressive":_metrics(stat_e),
            "cash_fresh_100":{
                "core":_cash_path_stopout_safe(core_e,spec=broker_spec,tiers=leverage_tiers,account_leverage=ACCOUNT_LEVERAGE,stopout_pct=MARGIN_FLOOR_PCT,trading_dates=edates),
                "selector":_cash_path_stopout_safe(sel_e,spec=broker_spec,tiers=leverage_tiers,account_leverage=ACCOUNT_LEVERAGE,stopout_pct=MARGIN_FLOOR_PCT,trading_dates=edates),
                "static_all_aggressive":_cash_path_stopout_safe(stat_e,spec=broker_spec,tiers=leverage_tiers,account_leverage=ACCOUNT_LEVERAGE,stopout_pct=MARGIN_FLOOR_PCT,trading_dates=edates),
            },
        }

    state_counts={}
    for era,(a,b) in era_windows.items():
        aa=ensure_utc(a);bb=ensure_utc(b)
        s=state[(state["available_at"]>=aa)&(state["available_at"]<bb)]
        state_counts[era]={str(k):int(v) for k,v in s["state"].value_counts().to_dict().items()}

    return {
        "research_version":RESEARCH_VERSION,
        "artifact_contract":ARTIFACT_CONTRACT,
        "policy_effect":POLICY_EFFECT,
        "execution_influence":EXECUTION_INFLUENCE,
        "promotion_eligible":PROMOTION_ELIGIBLE,
        "live_execution_enabled":False,
        "state_contract":{
            "features":list(STATE_FEATURES),
            "rank_lookback_days":RANK_LOOKBACK_DAYS,
            "rank_min_history_days":RANK_MIN_HISTORY_DAYS,
            "expansion_score_threshold":EXPANSION_SCORE_THRESHOLD,
            "normal_score_threshold":NORMAL_SCORE_THRESHOLD,
            "state_confirmation_days":STATE_CONFIRM_DAYS,
            "calendar_year_used":False,
            "direction_requires_trend60_and_ema200_distance_same_sign":True,
            "threshold_grid_search":False,
        },
        "change_points":list(change_points),
        "state_counts_by_era":state_counts,
        "satellite_gates":gates,
        "full_period":{
            "core":_metrics(core),
            "selector":_metrics(selector),
            "static_all_aggressive":_metrics(static),
        },
        "eras":era_out,
        "note":"V98 is an exploratory causal selector. It uses only prior-relative market-state ranks, three-day state confirmation, V87 change-point resets, and frozen V40/V47 health thresholds. Era labels are evaluation-only.",
    }

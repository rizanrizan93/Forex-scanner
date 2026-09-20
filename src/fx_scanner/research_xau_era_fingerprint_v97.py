from __future__ import annotations

from bisect import bisect_right
from datetime import timedelta
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from .demo_donchian_adaptive_tournament import TournamentTrade, compute_metrics
from .models import Bar, ensure_utc
from .research_multisymbol_m15_breakout_v18 import extract_signals as extract_m15_breakout, simulate as simulate_m15
from .research_xau_100usd_bootstrap_v89 import _assemble
from .research_xau_era_robustness_v31 import _simulate_d1_classic
from .research_xau_fvg_ote_bootstrap_v93 import transform_v87_ict_entries
from .research_xau_hierarchical_regime_router_v35 import _adx, _resample_completed
from .research_xau_multihorizon_100usd_v20 import M15_VARIANTS, simulate_d1_staggered
from .research_xau_m15_dual_strategy import M15ResearchCosts
from .research_xau_changepoint_reset_router_v87 import build_regime_feature_frame

RESEARCH_VERSION="XAU_ERA_FINGERPRINT_V97"
ARTIFACT_CONTRACT="XAU_ERA_FINGERPRINT_V97_EVIDENCE_1"
POLICY_EFFECT="SHADOW_ONLY"
EXECUTION_INFLUENCE=False
PROMOTION_ELIGIBLE=False

FEATURES=(
    "trend60_atr",
    "ema200_distance_atr",
    "atr14_pct",
    "efficiency20",
    "adx14",
    "di_spread_abs",
    "ret20_atr",
    "ret60_atr",
    "atr_ratio_252",
    "range20_atr",
    "close_position20",
    "drawdown60_atr",
    "h1_adx14",
    "h1_ema20_50_spread_atr",
)

STRATEGIES=(
    "D1_CLASSIC",
    "D1_STAGGERED",
    "M15_L12",
    "M15_L20",
    "FVG_CE",
)


def build_fingerprint_frame(rows:Sequence[Bar])->pd.DataFrame:
    d1=build_regime_feature_frame(rows).copy().sort_values("time").reset_index(drop=True)
    adx,pdi,mdi=_adx(d1[["time","open","high","low","close"]].copy(),14)
    d1["adx14"]=adx
    d1["di_spread_abs"]=(pdi-mdi).abs()
    atr=d1["atr14"].astype(float).replace(0.0,np.nan)
    close=d1["close"].astype(float)
    d1["ret20_atr"]=(close-close.shift(20))/atr
    d1["ret60_atr"]=(close-close.shift(60))/atr
    d1["atr_ratio_252"]=atr/atr.rolling(252,min_periods=126).median()
    high20=d1["high"].astype(float).rolling(20,min_periods=20).max()
    low20=d1["low"].astype(float).rolling(20,min_periods=20).min()
    width=(high20-low20).replace(0.0,np.nan)
    d1["range20_atr"]=width/atr
    d1["close_position20"]=(close-low20)/width
    high60=d1["high"].astype(float).rolling(60,min_periods=60).max()
    d1["drawdown60_atr"]=(high60-close)/atr

    h1=_resample_completed(rows,"1h")
    h1["atr14"] = (
        pd.concat([
            (h1["high"]-h1["low"]).abs(),
            (h1["high"]-h1["close"].shift(1)).abs(),
            (h1["low"]-h1["close"].shift(1)).abs(),
        ],axis=1).max(axis=1)
        .ewm(alpha=1/14,adjust=False,min_periods=14).mean()
    )
    hadx,_,_=_adx(h1,14)
    h1["h1_adx14"]=hadx
    h1["ema20"]=h1["close"].ewm(span=20,adjust=False,min_periods=20).mean()
    h1["ema50"]=h1["close"].ewm(span=50,adjust=False,min_periods=50).mean()
    h1["h1_ema20_50_spread_atr"]=(h1["ema20"]-h1["ema50"]).abs()/h1["atr14"].replace(0.0,np.nan)
    h1_daily=(
        h1.set_index("time")[["h1_adx14","h1_ema20_50_spread_atr"]]
        .resample("1D",label="right",closed="right").last().dropna(how="all").reset_index()
    )
    d1=pd.merge_asof(
        d1.sort_values("time"),
        h1_daily.sort_values("time"),
        on="time",direction="backward",
    )
    # D1 source uses day-labelled bars; these features are safe only after that day has completed.
    d1["available_at"]=[ensure_utc(x)+timedelta(days=1) for x in d1["time"]]
    return d1


def _profile(frame:pd.DataFrame)->dict[str,Any]:
    out={}
    for f in FEATURES:
        x=frame[f].astype(float).replace([np.inf,-np.inf],np.nan).dropna()
        if x.empty:
            out[f]={"n":0,"p10":None,"p25":None,"median":None,"p75":None,"p90":None,"mean":None}
            continue
        out[f]={
            "n":int(len(x)),
            "p10":float(x.quantile(.10)),
            "p25":float(x.quantile(.25)),
            "median":float(x.median()),
            "p75":float(x.quantile(.75)),
            "p90":float(x.quantile(.90)),
            "mean":float(x.mean()),
        }
    return out


def _robust_effect(a:pd.Series,b:pd.Series)->float|None:
    x=a.astype(float).replace([np.inf,-np.inf],np.nan).dropna()
    y=b.astype(float).replace([np.inf,-np.inf],np.nan).dropna()
    if x.empty or y.empty:
        return None
    pooled=pd.concat([x,y],ignore_index=True)
    med=float(pooled.median())
    mad=float((pooled-med).abs().median())
    if not np.isfinite(mad) or mad<=1e-12:
        return None
    return float((x.median()-y.median())/(1.4826*mad))


class _Asof:
    def __init__(self,frame:pd.DataFrame):
        self.frame=frame.reset_index(drop=True)
        self.times=[ensure_utc(x) for x in self.frame["available_at"]]
    def row(self,timestamp)->Mapping[str,Any]|None:
        t=ensure_utc(timestamp)
        i=bisect_right(self.times,t)-1
        if i<0:return None
        return self.frame.iloc[i].to_dict()


def _strategy_streams(rows:Sequence[Bar],*,costs:M15ResearchCosts,pip_size:float,evaluation_end)->dict[str,tuple[TournamentTrade,...]]:
    bars=tuple(sorted(rows,key=lambda x:ensure_utc(x.timestamp)))
    out={
        "D1_CLASSIC":_simulate_d1_classic(bars,costs=costs,pip_size=pip_size),
        "D1_STAGGERED":simulate_d1_staggered(bars,costs=costs,pip_size=pip_size),
    }
    for variant,name in zip(M15_VARIANTS,("M15_L12","M15_L20")):
        sig=extract_m15_breakout(bars,variant=variant)
        out[name]=simulate_m15(bars,signals=sig,costs=costs,pip_size=pip_size)
    _,satellite,_,_,_=_assemble(bars,costs=costs,pip_size=pip_size,end=ensure_utc(evaluation_end))
    out["FVG_CE"]=transform_v87_ict_entries(bars,satellite,variant_id="FVG_CE_4",costs=costs)
    return out


def _period(trades:Sequence[TournamentTrade],a,b)->tuple[TournamentTrade,...]:
    aa=ensure_utc(a);bb=ensure_utc(b)
    return tuple(t for t in trades if aa<=ensure_utc(t.entry_at)<bb)


def _metrics(trades:Sequence[TournamentTrade])->dict[str,Any]:
    return compute_metrics(tuple(trades)).payload()


def _annual_metrics(trades:Sequence[TournamentTrade],start_year:int,end_year:int)->dict[str,Any]:
    out={}
    for y in range(start_year,end_year+1):
        vals=tuple(t for t in trades if ensure_utc(t.entry_at).year==y)
        out[str(y)]=_metrics(vals)
    return out


def _state_attribution(
    trades:Sequence[TournamentTrade],
    frame:pd.DataFrame,
    recent_profile:Mapping[str,Any],
    top_features:Sequence[str],
)->dict[str,Any]:
    lookup=_Asof(frame)
    buckets={0:[],1:[],2:[],3:[],4:[],5:[]}
    for t in trades:
        row=lookup.row(t.signal_at)
        if row is None: continue
        score=0
        for f in top_features:
            p=recent_profile[f]
            v=float(row.get(f,np.nan))
            if np.isfinite(v) and p["p25"] is not None and float(p["p25"])<=v<=float(p["p75"]):
                score+=1
        buckets[min(5,score)].append(t)
    return {str(k):_metrics(v) for k,v in buckets.items()}


def evaluate_v97(
    bars:Sequence[Bar],*,evaluation_start,evaluation_end,pip_size:float,
    costs:M15ResearchCosts,era_windows:Mapping[str,tuple[Any,Any]],
)->dict[str,Any]:
    rows=tuple(sorted(bars,key=lambda x:ensure_utc(x.timestamp)))
    start=ensure_utc(evaluation_start);end=ensure_utc(evaluation_end)
    frame=build_fingerprint_frame(rows)
    frame=frame[(frame["available_at"]>=start)&(frame["available_at"]<end)].copy()

    profiles={}
    slices={}
    for era,(a,b) in era_windows.items():
        aa=ensure_utc(a);bb=ensure_utc(b)
        s=frame[(frame["available_at"]>=aa)&(frame["available_at"]<bb)].copy()
        slices[era]=s
        profiles[era]=_profile(s)

    recent=slices["2025_2026YTD"]
    prior=slices["2019_2024"]
    old=slices["2012_2018"]
    effects={}
    for f in FEATURES:
        effects[f]={
            "recent_vs_2019_2024":_robust_effect(recent[f],prior[f]),
            "recent_vs_2012_2018":_robust_effect(recent[f],old[f]),
        }
    ranked=sorted(
        FEATURES,
        key=lambda f:abs(effects[f]["recent_vs_2019_2024"] or 0.0)+abs(effects[f]["recent_vs_2012_2018"] or 0.0),
        reverse=True,
    )
    top5=tuple(ranked[:5])

    streams=_strategy_streams(rows,costs=costs,pip_size=pip_size,evaluation_end=end)
    strategy={}
    for name,trades in streams.items():
        eligible=tuple(t for t in trades if start<=ensure_utc(t.entry_at)<end)
        strategy[name]={
            "full":_metrics(eligible),
            "eras":{
                era:_metrics(_period(eligible,a,b))
                for era,(a,b) in era_windows.items()
            },
            "annual":_annual_metrics(eligible,start.year,end.year),
            "recent_fingerprint_match_count":_state_attribution(
                eligible,frame,profiles["2025_2026YTD"],top5
            ),
        }

    return {
        "research_version":RESEARCH_VERSION,
        "artifact_contract":ARTIFACT_CONTRACT,
        "policy_effect":POLICY_EFFECT,
        "execution_influence":EXECUTION_INFLUENCE,
        "promotion_eligible":PROMOTION_ELIGIBLE,
        "live_execution_enabled":False,
        "evaluation_start":start.isoformat(),
        "evaluation_end_exclusive":end.isoformat(),
        "features":list(FEATURES),
        "era_profiles":profiles,
        "recent_effect_sizes":effects,
        "top_recent_distinguishing_features":list(top5),
        "strategy_metrics":strategy,
        "contract":{
            "calendar_labels_used_for_execution":False,
            "era_labels_used_for_forensic_attribution_only":True,
            "feature_availability":"completed D1 / completed H1 only",
            "recent_fingerprint_band":"2025-2026YTD p25-p75; diagnostic only",
            "fingerprint_match_is_not_a_selector":True,
            "dense_parameter_search":False,
            "execution_authority":False,
        },
        "note":"V97 diagnoses which observable market-state features distinguish the recent high-profit regime and whether strategies behave differently when those states recur. It does not route or size trades.",
    }

from __future__ import annotations

from bisect import bisect_left, bisect_right
from datetime import datetime, time
from typing import Any, Mapping, Sequence

import pandas as pd

from .models import Bar, ensure_utc
from .research_xau_changepoint_reset_router_v87 import (
    LOOKBACK_TRADING_DAYS,
    MIN_COMPLETED_TRADES,
    _date_cutoff,
    _trailing_health,
    build_regime_feature_frame,
    detect_change_points,
)
from .research_xau_expansion_species_v99 import build_species_frame
from .research_xau_m15_exceptional_expansion_audit_v109 import build_exceptional_frame
from .research_xau_multihorizon_100usd_v20 import _trading_dates
from .research_xau_causal_era_selector_v98 import _strategy_streams
from .research_xau_recency_witness_era_selector_v105 import RECENCY_WITNESS_DAYS
from .research_xau_m15_dual_strategy import M15ResearchCosts

RESEARCH_VERSION="XAU_V110_PROSPECTIVE_OBSERVER_V113"
ARTIFACT_CONTRACT="XAU_V110_PROSPECTIVE_OBSERVER_V113_EVIDENCE_1"
POLICY_EFFECT="SHADOW_ONLY"
EXECUTION_INFLUENCE=False
PROMOTION_ELIGIBLE=False

OBSERVED_STRATEGIES=("D1_CLASSIC","D1_STAGGERED","M15_L12","M15_L20")


class _Asof:
    def __init__(self,frame:pd.DataFrame):
        self.frame=frame.reset_index(drop=True)
        self.times=[ensure_utc(x) for x in self.frame["available_at"]]
    def row(self,timestamp):
        i=bisect_right(self.times,ensure_utc(timestamp))-1
        if i<0:return None
        return self.frame.iloc[i].to_dict()


def _species_side(label:str|None)->str|None:
    if not label:return None
    if str(label).startswith("BULL_"):return "LONG"
    if str(label).startswith("BEAR_"):return "SHORT"
    return None


def _m15_label(row:Mapping[str,Any]|None)->str|None:
    if row is None or not bool(row.get("unanimous_extreme_expansion")):
        return None
    state=str(row.get("state") or "")
    if state=="BULL_EXPANSION":return "BULL_UNANIMOUS_EXTREME"
    if state=="BEAR_EXPANSION":return "BEAR_UNANIMOUS_EXTREME"
    return None


def _label_for_trade(trade, *, lookup:_Asof, mode:str)->str|None:
    row=lookup.row(trade.signal_at)
    if mode=="D1_SPECIES":
        return None if row is None else str(row.get("species") or "UNCLASSIFIED")
    if mode=="M15_EXTREME":
        return _m15_label(row)
    raise ValueError(mode)


def _direction_matches(label:str|None,direction:str)->bool:
    side=_species_side(label)
    return side is not None and side==str(direction).upper()


def _witness_cutoff_date(as_of, trading_dates:Sequence[Any]):
    dates=tuple(trading_dates)
    if not dates:return ensure_utc(as_of).date()
    pos=bisect_left(dates,ensure_utc(as_of).date())
    return dates[max(0,pos-RECENCY_WITNESS_DAYS)]


def _current_health(
    trades,
    *,
    lookup:_Asof,
    current_label:str|None,
    mode:str,
    as_of,
    trading_dates:Sequence[Any],
    change_points:Sequence[Mapping[str,Any]],
)->dict[str,Any]:
    now=ensure_utc(as_of)
    if current_label is None:
        return {
            "authority":False,
            "status":"OFF_MARKET_STATE",
            "label":None,
            "direction":None,
            "tier":"NONE",
            "completed_trades":0,
            "profit_factor":None,
            "expectancy_r":None,
        }
    side=_species_side(current_label)
    if side is None:
        return {
            "authority":False,
            "status":"OFF_MARKET_STATE",
            "label":current_label,
            "direction":None,
            "tier":"NONE",
            "completed_trades":0,
            "profit_factor":None,
            "expectancy_r":None,
        }

    ordered=tuple(sorted(trades,key=lambda t:ensure_utc(t.signal_at)))
    labels={id(t):_label_for_trade(t,lookup=lookup,mode=mode) for t in ordered}
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
        and labels[id(t)]==current_label
        and _direction_matches(current_label,t.direction)
    ]
    exact_recent=[t for t in completed if ensure_utc(t.exit_at)>=recent_start]
    exact_epoch=[t for t in completed if ensure_utc(t.exit_at)>=epoch_start]

    witness_cutoff=_witness_cutoff_date(now,trading_dates)
    last_exit=None if not exact_epoch else ensure_utc(exact_epoch[-1].exit_at)

    tier="OFF_INSUFFICIENT"
    history=()
    status="OFF_INSUFFICIENT"
    if len(exact_recent)>=MIN_COMPLETED_TRADES:
        tier="EXACT_RECENT"
        history=tuple(exact_recent)
        status="HEALTH_CHECK"
    elif len(exact_epoch)>=MIN_COMPLETED_TRADES:
        fresh=last_exit is not None and last_exit.date()>=witness_cutoff
        if fresh:
            tier="EXACT_EPOCH_FRESH"
            history=tuple(exact_epoch)
            status="HEALTH_CHECK"
        else:
            base=_trailing_health(tuple(exact_epoch))
            return {
                "authority":False,
                "status":"SHADOW_PROBATION_REQUIRED",
                "label":current_label,
                "direction":side,
                "tier":"STALE_EXACT_EPOCH",
                "completed_trades":base["completed_trades"],
                "profit_factor":base["profit_factor"],
                "expectancy_r":base["expectancy_r"],
                "net_r":base["net_r"],
                "epoch_start":epoch_start.isoformat(),
                "recent_start":recent_start.isoformat(),
                "last_exact_exit":None if last_exit is None else last_exit.isoformat(),
                "witness_cutoff":str(witness_cutoff),
            }

    health=_trailing_health(history)
    authority=bool(health["active"])
    if status=="HEALTH_CHECK":
        status="ACTIVE" if authority else "OFF_HEALTH"
    return {
        "authority":authority,
        "status":status,
        "label":current_label,
        "direction":side,
        "tier":tier,
        "completed_trades":health["completed_trades"],
        "profit_factor":health["profit_factor"],
        "expectancy_r":health["expectancy_r"],
        "net_r":health["net_r"],
        "epoch_start":epoch_start.isoformat(),
        "recent_start":recent_start.isoformat(),
        "last_exact_exit":None if last_exit is None else last_exit.isoformat(),
        "witness_cutoff":str(witness_cutoff),
    }


def evaluate_v113(
    rows:Sequence[Bar],*,pip_size:float,costs:M15ResearchCosts,observed_at=None
)->dict[str,Any]:
    bars=tuple(sorted(rows,key=lambda x:ensure_utc(x.timestamp)))
    if not bars:
        raise ValueError("V113_EMPTY_HISTORY")
    latest_bar=ensure_utc(bars[-1].timestamp)
    as_of=latest_bar if observed_at is None else min(ensure_utc(observed_at),latest_bar)

    species=build_species_frame(bars)
    exceptional=build_exceptional_frame(bars)
    species_lookup=_Asof(species)
    exceptional_lookup=_Asof(exceptional)
    species_row=species_lookup.row(as_of)
    exceptional_row=exceptional_lookup.row(as_of)
    d1_label=None if species_row is None else str(species_row.get("species") or "UNCLASSIFIED")
    m15_label=_m15_label(exceptional_row)

    change_points=detect_change_points(build_regime_feature_frame(bars))
    dates=_trading_dates(bars,start=ensure_utc(bars[0].timestamp),end=as_of)
    streams=_strategy_streams(bars,costs=costs,pip_size=pip_size)

    d1=_current_health(
        streams["D1_STAGGERED"],lookup=species_lookup,current_label=d1_label,
        mode="D1_SPECIES",as_of=as_of,trading_dates=dates,change_points=change_points,
    )
    l12=_current_health(
        streams["M15_L12"],lookup=exceptional_lookup,current_label=m15_label,
        mode="M15_EXTREME",as_of=as_of,trading_dates=dates,change_points=change_points,
    )
    l20=_current_health(
        streams["M15_L20"],lookup=exceptional_lookup,current_label=m15_label,
        mode="M15_EXTREME",as_of=as_of,trading_dates=dates,change_points=change_points,
    )

    active=[name for name,x in (("D1_STAGGERED",d1),("M15_L12",l12),("M15_L20",l20)) if x["authority"]]
    last_cp=None
    for cp in change_points:
        t=ensure_utc(pd.Timestamp(cp["effective_at"]).to_pydatetime())
        if t<=as_of:last_cp=cp

    state_snapshot={
        "as_of":as_of.isoformat(),
        "latest_m15_bar":latest_bar.isoformat(),
        "v99_d1_species":d1_label,
        "v99_quality_score":None if species_row is None else species_row.get("quality_score"),
        "v98_state":None if exceptional_row is None else exceptional_row.get("state"),
        "v98_expansion_score":None if exceptional_row is None else exceptional_row.get("state_score"),
        "m15_unanimous_extreme":bool(exceptional_row.get("unanimous_extreme_expansion")) if exceptional_row is not None else False,
        "m15_state_label":m15_label,
        "last_v87_change_point":last_cp,
    }

    return {
        "research_version":RESEARCH_VERSION,
        "artifact_contract":ARTIFACT_CONTRACT,
        "policy_effect":POLICY_EFFECT,
        "execution_influence":EXECUTION_INFLUENCE,
        "promotion_eligible":PROMOTION_ELIGIBLE,
        "live_execution_enabled":False,
        "contract":{
            "selector":"frozen V110",
            "cost_assumption":"provided by runtime; intended V24_STRESS_4675",
            "D1_state":"V99 structural/shock species",
            "M15_state":"V109 direction-matched unanimous extreme expansion",
            "health_thresholds":"frozen V40/V47",
            "recency_witness_days":RECENCY_WITNESS_DAYS,
            "current_stale_state_policy":"shadow probation required",
            "orders_created":False,
        },
        "state_snapshot":state_snapshot,
        "strategy_authority":{
            "D1_CLASSIC":{
                "authority":True,
                "status":"CORE_FALLBACK",
                "note":"Base D1 core remains the fallback; V113 does not create orders.",
            },
            "D1_STAGGERED":d1,
            "M15_L12":l12,
            "M15_L20":l20,
        },
        "active_satellites":active,
        "selector_mode":"CORE_PLUS_SATELLITES" if active else "CORE_ONLY",
        "note":"Prospective shadow observer only. State and health are evaluated causally from information available up to the latest completed historical bar; no execution authority is connected to a broker.",
    }

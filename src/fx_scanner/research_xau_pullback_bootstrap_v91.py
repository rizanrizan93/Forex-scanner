from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any, Mapping, Sequence

from .demo_donchian_adaptive_tournament import TournamentTrade, compute_metrics
from .models import Bar, ensure_utc
from .research_multisymbol_m15_breakout_v18 import (
    MAX_HOLD_BARS,
    _cost_r,
)
from .research_xau_100usd_bootstrap_v89 import _assemble
from .research_xau_capital_ladder_v90 import (
    required_balance_distribution,
    risk_capped_dynamic_cash_path,
)
from .research_xau_hierarchical_regime_router_v35 import _period
from .research_xau_margin_leverage_v21 import LeverageTier
from .research_xau_multihorizon_100usd_v20 import BrokerLotSpec, M15_VARIANTS
from .research_xau_m15_dual_strategy import M15ResearchCosts

RESEARCH_VERSION="XAU_PULLBACK_BOOTSTRAP_V91"
ARTIFACT_CONTRACT="XAU_PULLBACK_BOOTSTRAP_V91_EVIDENCE_1"
POLICY_EFFECT="SHADOW_ONLY"
EXECUTION_INFLUENCE=False
PROMOTION_ELIGIBLE=False
DIAGNOSTIC_ONLY=True

PENDING_WINDOW_BARS=4
PIP_SIZE=0.01
STARTING_BALANCE=100.0
VARIANTS=("BREAKOUT_LEVEL_RETEST_4","DISPLACEMENT_50_RETEST_4")


def _variant_lookback(strategy_id:str)->int:
    for v in M15_VARIANTS:
        if v.variant_id==strategy_id:
            return int(v.lookback_m15)
    raise ValueError(f"V91_UNKNOWN_STRATEGY:{strategy_id}")


def _limit_price(rows:Sequence[Bar],trade:TournamentTrade,variant_id:str)->float|None:
    i=int(trade.signal_index)
    if i<=0 or i>=len(rows):
        return None
    signal=rows[i]
    if variant_id=="DISPLACEMENT_50_RETEST_4":
        return (float(signal.high)+float(signal.low))/2.0
    if variant_id=="BREAKOUT_LEVEL_RETEST_4":
        lookback=_variant_lookback(str(trade.strategy_id))
        if i<lookback:
            return None
        prior=rows[i-lookback:i]
        return (
            max(float(x.high) for x in prior)
            if str(trade.direction).upper()=="LONG"
            else min(float(x.low) for x in prior)
        )
    raise ValueError(f"V91_VARIANT_INVALID:{variant_id}")


def _simulate_one(
    rows:Sequence[Bar],
    baseline:TournamentTrade,
    *,
    variant_id:str,
    costs:M15ResearchCosts,
)->TournamentTrade|None:
    direction=str(baseline.direction).upper()
    start=int(baseline.signal_index)+1
    if start>=len(rows):
        return None
    limit=_limit_price(rows,baseline,variant_id)
    if limit is None or not isfinite(limit):
        return None
    stop=float(baseline.stop_loss)
    original_entry=float(rows[start].open)

    # The experiment is specifically a better-price pullback, not a marketable
    # order or a tighter stop. Keep the exact original structural invalidation.
    if direction=="LONG":
        if not (stop < limit < original_entry):
            return None
    elif direction=="SHORT":
        if not (original_entry < limit < stop):
            return None
    else:
        return None

    fill_i=None
    stopped_on_fill=False
    end_pending=min(len(rows)-1,start+PENDING_WINDOW_BARS-1)
    for j in range(start,end_pending+1):
        bar=rows[j]
        if direction=="LONG":
            fill= float(bar.low)<=limit
            stop_touch=float(bar.low)<=stop
        else:
            fill= float(bar.high)>=limit
            stop_touch=float(bar.high)>=stop

        if fill:
            fill_i=j
            # If both prices are inside one M15 bar, assume adverse ordering:
            # limit fills first and the structural stop is then hit.
            stopped_on_fill=bool(stop_touch)
            break
        # A structural invalidation before the pullback fills cancels the setup.
        if stop_touch:
            return None

    if fill_i is None:
        return None

    entry=float(limit)
    risk=entry-stop if direction=="LONG" else stop-entry
    if not isfinite(risk) or risk<=0:
        return None
    risk_pips=risk/PIP_SIZE
    target=float(baseline.take_profit)
    if direction=="LONG" and target<=entry:
        return None
    if direction=="SHORT" and target>=entry:
        return None

    if stopped_on_fill:
        cost=_cost_r(risk_pips=risk_pips,bars_held=0,costs=costs)
        return TournamentTrade(
            f"{baseline.strategy_id}_{variant_id}",
            baseline.symbol,direction,baseline.signal_at,
            ensure_utc(rows[fill_i].timestamp),ensure_utc(rows[fill_i].timestamp),
            baseline.signal_index,fill_i,entry,stop,baseline.atr_at_signal,
            stop,target,-1.0,cost,-1.0-cost,0,"STOP_FIRST_AMBIGUOUS",
        )

    last=min(len(rows)-1,fill_i+MAX_HOLD_BARS)
    for j in range(fill_i,last+1):
        bar=rows[j]
        if direction=="LONG":
            stop_hit=float(bar.low)<=stop
            target_hit=float(bar.high)>=target
        else:
            stop_hit=float(bar.high)>=stop
            target_hit=float(bar.low)<=target
        # Do not credit a target in the fill bar because intrabar ordering is unknown.
        raw_target=target_hit
        if j==fill_i:
            target_hit=False
        held=j-fill_i
        cost=_cost_r(risk_pips=risk_pips,bars_held=held,costs=costs)
        if stop_hit:
            return TournamentTrade(
                f"{baseline.strategy_id}_{variant_id}",baseline.symbol,direction,
                baseline.signal_at,ensure_utc(rows[fill_i].timestamp),ensure_utc(bar.timestamp),
                baseline.signal_index,j,entry,stop,baseline.atr_at_signal,stop,target,
                -1.0,cost,-1.0-cost,held,
                "STOP_FIRST_AMBIGUOUS" if raw_target else "STOP_HIT",
            )
        if target_hit:
            gross=abs(target-entry)/risk
            return TournamentTrade(
                f"{baseline.strategy_id}_{variant_id}",baseline.symbol,direction,
                baseline.signal_at,ensure_utc(rows[fill_i].timestamp),ensure_utc(bar.timestamp),
                baseline.signal_index,j,entry,target,baseline.atr_at_signal,stop,target,
                gross,cost,gross-cost,held,"TARGET_HIT",
            )

    if last<fill_i+MAX_HOLD_BARS:
        return None
    exit_bar=rows[last]
    exit_price=float(exit_bar.close)
    gross=(exit_price-entry)/risk if direction=="LONG" else (entry-exit_price)/risk
    cost=_cost_r(risk_pips=risk_pips,bars_held=MAX_HOLD_BARS,costs=costs)
    return TournamentTrade(
        f"{baseline.strategy_id}_{variant_id}",baseline.symbol,direction,
        baseline.signal_at,ensure_utc(rows[fill_i].timestamp),ensure_utc(exit_bar.timestamp),
        baseline.signal_index,last,entry,exit_price,baseline.atr_at_signal,stop,target,
        gross,cost,gross-cost,MAX_HOLD_BARS,"TIME_EXIT",
    )


def transform_v87_satellite(
    rows:Sequence[Bar],
    satellite:Sequence[TournamentTrade],
    *,
    variant_id:str,
    costs:M15ResearchCosts,
)->tuple[TournamentTrade,...]:
    bars=tuple(sorted(rows,key=lambda x:ensure_utc(x.timestamp)))
    out=[]
    for trade in satellite:
        value=_simulate_one(bars,trade,variant_id=variant_id,costs=costs)
        if value is not None:
            out.append(value)
    return tuple(sorted(out,key=lambda x:ensure_utc(x.entry_at)))


def evaluate_v91(
    bars,
    *,
    evaluation_start,
    evaluation_end,
    pip_size:float,
    costs:M15ResearchCosts,
    broker_spec:BrokerLotSpec,
    leverage_tiers:Sequence[LeverageTier],
    era_windows:Mapping[str,tuple[Any,Any]],
)->dict[str,Any]:
    rows=tuple(sorted(bars,key=lambda x:ensure_utc(x.timestamp)))
    start=ensure_utc(evaluation_start);end=ensure_utc(evaluation_end)
    _,satellite,_,change_points,gates=_assemble(rows,costs=costs,pip_size=pip_size,end=end)
    baseline=tuple(t for t in satellite if start<=ensure_utc(t.entry_at)<end)
    checkpoints={
        "START_2012":start,
        "START_2019":ensure_utc(era_windows["2019_2024"][0]),
        "START_2025":ensure_utc(era_windows["2025_2026YTD"][0]),
        "END_2026YTD":end,
    }
    results={}
    for variant_id in VARIANTS:
        trades=transform_v87_satellite(rows,baseline,variant_id=variant_id,costs=costs)
        results[variant_id]={
            "baseline_signals":len(baseline),
            "filled_trades":len(trades),
            "fill_fraction":0.0 if not baseline else len(trades)/float(len(baseline)),
            "metrics":compute_metrics(trades).payload(),
            "required_balance_for_minimum_lot":required_balance_distribution(trades,spec=broker_spec),
            "cash_100_risk5_dynamic":risk_capped_dynamic_cash_path(
                trades,starting_balance=STARTING_BALANCE,spec=broker_spec,
                tiers=leverage_tiers,checkpoint_times=checkpoints,
            ),
            "era_metrics":{
                era:compute_metrics(_period(trades,start=ensure_utc(a),end=ensure_utc(b))).payload()
                for era,(a,b) in era_windows.items()
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
            "source_signals":"V87_RESET_SATELLITE_ONLY",
            "pending_window_bars":PENDING_WINDOW_BARS,
            "pending_window_minutes":PENDING_WINDOW_BARS*15,
            "same_original_structural_stop":True,
            "same_original_absolute_target":True,
            "same_bar_fill_stop_assumption":"STOP_FIRST",
            "same_bar_fill_target_credit":False,
            "starting_balance_usd":STARTING_BALANCE,
            "risk_pct_per_trade":5.0,
            "lot_min":0.01,
            "lot_step":0.01,
            "lot_max":0.50,
            "variants":list(VARIANTS),
            "dense_grid_search":False,
            "calendar_era_routing":False,
        },
        "baseline_v87_satellite_metrics":compute_metrics(baseline).payload(),
        "change_points":list(change_points),
        "gates":gates,
        "variants":results,
    }

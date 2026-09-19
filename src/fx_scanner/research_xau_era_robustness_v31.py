from __future__ import annotations

from dataclasses import asdict
from typing import Any, Sequence

from .demo_donchian_adaptive_tournament import TournamentTrade, compute_metrics
from .models import Bar, ensure_utc
from .research_xau_100usd_stopout_v23 import _cash_path_stopout_safe
from .research_xau_margin_leverage_v21 import LeverageTier
from .research_xau_multihorizon_100usd_v20 import (
    BrokerLotSpec,
    _daily_frame,
    _d1_cost_r,
    _dedupe,
    _limit_concurrency,
    _period,
    _portfolio_candidates,
    _trading_dates,
)

RESEARCH_VERSION = "XAU_ERA_ROBUSTNESS_V31"
ARTIFACT_CONTRACT = "XAU_ERA_ROBUSTNESS_V31_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
DIAGNOSTIC_ONLY = True

ACCOUNT_LEVERAGE = 100.0
MARGIN_FLOOR_PCT = 150.0
PORTFOLIOS = ("D1_CLASSIC","D1_CLASSIC_PLUS_L20","D1_CLASSIC_PLUS_L12_L20","D1_ONLY","D1_PLUS_L20","D1_PLUS_L12_L20")



def _simulate_d1_classic(rows: Sequence[Bar], *, costs, pip_size: float):
    """Original non-staggered D1 TSMOM: one position at a time."""
    d1=_daily_frame(rows)
    output=[]
    i=0
    n=len(d1)
    while i<n-1:
        direction=int(d1.loc[i,"direction"])
        if direction==0:
            i+=1
            continue
        atr=float(d1.loc[i,"atr14"])
        if not (atr>0):
            i+=1
            continue
        entry_i=i+1
        entry=float(d1.loc[entry_i,"open"])
        risk=2.0*atr
        stop=entry-direction*risk
        target=entry+direction*2.0*risk
        last_i=min(n-1,entry_i+30-1)
        gross=None
        exit_i=last_i
        exit_price=float(d1.loc[last_i,"close"])
        reason="TIME_EXIT"
        for j in range(entry_i,last_i+1):
            hi=float(d1.loc[j,"high"]); lo=float(d1.loc[j,"low"])
            stop_hit=lo<=stop if direction>0 else hi>=stop
            target_hit=hi>=target if direction>0 else lo<=target
            if stop_hit:
                gross=-1.0; exit_i=j; exit_price=stop
                reason="STOP_FIRST_AMBIGUOUS" if target_hit else "STOP_HIT"
                break
            if target_hit:
                gross=2.0; exit_i=j; exit_price=target; reason="TARGET_HIT"
                break
        if gross is None:
            exit_price=float(d1.loc[exit_i,"close"])
            gross=direction*(exit_price-entry)/risk
        entry_time=d1.loc[entry_i,"time"]; exit_time=d1.loc[exit_i,"time"]
        cost_r=_d1_cost_r(
            risk_price=risk,entry_time=entry_time,exit_time=exit_time,
            pip_size=pip_size,costs=costs,
        )
        output.append(TournamentTrade(
            "V31_D1_TSMOM_CLASSIC","XAUUSD","LONG" if direction>0 else "SHORT",
            d1.loc[i,"time"],entry_time,exit_time,i,exit_i,entry,exit_price,atr,
            stop,target,float(gross),float(cost_r),float(gross-cost_r),
            int(exit_i-entry_i),reason,
        ))
        i=exit_i+1
    return tuple(output)


def _dedupe_with_classic(trades):
    priority={
        "V31_D1_TSMOM_CLASSIC":4,
        "V20_M15_L20_ADX15_D1_R200":3,
        "V20_D1_TSMOM_C1_R200":2,
        "V20_M15_L12_ADX12_D1_R150":1,
    }
    chosen={}
    for trade in trades:
        key=(ensure_utc(trade.entry_at),str(trade.direction))
        cur=chosen.get(key)
        if cur is None or priority.get(trade.strategy_id,0)>priority.get(cur.strategy_id,0):
            chosen[key]=trade
    return tuple(sorted(chosen.values(),key=lambda x:(ensure_utc(x.entry_at),x.strategy_id)))

def _direction_metrics(trades):
    long_t=tuple(x for x in trades if str(x.direction).upper()=="LONG")
    short_t=tuple(x for x in trades if str(x.direction).upper()=="SHORT")
    return {
        "long": compute_metrics(long_t).payload(),
        "short": compute_metrics(short_t).payload(),
    }


def evaluate_era(
    bars: Sequence[Bar],
    *,
    era_id: str,
    era_start,
    era_end,
    pip_size: float,
    base_costs,
    stressed_costs,
    broker_spec: BrokerLotSpec,
    leverage_tiers: Sequence[LeverageTier],
) -> dict[str,Any]:
    rows=tuple(sorted(bars,key=lambda x:ensure_utc(x.timestamp)))
    start=ensure_utc(era_start); end=ensure_utc(era_end)
    if not rows:
        raise ValueError("V31_EMPTY_HISTORY")
    if ensure_utc(rows[0].timestamp) >= start:
        raise ValueError("V31_WARMUP_REQUIRED")

    candidates=_portfolio_candidates(
        rows,base_costs=base_costs,stressed_costs=stressed_costs,pip_size=pip_size
    )
    classic_base=_simulate_d1_classic(rows,costs=base_costs,pip_size=pip_size)
    classic_stress=_simulate_d1_classic(rows,costs=stressed_costs,pip_size=pip_size)
    l20b=candidates["M15_L20_ONLY"]["base"]; l20s=candidates["M15_L20_ONLY"]["stress"]
    l12b=candidates["M15_L12_ONLY"]["base"]; l12s=candidates["M15_L12_ONLY"]["stress"]
    candidates={
        **candidates,
        "D1_CLASSIC":{"base":classic_base,"stress":classic_stress},
        "D1_CLASSIC_PLUS_L20":{
            "base":_limit_concurrency(_dedupe_with_classic((*classic_base,*l20b))),
            "stress":_limit_concurrency(_dedupe_with_classic((*classic_stress,*l20s))),
        },
        "D1_CLASSIC_PLUS_L12_L20":{
            "base":_limit_concurrency(_dedupe_with_classic((*classic_base,*l12b,*l20b))),
            "stress":_limit_concurrency(_dedupe_with_classic((*classic_stress,*l12s,*l20s))),
        },
    }
    dates=_trading_dates(rows,start=start,end=end)
    out={}
    for portfolio_id in PORTFOLIOS:
        trades=_period(candidates[portfolio_id]["stress"],start=start,end=end)
        cash=_cash_path_stopout_safe(
            trades,spec=broker_spec,tiers=leverage_tiers,
            account_leverage=ACCOUNT_LEVERAGE,
            stopout_pct=MARGIN_FLOOR_PCT,
            trading_dates=dates,
        )
        out[portfolio_id]={
            "available_trades":len(trades),
            "metrics":compute_metrics(trades).payload(),
            "direction_metrics":_direction_metrics(trades),
            "cash_fixed_001":cash,
        }

    return {
        "research_version":RESEARCH_VERSION,
        "policy_effect":POLICY_EFFECT,
        "execution_influence":EXECUTION_INFLUENCE,
        "live_execution_enabled":False,
        "diagnostic_only":DIAGNOSTIC_ONLY,
        "promotion_eligible":False,
        "era_id":era_id,
        "era_start":start.isoformat(),
        "era_end_exclusive":end.isoformat(),
        "history_rows":len(rows),
        "history_start":ensure_utc(rows[0].timestamp).isoformat(),
        "history_end":ensure_utc(rows[-1].timestamp).isoformat(),
        "account_contract":{
            "starting_balance_usd":100.0,
            "fixed_lot":0.01,
            "account_leverage":ACCOUNT_LEVERAGE,
            "planned_stop_margin_floor_pct":MARGIN_FLOOR_PCT,
            "risk_pct_filter":None,
            "broker_volume":asdict(broker_spec),
            "dynamic_leverage_tiers":[asdict(x) for x in leverage_tiers],
        },
        "portfolio_results":out,
        "interpretation":(
            "Alternate-feed era robustness using Dukascopy BID M15 plus explicit broker-like "
            "transaction-cost stress. Exact V20/V24 D1+M15 signal rules are unchanged. "
            "Results are historical diagnostics only and do not grant execution authority."
        ),
    }

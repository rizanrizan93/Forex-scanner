from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from .demo_donchian_adaptive_tournament import TournamentTrade, compute_metrics
from .models import Bar, ensure_utc
from .research_xau_2025_bootstrap_onset_forensic_v122 import build_v122_feature_frame
from .research_xau_100usd_stopout_v23 import _symbol_leverage
from .research_xau_champion_onset_reaccel_v123 import build_reaccel_route_frame
from .research_xau_false_onset_forensic_v125 import annotate_compressed_epochs
from .research_xau_multihorizon_100usd_v20 import _portfolio_candidates
from .research_xau_qualitative_reaccel_gate_v126 import passes_qualitative_gate
from .research_xau_v110_robustness_v111 import assemble_v110_selector
from .research_xau_v126_robustness_v127 import _route

RESEARCH_VERSION="XAU_RUNTIME_FEASIBILITY_V128"
ARTIFACT_CONTRACT="XAU_RUNTIME_FEASIBILITY_V128_EVIDENCE_1"
POLICY_EFFECT="SHADOW_ONLY"
EXECUTION_INFLUENCE=False
PROMOTION_ELIGIBLE=False

PER_TRADE_RISK_PCT=20.0
PORTFOLIO_RISK_PCT=20.0
MARGIN_FREE_USAGE_PCT=25.0
MAX_POSITIONS=10
STOPOUT_PCT=50.0
LOT=0.01

SCENARIOS=(
    ("LIVE_100_1_100",100.0,100.0),
    ("DEMO_342_1_30",342.0,30.0),
    ("DEMO_850_1_30",850.0,30.0),
)

@dataclass(frozen=True)
class GuardedResult:
    starting_balance: float
    ending_balance: float
    opened: int
    risk_skips: int
    portfolio_risk_skips: int
    margin_cap_skips: int
    stopout_skips: int
    max_positions_skips: int
    max_active: int
    min_balance: float
    max_drawdown_pct: float
    hit_1000_at: str|None


def _metrics(trades:Sequence[TournamentTrade])->dict[str,Any]:
    return compute_metrics(tuple(trades)).payload()


def _period(trades:Sequence[TournamentTrade],start,end)->tuple[TournamentTrade,...]:
    a=ensure_utc(start);b=ensure_utc(end)
    return tuple(t for t in trades if a<=ensure_utc(t.entry_at)<b)


def _margin_for_trade(trade:TournamentTrade,*,spec,tiers,account_leverage:float)->float:
    units=float(spec.contract_units_per_lot)*LOT
    notional=abs(float(trade.entry_price))*units
    symbol_lev=_symbol_leverage(tiers,notional)
    effective=float(account_leverage) if symbol_lev is None else min(float(account_leverage),float(symbol_lev))
    return notional/effective


def _loss_to_stop(trade:TournamentTrade,*,spec)->float:
    units=float(spec.contract_units_per_lot)*LOT
    return abs(float(trade.entry_price)-float(trade.stop_loss))*units


def _capital_floor_single_trade(trade:TournamentTrade,*,spec,tiers,account_leverage:float)->dict[str,float]:
    loss=_loss_to_stop(trade,spec=spec)
    margin=_margin_for_trade(trade,spec=spec,tiers=tiers,account_leverage=account_leverage)
    risk_floor=loss/(PER_TRADE_RISK_PCT/100.0)
    margin_floor=margin/(MARGIN_FREE_USAGE_PCT/100.0)
    return {
        "stop_loss_usd":float(loss),
        "expected_margin_usd":float(margin),
        "risk_floor_balance_usd":float(risk_floor),
        "margin_floor_balance_usd":float(margin_floor),
        "single_trade_floor_balance_usd":float(max(risk_floor,margin_floor)),
    }


def simulate_runtime_guards(
    trades:Sequence[TournamentTrade],
    *,
    spec,
    tiers,
    start_balance:float,
    account_leverage:float,
)->dict[str,Any]:
    balance=float(start_balance)
    peak=balance
    min_balance=balance
    max_dd_pct=0.0
    active:dict[int,dict[str,float]]={}
    opened=0
    risk_skips=0
    portfolio_risk_skips=0
    margin_cap_skips=0
    stopout_skips=0
    max_positions_skips=0
    max_active=0
    accepted:list[TournamentTrade]=[]
    hit_1000_at=None

    events=[]
    ordered=sorted(trades,key=lambda t:(ensure_utc(t.entry_at),ensure_utc(t.exit_at)))
    for idx,t in enumerate(ordered):
        events.append((ensure_utc(t.entry_at),1,idx,"ENTRY",t))
        events.append((ensure_utc(t.exit_at),0,idx,"EXIT",t))
    events.sort(key=lambda x:(x[0],x[1],x[2]))

    for at,_,idx,kind,trade in events:
        if kind=="EXIT":
            state=active.pop(idx,None)
            if state is None:
                continue
            balance+=state["pnl_usd"]
            min_balance=min(min_balance,balance)
            peak=max(peak,balance)
            if peak>0:
                max_dd_pct=max(max_dd_pct,100.0*(peak-balance)/peak)
            if hit_1000_at is None and balance>=1000.0:
                hit_1000_at=at.isoformat()
            continue

        if balance<=0:
            continue
        if len(active)>=MAX_POSITIONS:
            max_positions_skips+=1
            continue

        planned_loss=_loss_to_stop(trade,spec=spec)
        per_trade_cap=balance*(PER_TRADE_RISK_PCT/100.0)
        if planned_loss>per_trade_cap+1e-9:
            risk_skips+=1
            continue

        existing_risk=sum(x["planned_loss_usd"] for x in active.values())
        portfolio_cap=balance*(PORTFOLIO_RISK_PCT/100.0)
        if existing_risk+planned_loss>portfolio_cap+1e-9:
            portfolio_risk_skips+=1
            continue

        current_margin=sum(x["margin_usd"] for x in active.values())
        margin_free=max(0.0,balance-current_margin)
        margin_capital=margin_free*(MARGIN_FREE_USAGE_PCT/100.0)
        margin=_margin_for_trade(trade,spec=spec,tiers=tiers,account_leverage=account_leverage)
        if margin>margin_capital+1e-9:
            margin_cap_skips+=1
            continue

        candidate_margin=current_margin+margin
        worst_equity=balance-(existing_risk+planned_loss)
        margin_level=float("inf") if candidate_margin<=0 else 100.0*worst_equity/candidate_margin
        if margin_level<=STOPOUT_PCT:
            stopout_skips+=1
            continue

        risk_price=abs(float(trade.entry_price)-float(trade.stop_loss))
        units=float(spec.contract_units_per_lot)*LOT
        pnl=float(trade.net_r)*risk_price*units
        active[idx]={
            "planned_loss_usd":planned_loss,
            "margin_usd":margin,
            "pnl_usd":pnl,
        }
        opened+=1
        accepted.append(trade)
        max_active=max(max_active,len(active))

    m=_metrics(accepted)
    return {
        "starting_balance_usd":float(start_balance),
        "account_leverage":float(account_leverage),
        "ending_balance_usd":float(balance),
        "return_pct":float((balance/start_balance-1.0)*100.0),
        "opened_trades":opened,
        "available_trades":len(trades),
        "acceptance_rate":0.0 if not trades else float(opened/len(trades)),
        "risk_skips":risk_skips,
        "portfolio_risk_skips":portfolio_risk_skips,
        "margin_cap_skips":margin_cap_skips,
        "stopout_skips":stopout_skips,
        "max_positions_skips":max_positions_skips,
        "max_active_positions":max_active,
        "minimum_balance_usd":float(min_balance),
        "max_realized_drawdown_pct":float(max_dd_pct),
        "hit_1000":hit_1000_at is not None,
        "hit_1000_at":hit_1000_at,
        "accepted_metrics":m,
    }


def _floor_summary(trades:Sequence[TournamentTrade],*,spec,tiers,account_leverage:float)->dict[str,Any]:
    rows=[_capital_floor_single_trade(t,spec=spec,tiers=tiers,account_leverage=account_leverage) for t in trades]
    if not rows:
        return {"n":0}
    out={"n":len(rows)}
    for key in ("stop_loss_usd","expected_margin_usd","risk_floor_balance_usd","margin_floor_balance_usd","single_trade_floor_balance_usd"):
        vals=np.asarray([r[key] for r in rows],dtype=float)
        out[key]={
            "min":float(vals.min()),"p25":float(np.quantile(vals,.25)),
            "median":float(np.median(vals)),"p75":float(np.quantile(vals,.75)),
            "max":float(vals.max()),
        }
    return out


def _by_strategy_floor(trades:Sequence[TournamentTrade],*,spec,tiers,account_leverage:float)->dict[str,Any]:
    ids=sorted({str(t.strategy_id) for t in trades})
    return {
        sid:_floor_summary(tuple(t for t in trades if str(t.strategy_id)==sid),spec=spec,tiers=tiers,account_leverage=account_leverage)
        for sid in ids
    }


def evaluate_v128(
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

    v24=_portfolio_candidates(
        bars,base_costs=costs,stressed_costs=costs,pip_size=pip_size
    )["D1_PLUS_L12_L20"]["stress"]
    v24=_period(v24,datetime(2012,1,1,tzinfo=timezone.utc),end)

    frame=build_v122_feature_frame(bars)
    _,epoch_defs=build_reaccel_route_frame(frame,route_id="COMPRESSED_REACCEL")
    _,selector_all,_=assemble_v110_selector(
        bars,costs=costs,pip_size=pip_size,evaluation_end=end
    )
    selector=tuple(t for t in selector_all if ensure_utc(t.entry_at)<end)
    epoch_records=annotate_compressed_epochs(frame,epoch_defs,selector)
    v126=_route(selector,epoch_records,end=end,predicate=passes_qualitative_gate)
    v126=_period(v126,datetime(2012,1,1,tzinfo=timezone.utc),end)

    portfolios={"V24_EXACT":v24,"V126_GATED_V110":v126}
    results={}
    for pid,trades in portfolios.items():
        scenario_rows={}
        for sid,start_balance,lev in SCENARIOS:
            scenario_rows[sid]=simulate_runtime_guards(
                trades,spec=broker_spec,tiers=leverage_tiers,
                start_balance=start_balance,account_leverage=lev,
            )
        results[pid]={
            "unconstrained_metrics":_metrics(trades),
            "runtime_scenarios":scenario_rows,
            "single_trade_capital_floor_live_1_100":_floor_summary(
                trades,spec=broker_spec,tiers=leverage_tiers,account_leverage=100.0
            ),
            "single_trade_capital_floor_demo_1_30":_floor_summary(
                trades,spec=broker_spec,tiers=leverage_tiers,account_leverage=30.0
            ),
            "by_strategy_floor_live_1_100":_by_strategy_floor(
                trades,spec=broker_spec,tiers=leverage_tiers,account_leverage=100.0
            ),
            "by_strategy_floor_demo_1_30":_by_strategy_floor(
                trades,spec=broker_spec,tiers=leverage_tiers,account_leverage=30.0
            ),
        }

    current_v24_d1={
        "entry":4372.83,
        "stop":4203.252090040158,
        "lot":0.01,
    }
    pseudo=type("Pseudo",(object,),{
        "entry_price":current_v24_d1["entry"],
        "stop_loss":current_v24_d1["stop"],
    })()
    current_v24_d1["live_1_100_floor"]=_capital_floor_single_trade(
        pseudo,spec=broker_spec,tiers=leverage_tiers,account_leverage=100.0
    )
    current_v24_d1["demo_1_30_floor"]=_capital_floor_single_trade(
        pseudo,spec=broker_spec,tiers=leverage_tiers,account_leverage=30.0
    )
    current_v24_d1["risk_pct_on_demo_342"]=100.0*current_v24_d1["demo_1_30_floor"]["stop_loss_usd"]/342.0
    current_v24_d1["risk_pct_on_live_100"]=100.0*current_v24_d1["live_1_100_floor"]["stop_loss_usd"]/100.0

    return {
        "research_version":RESEARCH_VERSION,
        "artifact_contract":ARTIFACT_CONTRACT,
        "policy_effect":POLICY_EFFECT,
        "execution_influence":EXECUTION_INFLUENCE,
        "promotion_eligible":PROMOTION_ELIGIBLE,
        "live_execution_enabled":False,
        "contract":{
            "lot":LOT,
            "per_trade_risk_pct":PER_TRADE_RISK_PCT,
            "aggregate_open_risk_pct":PORTFOLIO_RISK_PCT,
            "margin_free_usage_pct":MARGIN_FREE_USAGE_PCT,
            "max_positions":MAX_POSITIONS,
            "stopout_pct":STOPOUT_PCT,
            "runtime_parity_note":"historical equity is approximated by realized balance; active-position risk is conservatively held at planned entry-to-SL loss until exit",
            "margin_model":"historical notional / min(account leverage, frozen broker leverage tier); live runtime uses broker expected-margin endpoint",
            "no_guard_changes":True,
            "no_execution_authority":True,
        },
        "scenarios":[{"id":x[0],"start_balance":x[1],"account_leverage":x[2]} for x in SCENARIOS],
        "current_v24_d1_reference":current_v24_d1,
        "portfolios":results,
    }

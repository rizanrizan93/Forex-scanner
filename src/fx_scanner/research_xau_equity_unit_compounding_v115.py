from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

from .models import ensure_utc
from .research_xau_100usd_leverage_v22 import _lot_feasible, _symbol_leverage
from .research_xau_margin_leverage_v21 import LeverageTier
from .research_xau_multihorizon_100usd_v20 import BrokerLotSpec, MAX_ACTIVE_POSITIONS, _trading_dates
from .research_xau_capital_preservation_v114 import build_capital_preservation_portfolio

RESEARCH_VERSION="XAU_EQUITY_UNIT_COMPOUNDING_V115"
ARTIFACT_CONTRACT="XAU_EQUITY_UNIT_COMPOUNDING_V115_EVIDENCE_1"
POLICY_EFFECT="SHADOW_ONLY"
EXECUTION_INFLUENCE=False
PROMOTION_ELIGIBLE=False

STARTING_BALANCE_USD=100.0
ACCOUNT_LEVERAGE=100.0
BROKER_STOPOUT_PCT=50.0
MIN_LOT=0.01
MAX_LOT=0.50
LOT_STEP=0.01
EQUITY_UNIT_USD=100.0


def _target_lot(balance:float)->float:
    units=max(1,int(math.floor(max(0.0,balance)/EQUITY_UNIT_USD)))
    lot=min(MAX_LOT,units*MIN_LOT)
    steps=math.floor((lot+1e-12)/LOT_STEP)
    return round(max(MIN_LOT,steps*LOT_STEP),2)


def cash_path_equity_unit(
    trades,
    *,
    spec:BrokerLotSpec,
    tiers:Sequence[LeverageTier],
    trading_dates:Sequence[Any],
    evaluation_start,
    evaluation_end,
)->dict[str,Any]:
    balance=STARTING_BALANCE_USD
    peak=balance
    min_balance=balance
    max_dd=0.0
    max_dd_pct=0.0
    active={}
    opened=0
    margin_skips=0
    stopout_guard_skips=0
    size_reductions=0
    ruin=False
    max_lot_used=0.0
    max_active=0
    max_margin_used=0.0
    min_margin_level=float("inf")
    first_1000=None
    first_10000=None
    checkpoints={}
    losing_streak=0
    max_losing_streak=0

    marks={
        "START_2012":ensure_utc(evaluation_start),
        "START_2019":ensure_utc(evaluation_start).replace(year=2019,month=1,day=1),
        "START_2025":ensure_utc(evaluation_start).replace(year=2025,month=1,day=1),
        "END_2026YTD":ensure_utc(evaluation_end),
    }
    cps=sorted((ts,label) for label,ts in marks.items())
    cp_i=0

    ordered=sorted(trades,key=lambda x:(ensure_utc(x.entry_at),ensure_utc(x.exit_at)))
    events=[]
    for idx,t in enumerate(ordered):
        events.append((ensure_utc(t.entry_at),1,idx,"ENTRY",t))
        events.append((ensure_utc(t.exit_at),0,idx,"EXIT",t))
    events.sort(key=lambda x:(x[0],x[1],x[2]))

    def record(label,ts):
        checkpoints[label]={
            "at":ensure_utc(ts).isoformat(),
            "realized_balance_usd":float(balance),
            "target_lot":_target_lot(balance),
            "active_positions":len(active),
            "margin_used_usd":float(sum(float(x["margin_usd"]) for x in active.values())),
        }

    for ts,_,idx,kind,trade in events:
        while cp_i<len(cps) and cps[cp_i][0]<=ts:
            record(cps[cp_i][1],cps[cp_i][0]);cp_i+=1

        if kind=="EXIT":
            state=active.pop(idx,None)
            if state is None:
                continue
            pnl=float(state["pnl_usd"])
            balance+=pnl
            min_balance=min(min_balance,balance)
            peak=max(peak,balance)
            dd=peak-balance
            max_dd=max(max_dd,dd)
            if peak>0:
                max_dd_pct=max(max_dd_pct,100.0*dd/peak)
            if pnl<0:
                losing_streak+=1
                max_losing_streak=max(max_losing_streak,losing_streak)
            else:
                losing_streak=0
            if first_1000 is None and balance>=1000.0:
                first_1000=ts.isoformat()
            if first_10000 is None and balance>=10000.0:
                first_10000=ts.isoformat()
            if balance<=0:
                ruin=True
            continue

        if ruin:
            continue
        if len(active)>=MAX_ACTIVE_POSITIONS:
            margin_skips+=1
            continue

        target=_target_lot(balance)
        current_margin=sum(float(x["margin_usd"]) for x in active.values())
        existing_loss=sum(float(x["planned_loss_usd"]) for x in active.values())
        risk_price=abs(float(trade.entry_price)-float(trade.stop_loss))
        cost_multiplier=1.0+max(0.0,float(trade.cost_r))

        chosen=None
        candidate_lot=target
        while candidate_lot>=MIN_LOT-1e-12:
            candidate_lot=round(candidate_lot,2)
            if _lot_feasible(spec,candidate_lot):
                units=spec.contract_units_per_lot*candidate_lot
                notional=abs(float(trade.entry_price))*units
                symbol_lev=_symbol_leverage(tiers,notional)
                effective=ACCOUNT_LEVERAGE if symbol_lev is None else min(ACCOUNT_LEVERAGE,symbol_lev)
                margin=notional/effective
                planned_loss=risk_price*units*cost_multiplier
                candidate_margin=current_margin+margin
                worst_equity=balance-(existing_loss+planned_loss)
                margin_level=float("inf") if candidate_margin<=0 else 100.0*worst_equity/candidate_margin
                if balance-current_margin>=margin and margin_level>BROKER_STOPOUT_PCT:
                    chosen=(candidate_lot,units,margin,planned_loss,margin_level)
                    break
            candidate_lot=round(candidate_lot-LOT_STEP,2)

        if chosen is None:
            min_units=spec.contract_units_per_lot*MIN_LOT
            min_notional=abs(float(trade.entry_price))*min_units
            min_symbol_lev=_symbol_leverage(tiers,min_notional)
            min_effective=ACCOUNT_LEVERAGE if min_symbol_lev is None else min(ACCOUNT_LEVERAGE,min_symbol_lev)
            min_margin=min_notional/min_effective
            if balance-current_margin<min_margin:
                margin_skips+=1
            else:
                stopout_guard_skips+=1
            continue

        lot,units,margin,planned_loss,margin_level=chosen
        if lot<target:
            size_reductions+=1
        active[idx]={
            "lot":lot,
            "margin_usd":margin,
            "planned_loss_usd":planned_loss,
            "pnl_usd":float(trade.net_r)*risk_price*units,
        }
        opened+=1
        max_lot_used=max(max_lot_used,lot)
        max_active=max(max_active,len(active))
        max_margin_used=max(max_margin_used,sum(float(x["margin_usd"]) for x in active.values()))
        min_margin_level=min(min_margin_level,margin_level)

    while cp_i<len(cps):
        record(cps[cp_i][1],cps[cp_i][0]);cp_i+=1

    return {
        "starting_balance_usd":STARTING_BALANCE_USD,
        "ending_balance_usd":float(balance),
        "net_profit_usd":float(balance-STARTING_BALANCE_USD),
        "return_pct":float((balance/STARTING_BALANCE_USD-1.0)*100.0),
        "account_leverage":ACCOUNT_LEVERAGE,
        "risk_pct_filter":None,
        "sizing_policy":"floor(realized_balance / $100) * 0.01 lot, broker-feasibility de-risk fallback",
        "equity_unit_usd":EQUITY_UNIT_USD,
        "min_lot":MIN_LOT,
        "max_lot":MAX_LOT,
        "max_lot_used":float(max_lot_used),
        "opened_trades":opened,
        "margin_skips":margin_skips,
        "stopout_guard_skips":stopout_guard_skips,
        "size_reductions":size_reductions,
        "minimum_realized_balance_usd":float(min_balance),
        "max_realized_drawdown_usd":float(max_dd),
        "max_realized_drawdown_pct":float(max_dd_pct),
        "max_losing_streak":int(max_losing_streak),
        "max_active_positions":int(max_active),
        "max_margin_used_usd":float(max_margin_used),
        "minimum_planned_stop_margin_level_pct":None if min_margin_level==float("inf") else float(min_margin_level),
        "ruin":bool(ruin),
        "hit_1000":first_1000 is not None,
        "hit_1000_at":first_1000,
        "hit_10000":first_10000 is not None,
        "hit_10000_at":first_10000,
        "trading_days":len(set(trading_dates)),
        "checkpoints":checkpoints,
    }


def evaluate_v115(
    rows,
    *,
    evaluation_start,
    evaluation_end,
    pip_size:float,
    cost_scenarios:Mapping[str,Any],
    broker_spec:BrokerLotSpec,
    leverage_tiers:Sequence[LeverageTier],
)->dict[str,Any]:
    bars=tuple(sorted(rows,key=lambda x:ensure_utc(x.timestamp)))
    start=ensure_utc(evaluation_start);end=ensure_utc(evaluation_end)
    dates=_trading_dates(bars,start=start,end=end)
    scenarios={}
    for cost_id,costs in cost_scenarios.items():
        _,_,portfolio,diag=build_capital_preservation_portfolio(
            bars,costs=costs,pip_size=pip_size,evaluation_end=end
        )
        p=tuple(t for t in portfolio if start<=ensure_utc(t.entry_at)<end)
        cash=cash_path_equity_unit(
            p,
            spec=broker_spec,
            tiers=leverage_tiers,
            trading_dates=dates,
            evaluation_start=start,
            evaluation_end=end,
        )
        scenarios[cost_id]={
            "available_trades":len(p),
            "signal_metrics":compute_metrics(p).payload(),
            "capital_preservation_diagnostics":diag,
            "cash_equity_unit":cash,
        }
    return {
        "research_version":RESEARCH_VERSION,
        "artifact_contract":ARTIFACT_CONTRACT,
        "policy_effect":POLICY_EFFECT,
        "execution_influence":EXECUTION_INFLUENCE,
        "promotion_eligible":PROMOTION_ELIGIBLE,
        "live_execution_enabled":False,
        "contract":{
            "routing":"corrected V114 capital-preservation state",
            "starting_balance_usd":STARTING_BALANCE_USD,
            "account_leverage":ACCOUNT_LEVERAGE,
            "risk_pct_filter":None,
            "broker_stopout_pct":BROKER_STOPOUT_PCT,
            "equity_unit_usd":EQUITY_UNIT_USD,
            "lot_rule":"0.01 lot per full $100 realized equity",
            "lot_rule_anchor":"starting balance and broker minimum lot; not optimized",
            "automatic_descaling":True,
            "max_lot":MAX_LOT,
            "calendar_year_used_for_routing":False,
            "parameter_search":False,
        },
        "scenarios":scenarios,
        "note":"V115 changes sizing only. V114 routing/state logic is frozen. The sizing rule compounds in discrete $100 equity units and falls back to smaller lots only when broker margin/stop-out survivability requires it.",
    }

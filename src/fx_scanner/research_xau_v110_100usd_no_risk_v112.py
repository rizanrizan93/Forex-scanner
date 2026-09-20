from __future__ import annotations

from typing import Any, Mapping, Sequence

from .models import ensure_utc
from .research_xau_100usd_leverage_v22 import _lot_feasible, _symbol_leverage
from .research_xau_100usd_stopout_v23 import _cash_path_stopout_safe
from .research_xau_margin_leverage_v21 import LeverageTier
from .research_xau_multihorizon_100usd_v20 import BrokerLotSpec, MAX_ACTIVE_POSITIONS, _trading_dates
from .research_xau_v110_robustness_v111 import assemble_v110_selector

RESEARCH_VERSION="XAU_V110_100USD_NO_RISK_V112"
ARTIFACT_CONTRACT="XAU_V110_100USD_NO_RISK_V112_EVIDENCE_1"
POLICY_EFFECT="SHADOW_ONLY"
EXECUTION_INFLUENCE=False
PROMOTION_ELIGIBLE=False

STARTING_BALANCE_USD=100.0
ACCOUNT_LEVERAGE=100.0
BROKER_STOPOUT_PCT=50.0
FIXED_LOT=0.01
DYNAMIC_MIN_LOT=0.01
DYNAMIC_MAX_LOT=0.50
DYNAMIC_LOT_STEP=0.01


def _checkpoints(trades, *, start, end):
    marks={
        "START_2012":ensure_utc(start),
        "START_2019":ensure_utc(start).replace(year=2019,month=1,day=1),
        "START_2025":ensure_utc(start).replace(year=2025,month=1,day=1),
        "END_2026YTD":ensure_utc(end),
    }
    ordered=sorted(trades,key=lambda x:(ensure_utc(x.entry_at),ensure_utc(x.exit_at)))
    return marks,ordered


def _cash_path_dynamic_no_risk(
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
    ruin=False
    max_active=0
    max_margin_used=0.0
    min_margin_level=float("inf")
    max_lot_used=0.0
    first_1000=None
    first_10000=None
    losing_streak=0
    max_losing_streak=0

    checkpoint_times,ordered=_checkpoints(
        trades,start=evaluation_start,end=evaluation_end
    )
    cps=sorted((ts,label) for label,ts in checkpoint_times.items())
    cp_i=0
    checkpoint_out={}

    events=[]
    for idx,t in enumerate(ordered):
        events.append((ensure_utc(t.entry_at),1,idx,"ENTRY",t))
        events.append((ensure_utc(t.exit_at),0,idx,"EXIT",t))
    events.sort(key=lambda x:(x[0],x[1],x[2]))

    def record(label,ts):
        checkpoint_out[label]={
            "at":ensure_utc(ts).isoformat(),
            "realized_balance_usd":float(balance),
            "active_positions":len(active),
            "margin_used_usd":float(sum(float(x["margin_usd"]) for x in active.values())),
        }

    def lot_grid_desc():
        steps=int(round((DYNAMIC_MAX_LOT-DYNAMIC_MIN_LOT)/DYNAMIC_LOT_STEP))
        return [round(DYNAMIC_MAX_LOT-i*DYNAMIC_LOT_STEP,2) for i in range(steps+1)]

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
            if first_1000 is None and balance>=1000:
                first_1000=ts.isoformat()
            if first_10000 is None and balance>=10000:
                first_10000=ts.isoformat()
            if balance<=0:
                ruin=True
            continue

        if ruin:
            continue
        if len(active)>=MAX_ACTIVE_POSITIONS:
            margin_skips+=1
            continue

        current_margin=sum(float(x["margin_usd"]) for x in active.values())
        existing_loss=sum(float(x["planned_loss_usd"]) for x in active.values())
        chosen=None
        risk_price=abs(float(trade.entry_price)-float(trade.stop_loss))
        cost_multiplier=1.0+max(0.0,float(trade.cost_r))

        for lot in lot_grid_desc():
            if not _lot_feasible(spec,lot):
                continue
            units=spec.contract_units_per_lot*lot
            notional=abs(float(trade.entry_price))*units
            symbol_lev=_symbol_leverage(tiers,notional)
            effective=ACCOUNT_LEVERAGE if symbol_lev is None else min(ACCOUNT_LEVERAGE,symbol_lev)
            margin=notional/effective
            if balance-current_margin<margin:
                continue
            planned_loss=risk_price*units*cost_multiplier
            candidate_margin=current_margin+margin
            worst_equity=balance-(existing_loss+planned_loss)
            margin_level=float("inf") if candidate_margin<=0 else 100.0*worst_equity/candidate_margin
            if margin_level<=BROKER_STOPOUT_PCT:
                continue
            chosen=(lot,units,margin,planned_loss,margin_level)
            break

        if chosen is None:
            # Distinguish physical margin failure from planned stop-out survivability.
            min_units=spec.contract_units_per_lot*DYNAMIC_MIN_LOT
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
        active[idx]={
            "lot":lot,
            "margin_usd":margin,
            "planned_loss_usd":planned_loss,
            "pnl_usd":float(trade.net_r)*risk_price*units,
        }
        opened+=1
        max_lot_used=max(max_lot_used,lot)
        max_active=max(max_active,len(active))
        max_margin_used=max(
            max_margin_used,
            sum(float(x["margin_usd"]) for x in active.values())
        )
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
        "lot_policy":"largest 0.01-step lot <=0.50 satisfying free-margin and 50% broker stop-out survivability",
        "min_lot":DYNAMIC_MIN_LOT,
        "max_lot":DYNAMIC_MAX_LOT,
        "max_lot_used":float(max_lot_used),
        "opened_trades":opened,
        "margin_skips":margin_skips,
        "stopout_guard_skips":stopout_guard_skips,
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
        "checkpoints":checkpoint_out,
    }


def evaluate_v112(
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
        _,selector_all,_=assemble_v110_selector(
            bars,costs=costs,pip_size=pip_size,evaluation_end=end
        )
        selector=tuple(t for t in selector_all if start<=ensure_utc(t.entry_at)<end)
        fixed=_cash_path_stopout_safe(
            selector,
            spec=broker_spec,
            tiers=leverage_tiers,
            account_leverage=ACCOUNT_LEVERAGE,
            stopout_pct=BROKER_STOPOUT_PCT,
            trading_dates=dates,
        )
        dynamic=_cash_path_dynamic_no_risk(
            selector,
            spec=broker_spec,
            tiers=leverage_tiers,
            trading_dates=dates,
            evaluation_start=start,
            evaluation_end=end,
        )
        scenarios[cost_id]={
            "available_selector_trades":len(selector),
            "fixed_001_no_risk_cap":fixed,
            "dynamic_001_to_050_no_risk_cap":dynamic,
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
            "evaluation_start":start.isoformat(),
            "evaluation_end_exclusive":end.isoformat(),
            "starting_balance_usd":STARTING_BALANCE_USD,
            "account_leverage":ACCOUNT_LEVERAGE,
            "risk_pct_filter":None,
            "max_active_positions":MAX_ACTIVE_POSITIONS,
            "broker_stopout_pct":BROKER_STOPOUT_PCT,
            "fixed_path_lot":FIXED_LOT,
            "dynamic_path_lot_range":[DYNAMIC_MIN_LOT,DYNAMIC_MAX_LOT],
            "dynamic_lot_step":DYNAMIC_LOT_STEP,
            "margin_and_stopout_constraints_retained":True,
            "calendar_year_used_for_routing":False,
        },
        "scenarios":scenarios,
        "note":"V112 is a historical diagnostic only. It removes percentage-risk limits but retains physical broker margin and 50% stop-out survivability. Dynamic sizing is deliberately aggressive and is not a live recommendation.",
    }

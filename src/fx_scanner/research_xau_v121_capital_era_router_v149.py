from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from .demo_donchian_adaptive_tournament import TournamentTrade, compute_metrics
from .models import Bar, ensure_utc
from .research_xau_100usd_leverage_v22 import _lot_feasible, _symbol_leverage
from .research_xau_era_robustness_v31 import _dedupe_with_classic
from .research_xau_multihorizon_100usd_v20 import (
    BrokerLotSpec,
    MAX_ACTIVE_POSITIONS,
    MIN_LOT,
    STARTING_BALANCE_USD,
)
from .research_xau_v110_robustness_v111 import assemble_v110_selector

RESEARCH_VERSION="XAU_CAPITAL_ERA_ROUTER_V149"
ARTIFACT_CONTRACT="XAU_CAPITAL_ERA_ROUTER_V149_EVIDENCE_1"
POLICY_EFFECT="SHADOW_ONLY"
EXECUTION_INFLUENCE=False
PROMOTION_ELIGIBLE=False

BOOTSTRAP_THRESHOLD_USD=1000.0
ACCOUNT_LEVERAGE=100.0
STOPOUT_PCT=50.0

CORE_ID="V31_D1_TSMOM_CLASSIC"
D1_ID="V20_D1_TSMOM_C1_R200"
L12_ID="V20_M15_L12_ADX12_D1_R150"
L20_ID="V20_M15_L20_ADX15_D1_R200"

ERA_WINDOWS=(
    ("2012_2018",datetime(2012,1,1,tzinfo=timezone.utc),datetime(2019,1,1,tzinfo=timezone.utc)),
    ("2019_2024",datetime(2019,1,1,tzinfo=timezone.utc),datetime(2025,1,1,tzinfo=timezone.utc)),
    ("2025_2026YTD",datetime(2025,1,1,tzinfo=timezone.utc),datetime(2026,9,20,tzinfo=timezone.utc)),
)
START_SENSITIVITY=(2012,2015,2019,2022,2025)


def _metrics(trades:Sequence[TournamentTrade])->dict[str,Any]:
    return compute_metrics(tuple(trades)).payload()


def _period(trades:Sequence[TournamentTrade],a,b)->tuple[TournamentTrade,...]:
    aa,bb=ensure_utc(a),ensure_utc(b)
    return tuple(t for t in trades if aa<=ensure_utc(t.entry_at)<bb)


def _candidate_portfolio(*groups:Sequence[TournamentTrade])->tuple[TournamentTrade,...]:
    return _dedupe_with_classic(tuple(t for g in groups for t in g))


def _admit(strategy_id:str,variant:str,balance:float)->bool:
    if variant=="CORE_ONLY":
        return strategy_id==CORE_ID
    if variant=="CORE_D1_ONLY":
        return strategy_id in {CORE_ID,D1_ID}
    if variant=="CORE_D1_L20_ALWAYS":
        return strategy_id in {CORE_ID,D1_ID,L20_ID}
    if variant=="CAPITAL_ERA_ROUTER":
        if strategy_id in {CORE_ID,D1_ID}:
            return True
        if strategy_id==L20_ID:
            return balance>=BOOTSTRAP_THRESHOLD_USD
        return False
    if variant=="FULL_V110":
        return strategy_id in {CORE_ID,D1_ID,L12_ID,L20_ID}
    raise ValueError(f"V149_UNKNOWN_VARIANT:{variant}")


def _cash_route(
    trades:Sequence[TournamentTrade],
    *,
    variant:str,
    spec:BrokerLotSpec,
    tiers,
    evaluation_start,
    evaluation_end,
)->dict[str,Any]:
    start,end=ensure_utc(evaluation_start),ensure_utc(evaluation_end)
    rows=_period(trades,start,end)
    balance=float(STARTING_BALANCE_USD)
    peak=balance
    max_dd_pct=0.0
    active={}
    accepted=[]
    ledger=[]
    state_transitions=[]
    last_state="MATURE" if balance>=BOOTSTRAP_THRESHOLD_USD else "BOOTSTRAP"

    events=[]
    for idx,t in enumerate(sorted(rows,key=lambda x:(ensure_utc(x.entry_at),ensure_utc(x.exit_at),x.strategy_id))):
        events.append((ensure_utc(t.entry_at),1,idx,"ENTRY",t))
        events.append((ensure_utc(t.exit_at),0,idx,"EXIT",t))
    events.sort(key=lambda x:(x[0],x[1],x[2]))

    skipped_by_reason={}
    skipped_by_strategy={}
    opened_by_strategy={}

    for ts,_,idx,kind,t in events:
        if kind=="EXIT":
            state=active.pop(idx,None)
            if state is None:
                continue
            before=balance
            balance+=float(state["pnl_usd"])
            peak=max(peak,balance)
            dd=0.0 if peak<=0 else 100.0*max(0.0,peak-balance)/peak
            max_dd_pct=max(max_dd_pct,dd)
            now_state="MATURE" if balance>=BOOTSTRAP_THRESHOLD_USD else "BOOTSTRAP"
            if now_state!=last_state:
                state_transitions.append({
                    "at":ts.isoformat(),
                    "from":last_state,
                    "to":now_state,
                    "balance":float(balance),
                    "trigger_strategy":t.strategy_id,
                })
                last_state=now_state
            ledger.append({
                "event":"EXIT","at":ts.isoformat(),"strategy_id":t.strategy_id,
                "pnl_usd":float(state["pnl_usd"]),"balance_before":float(before),
                "balance_after":float(balance),"state_after":now_state,
            })
            continue

        if not _admit(t.strategy_id,variant,balance):
            reason="CAPITAL_PHASE_BLOCK" if variant=="CAPITAL_ERA_ROUTER" and t.strategy_id==L20_ID else "VARIANT_BLOCK"
            skipped_by_reason[reason]=skipped_by_reason.get(reason,0)+1
            skipped_by_strategy[t.strategy_id]=skipped_by_strategy.get(t.strategy_id,0)+1
            continue

        lot=MIN_LOT
        if not _lot_feasible(spec,lot):
            skipped_by_reason["LOT_NOT_FEASIBLE"]=skipped_by_reason.get("LOT_NOT_FEASIBLE",0)+1
            continue

        units=spec.contract_units_per_lot*lot
        notional=abs(float(t.entry_price))*units
        symbol_lev=_symbol_leverage(tiers,notional)
        effective=ACCOUNT_LEVERAGE if symbol_lev is None else min(ACCOUNT_LEVERAGE,symbol_lev)
        margin=notional/effective
        current_margin=sum(float(x["margin_usd"]) for x in active.values())

        if len(active)>=MAX_ACTIVE_POSITIONS:
            skipped_by_reason["MAX_ACTIVE_POSITIONS"]=skipped_by_reason.get("MAX_ACTIVE_POSITIONS",0)+1
            continue
        if balance-current_margin<margin:
            skipped_by_reason["MARGIN_NOT_AVAILABLE"]=skipped_by_reason.get("MARGIN_NOT_AVAILABLE",0)+1
            continue

        risk_price=abs(float(t.entry_price)-float(t.stop_loss))
        cost_multiplier=1.0+max(0.0,float(t.cost_r))
        planned_loss=risk_price*units*cost_multiplier
        candidate_margin=current_margin+margin
        candidate_planned_loss=sum(float(x["planned_loss_usd"]) for x in active.values())+planned_loss
        worst_equity=balance-candidate_planned_loss
        margin_level=float("inf") if candidate_margin<=0 else 100.0*worst_equity/candidate_margin
        if margin_level<=STOPOUT_PCT:
            skipped_by_reason["PLANNED_STOPOUT_GUARD"]=skipped_by_reason.get("PLANNED_STOPOUT_GUARD",0)+1
            continue

        pnl_usd=float(t.net_r)*risk_price*units
        active[idx]={
            "margin_usd":margin,
            "planned_loss_usd":planned_loss,
            "pnl_usd":pnl_usd,
        }
        accepted.append(t)
        opened_by_strategy[t.strategy_id]=opened_by_strategy.get(t.strategy_id,0)+1
        ledger.append({
            "event":"ENTRY","at":ts.isoformat(),"strategy_id":t.strategy_id,
            "balance":float(balance),"state":"MATURE" if balance>=BOOTSTRAP_THRESHOLD_USD else "BOOTSTRAP",
            "margin_usd":float(margin),"planned_loss_usd":float(planned_loss),
            "planned_margin_level_pct":float(margin_level),
        })

    first_1000=next(
        (x for x in ledger if x["event"]=="EXIT" and float(x["balance_after"])>=BOOTSTRAP_THRESHOLD_USD),
        None,
    )
    return {
        "variant":variant,
        "starting_balance_usd":float(STARTING_BALANCE_USD),
        "ending_balance_usd":float(balance),
        "return_pct":100.0*(balance/STARTING_BALANCE_USD-1.0),
        "max_realized_drawdown_pct":float(max_dd_pct),
        "opened":len(accepted),
        "metrics":_metrics(accepted),
        "opened_by_strategy":opened_by_strategy,
        "skipped_by_strategy":skipped_by_strategy,
        "skipped_by_reason":skipped_by_reason,
        "first_1000_exit":first_1000,
        "state_transitions":state_transitions,
        "ending_state":"MATURE" if balance>=BOOTSTRAP_THRESHOLD_USD else "BOOTSTRAP",
    }


def evaluate_v149(
    rows:Sequence[Bar],*,
    evaluation_end,
    pip_size:float,
    costs,
    broker_spec:BrokerLotSpec,
    leverage_tiers,
)->dict[str,Any]:
    bars=tuple(sorted(rows,key=lambda x:ensure_utc(x.timestamp)))
    end=ensure_utc(evaluation_end)
    core_all,selector_all,selected=assemble_v110_selector(
        bars,costs=costs,pip_size=pip_size,evaluation_end=end
    )
    d1_all=tuple(selected["D1_STAGGERED"])
    l12_all=tuple(selected["M15_L12"])
    l20_all=tuple(selected["M15_L20"])
    universe=_candidate_portfolio(core_all,d1_all,l12_all,l20_all)

    variants=("CORE_ONLY","CORE_D1_ONLY","CORE_D1_L20_ALWAYS","CAPITAL_ERA_ROUTER","FULL_V110")

    eras={}
    for label,a,b in ERA_WINDOWS:
        bb=min(ensure_utc(b),end)
        if ensure_utc(a)>=bb:
            continue
        eras[label]={
            v:_cash_route(
                universe,variant=v,spec=broker_spec,tiers=leverage_tiers,
                evaluation_start=a,evaluation_end=bb,
            )
            for v in variants
        }

    start_sensitivity={}
    for year in START_SENSITIVITY:
        s=datetime(year,1,1,tzinfo=timezone.utc)
        if s>=end:
            continue
        start_sensitivity[str(year)]={
            v:_cash_route(
                universe,variant=v,spec=broker_spec,tiers=leverage_tiers,
                evaluation_start=s,evaluation_end=end,
            )
            for v in variants
        }

    return {
        "research_version":RESEARCH_VERSION,
        "artifact_contract":ARTIFACT_CONTRACT,
        "policy_effect":POLICY_EFFECT,
        "execution_influence":EXECUTION_INFLUENCE,
        "promotion_eligible":PROMOTION_ELIGIBLE,
        "live_execution_enabled":False,
        "contract":{
            "base_selector":"frozen causal V110 strategy-specific state selector",
            "capital_state":{
                "BOOTSTRAP":"realized balance < $1,000; CORE + selected D1_STAGGERED only",
                "MATURE":"realized balance >= $1,000; CORE + selected D1_STAGGERED + selected M15_L20",
                "demotion":"if realized balance drops below $1,000, M15_L20 is blocked again",
            },
            "M15_L12":"excluded by preregistered V121 follow-up hypothesis",
            "bootstrap_threshold_usd":BOOTSTRAP_THRESHOLD_USD,
            "account":"fresh $100 / leverage 1:100 / fixed 0.01 lot / 50% planned-stop floor",
            "era_windows":[x[0] for x in ERA_WINDOWS],
            "start_sensitivity_years":list(START_SENSITIVITY),
            "parameter_grid_search":False,
            "calendar_year_used_for_routing":False,
            "same_trade_outcome_used_for_entry":False,
            "execution_authority":False,
        },
        "eras":eras,
        "start_sensitivity":start_sensitivity,
        "note":"V149 adds only a realized-capital state machine on top of the frozen causal V110 selector. Era windows are evaluation slices, never routing inputs.",
    }

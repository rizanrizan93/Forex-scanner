from __future__ import annotations

from datetime import datetime, timezone
from math import floor
from typing import Any, Sequence

from .demo_donchian_adaptive_tournament import TournamentTrade, compute_metrics
from .models import Bar, ensure_utc
from .research_xau_100usd_leverage_v22 import _lot_feasible, _symbol_leverage
from .research_xau_capital_preservation_v114 import build_capital_preservation_portfolio
from .research_xau_era_robustness_v31 import _dedupe_with_classic
from .research_xau_multihorizon_100usd_v20 import BrokerLotSpec, MAX_ACTIVE_POSITIONS
from .research_xau_v110_robustness_v111 import assemble_v110_selector

RESEARCH_VERSION="XAU_ACCOUNT_COMPATIBLE_ERA_ROUTER_V150"
ARTIFACT_CONTRACT="XAU_ACCOUNT_COMPATIBLE_ERA_ROUTER_V150_EVIDENCE_1"
POLICY_EFFECT="SHADOW_ONLY"
EXECUTION_INFLUENCE=False
PROMOTION_ELIGIBLE=False

STARTING_BALANCE_USD=100.0
ACCOUNT_LEVERAGE=100.0
MIN_LOT=0.01
MAX_LOT=0.50
LOT_STEP=0.01
RISK_CAP_PCT=20.0
AGGREGATE_RISK_CAP_PCT=20.0
MARGIN_USAGE_CAP_PCT=50.0
BOOTSTRAP_THRESHOLD_USD=1000.0
STOPOUT_PCT=50.0

CORE_ID="V31_D1_TSMOM_CLASSIC"
D1_ID="V20_D1_TSMOM_C1_R200"
L20_ID="V20_M15_L20_ADX15_D1_R200"

ERA_WINDOWS=(
    ("2012_2018",datetime(2012,1,1,tzinfo=timezone.utc),datetime(2019,1,1,tzinfo=timezone.utc)),
    ("2019_2024",datetime(2019,1,1,tzinfo=timezone.utc),datetime(2025,1,1,tzinfo=timezone.utc)),
    ("2025_2026YTD",datetime(2025,1,1,tzinfo=timezone.utc),datetime(2026,9,20,tzinfo=timezone.utc)),
)
START_SENSITIVITY=(2012,2015,2019,2022,2025)


def _period(trades:Sequence[TournamentTrade],a,b)->tuple[TournamentTrade,...]:
    aa,bb=ensure_utc(a),ensure_utc(b)
    return tuple(t for t in trades if aa<=ensure_utc(t.entry_at)<bb)


def _metrics(trades): return compute_metrics(tuple(trades)).payload()


def _allowed_family(strategy_id:str,balance:float)->bool:
    if strategy_id in {CORE_ID,D1_ID}:
        return True
    if strategy_id==L20_ID:
        return balance>=BOOTSTRAP_THRESHOLD_USD
    return False


def _risk_per_lot_usd(t:TournamentTrade,spec:BrokerLotSpec)->float:
    units=spec.contract_units_per_lot
    risk_price=abs(float(t.entry_price)-float(t.stop_loss))
    return risk_price*units*(1.0+max(0.0,float(t.cost_r)))


def _size_for_risk(t:TournamentTrade,*,balance:float,spec:BrokerLotSpec)->float:
    per_lot=_risk_per_lot_usd(t,spec)
    if per_lot<=0 or balance<=0:
        return 0.0
    budget=balance*(RISK_CAP_PCT/100.0)
    raw=budget/per_lot
    steps=floor((raw+1e-12)/LOT_STEP)
    lot=min(MAX_LOT,steps*LOT_STEP)
    if lot<MIN_LOT:
        return 0.0
    return round(lot,2)


def _replay(
    trades:Sequence[TournamentTrade],*,
    spec:BrokerLotSpec,tiers,
    evaluation_start,evaluation_end,
    sizing:str,
)->dict[str,Any]:
    start,end=ensure_utc(evaluation_start),ensure_utc(evaluation_end)
    rows=_period(trades,start,end)
    balance=STARTING_BALANCE_USD
    peak=balance
    max_dd=0.0
    active={}
    accepted=[]
    opened_by_strategy={}
    skipped={}
    transitions=[]
    last_state="BOOTSTRAP"

    events=[]
    ordered=sorted(rows,key=lambda x:(ensure_utc(x.entry_at),ensure_utc(x.exit_at),x.strategy_id))
    for idx,t in enumerate(ordered):
        events.append((ensure_utc(t.entry_at),1,idx,"ENTRY",t))
        events.append((ensure_utc(t.exit_at),0,idx,"EXIT",t))
    events.sort(key=lambda x:(x[0],x[1],x[2]))

    def skip(reason):
        skipped[reason]=skipped.get(reason,0)+1

    for ts,_,idx,kind,t in events:
        if kind=="EXIT":
            st=active.pop(idx,None)
            if st is None: continue
            balance+=float(st["pnl_usd"])
            peak=max(peak,balance)
            dd=0.0 if peak<=0 else 100.0*max(0.0,peak-balance)/peak
            max_dd=max(max_dd,dd)
            state="MATURE" if balance>=BOOTSTRAP_THRESHOLD_USD else "BOOTSTRAP"
            if state!=last_state:
                transitions.append({"at":ts.isoformat(),"from":last_state,"to":state,"balance":float(balance)})
                last_state=state
            continue

        if not _allowed_family(t.strategy_id,balance):
            skip("CAPITAL_PHASE_OR_FAMILY_BLOCK")
            continue

        if sizing=="FIXED_001":
            lot=MIN_LOT
            planned_loss=_risk_per_lot_usd(t,spec)*lot
            if planned_loss>balance*(RISK_CAP_PCT/100.0)+1e-9:
                skip("PER_TRADE_RISK_CAP")
                continue
        elif sizing=="RISK_BUDGETED":
            lot=_size_for_risk(t,balance=balance,spec=spec)
            if lot<MIN_LOT:
                skip("BELOW_MIN_LOT_AT_RISK_CAP")
                continue
            planned_loss=_risk_per_lot_usd(t,spec)*lot
        else:
            raise ValueError(f"V150_UNKNOWN_SIZING:{sizing}")

        if not _lot_feasible(spec,lot):
            skip("LOT_NOT_FEASIBLE"); continue
        if len(active)>=MAX_ACTIVE_POSITIONS:
            skip("MAX_ACTIVE_POSITIONS"); continue

        aggregate_loss=sum(float(x["planned_loss_usd"]) for x in active.values())+planned_loss
        if aggregate_loss>balance*(AGGREGATE_RISK_CAP_PCT/100.0)+1e-9:
            skip("AGGREGATE_RISK_CAP"); continue

        units=spec.contract_units_per_lot*lot
        notional=abs(float(t.entry_price))*units
        symbol_lev=_symbol_leverage(tiers,notional)
        effective=ACCOUNT_LEVERAGE if symbol_lev is None else min(ACCOUNT_LEVERAGE,symbol_lev)
        margin=notional/effective
        aggregate_margin=sum(float(x["margin_usd"]) for x in active.values())+margin
        if aggregate_margin>balance*(MARGIN_USAGE_CAP_PCT/100.0)+1e-9:
            skip("MARGIN_USAGE_CAP"); continue

        worst_equity=balance-aggregate_loss
        margin_level=float("inf") if aggregate_margin<=0 else 100.0*worst_equity/aggregate_margin
        if margin_level<=STOPOUT_PCT:
            skip("PLANNED_STOPOUT_GUARD"); continue

        risk_price=abs(float(t.entry_price)-float(t.stop_loss))
        pnl=float(t.net_r)*risk_price*units
        active[idx]={
            "lot":lot,"planned_loss_usd":planned_loss,"margin_usd":margin,"pnl_usd":pnl,
        }
        accepted.append(t)
        opened_by_strategy[t.strategy_id]=opened_by_strategy.get(t.strategy_id,0)+1

    return {
        "sizing":sizing,
        "ending_balance_usd":float(balance),
        "return_pct":100.0*(balance/STARTING_BALANCE_USD-1.0),
        "max_realized_drawdown_pct":float(max_dd),
        "opened":len(accepted),
        "metrics":_metrics(accepted),
        "opened_by_strategy":opened_by_strategy,
        "skipped_by_reason":skipped,
        "state_transitions":transitions,
        "ending_state":"MATURE" if balance>=BOOTSTRAP_THRESHOLD_USD else "BOOTSTRAP",
        "hit_1000":any(x["to"]=="MATURE" for x in transitions),
    }


def _candidate_universe(rows:Sequence[Bar],*,costs,pip_size:float,evaluation_end):
    bars=tuple(sorted(rows,key=lambda x:ensure_utc(x.timestamp)))
    _,gated_core,_,v114_diag=build_capital_preservation_portfolio(
        bars,costs=costs,pip_size=pip_size,evaluation_end=evaluation_end
    )
    _,_,selected=assemble_v110_selector(
        bars,costs=costs,pip_size=pip_size,evaluation_end=evaluation_end
    )
    d1=tuple(selected["D1_STAGGERED"])
    l20=tuple(selected["M15_L20"])
    universe=_dedupe_with_classic((*gated_core,*d1,*l20))
    return universe,{
        "v114":v114_diag,
        "gated_core":len(gated_core),
        "selected_d1":len(d1),
        "selected_l20":len(l20),
    }


def evaluate_v150(rows:Sequence[Bar],*,evaluation_end,pip_size:float,costs,broker_spec,leverage_tiers):
    end=ensure_utc(evaluation_end)
    universe,diag=_candidate_universe(rows,costs=costs,pip_size=pip_size,evaluation_end=end)
    sizes=("FIXED_001","RISK_BUDGETED")

    eras={}
    for label,a,b in ERA_WINDOWS:
        bb=min(ensure_utc(b),end)
        if ensure_utc(a)>=bb: continue
        eras[label]={s:_replay(universe,spec=broker_spec,tiers=leverage_tiers,evaluation_start=a,evaluation_end=bb,sizing=s) for s in sizes}

    starts={}
    for year in START_SENSITIVITY:
        a=datetime(year,1,1,tzinfo=timezone.utc)
        if a>=end: continue
        starts[str(year)]={s:_replay(universe,spec=broker_spec,tiers=leverage_tiers,evaluation_start=a,evaluation_end=end,sizing=s) for s in sizes}

    return {
        "research_version":RESEARCH_VERSION,
        "artifact_contract":ARTIFACT_CONTRACT,
        "policy_effect":POLICY_EFFECT,
        "execution_influence":EXECUTION_INFLUENCE,
        "promotion_eligible":PROMOTION_ELIGIBLE,
        "live_execution_enabled":False,
        "contract":{
            "market_permission":"V114 CASH-state + frozen V110 causal selectors",
            "bootstrap":"CORE + D1_STAGGERED while realized balance < $1,000",
            "mature":"CORE + D1_STAGGERED + L20 at realized balance >= $1,000",
            "L12":"excluded by V121 preregistered follow-up hypothesis",
            "starting_balance_usd":STARTING_BALANCE_USD,
            "leverage":ACCOUNT_LEVERAGE,
            "lot_range":[MIN_LOT,MAX_LOT],
            "risk_cap_pct":RISK_CAP_PCT,
            "aggregate_risk_cap_pct":AGGREGATE_RISK_CAP_PCT,
            "margin_usage_cap_pct":MARGIN_USAGE_CAP_PCT,
            "max_positions":MAX_ACTIVE_POSITIONS,
            "fixed_variant":"0.01 lot only if it satisfies the same 20% risk contract",
            "risk_budgeted_variant":"largest 0.01-step lot <=20% planned-loss budget, capped at 0.50",
            "threshold_grid_search":False,
            "calendar_year_used_for_routing":False,
            "execution_authority":False,
        },
        "universe_diagnostics":diag,
        "eras":eras,
        "start_sensitivity":starts,
        "note":"V150 tests account geometry as part of the meta-selector. The 20% risk and 50% margin caps are user-established account constraints, not fitted thresholds.",
    }

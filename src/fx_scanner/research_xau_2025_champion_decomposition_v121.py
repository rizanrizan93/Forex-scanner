from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from .demo_donchian_adaptive_tournament import TournamentTrade, compute_metrics
from .models import ensure_utc
from .research_xau_100usd_stopout_v23 import _cash_path_stopout_safe
from .research_xau_era_robustness_v31 import _dedupe_with_classic
from .research_xau_multihorizon_100usd_v20 import _limit_concurrency, _trading_dates
from .research_xau_v110_robustness_v111 import assemble_v110_selector

RESEARCH_VERSION="XAU_2025_CHAMPION_DECOMPOSITION_V121"
ARTIFACT_CONTRACT="XAU_2025_CHAMPION_DECOMPOSITION_V121_EVIDENCE_1"
POLICY_EFFECT="SHADOW_ONLY"
EXECUTION_INFLUENCE=False
PROMOTION_ELIGIBLE=False

START=datetime(2025,1,1,tzinfo=timezone.utc)


def _period(trades:Sequence[TournamentTrade],a,b)->tuple[TournamentTrade,...]:
    aa=ensure_utc(a);bb=ensure_utc(b)
    return tuple(t for t in trades if aa<=ensure_utc(t.entry_at)<bb)


def _metrics(trades):
    return compute_metrics(tuple(trades)).payload()


def _portfolio(core, *sat_groups):
    return _limit_concurrency(_dedupe_with_classic((*tuple(core),*(t for g in sat_groups for t in g))))


def _trace_cash(
    trades,
    *,
    spec,
    tiers,
    evaluation_start,
    evaluation_end,
    account_leverage:float=100.0,
    stopout_pct:float=50.0,
):
    # Same physical contract as V23/V120, but retain an execution ledger.
    from .research_xau_100usd_leverage_v22 import _lot_feasible, _symbol_leverage
    from .research_xau_multihorizon_100usd_v20 import MIN_LOT, MAX_ACTIVE_POSITIONS, STARTING_BALANCE_USD

    balance=STARTING_BALANCE_USD
    active={}
    ledger=[]
    events=[]
    ordered=sorted(trades,key=lambda x:(ensure_utc(x.entry_at),ensure_utc(x.exit_at)))
    for idx,t in enumerate(ordered):
        events.append((ensure_utc(t.entry_at),1,idx,"ENTRY",t))
        events.append((ensure_utc(t.exit_at),0,idx,"EXIT",t))
    events.sort(key=lambda x:(x[0],x[1],x[2]))

    for ts,_,idx,kind,t in events:
        if kind=="EXIT":
            state=active.pop(idx,None)
            if state is None:
                continue
            before=balance
            balance+=float(state["pnl_usd"])
            ledger.append({
                "event":"EXIT",
                "at":ts.isoformat(),
                "strategy_id":t.strategy_id,
                "direction":str(t.direction),
                "entry_at":ensure_utc(t.entry_at).isoformat(),
                "exit_at":ensure_utc(t.exit_at).isoformat(),
                "net_r":float(t.net_r),
                "pnl_usd":float(state["pnl_usd"]),
                "balance_before":float(before),
                "balance_after":float(balance),
            })
            continue

        lot=MIN_LOT
        if not _lot_feasible(spec,lot):
            continue
        units=spec.contract_units_per_lot*lot
        notional=abs(float(t.entry_price))*units
        symbol_lev=_symbol_leverage(tiers,notional)
        effective=account_leverage if symbol_lev is None else min(account_leverage,symbol_lev)
        margin=notional/effective
        current_margin=sum(float(x["margin_usd"]) for x in active.values())
        if len(active)>=MAX_ACTIVE_POSITIONS or balance-current_margin<margin:
            continue

        risk_price=abs(float(t.entry_price)-float(t.stop_loss))
        cost_multiplier=1.0+max(0.0,float(t.cost_r))
        planned_loss=risk_price*units*cost_multiplier
        candidate_margin=current_margin+margin
        candidate_planned_loss=sum(float(x["planned_loss_usd"]) for x in active.values())+planned_loss
        worst_equity=balance-candidate_planned_loss
        margin_level=float("inf") if candidate_margin<=0 else 100.0*worst_equity/candidate_margin
        if margin_level<=stopout_pct:
            continue

        pnl_usd=float(t.net_r)*risk_price*units
        active[idx]={
            "margin_usd":margin,
            "planned_loss_usd":planned_loss,
            "pnl_usd":pnl_usd,
        }
        ledger.append({
            "event":"ENTRY",
            "at":ts.isoformat(),
            "strategy_id":t.strategy_id,
            "direction":str(t.direction),
            "entry_price":float(t.entry_price),
            "stop_loss":float(t.stop_loss),
            "risk_price":float(risk_price),
            "planned_loss_usd":float(planned_loss),
            "margin_usd":float(margin),
            "planned_margin_level_pct":float(margin_level),
            "balance":float(balance),
        })

    exits=[x for x in ledger if x["event"]=="EXIT"]
    first_1000=next((x for x in exits if x["balance_after"]>=1000.0),None)
    return {
        "ending_balance_usd":float(balance),
        "first_1000_exit":first_1000,
        "ledger_to_first_1000":(
            ledger if first_1000 is None
            else [x for x in ledger if ensure_utc(datetime.fromisoformat(x["at"]))<=ensure_utc(datetime.fromisoformat(first_1000["at"]))]
        ),
    }


def evaluate_v121(
    rows,*,
    evaluation_end,
    pip_size:float,
    costs,
    broker_spec,
    leverage_tiers,
)->dict[str,Any]:
    bars=tuple(sorted(rows,key=lambda x:ensure_utc(x.timestamp)))
    end=ensure_utc(evaluation_end)
    core_all,selector_all,selected=assemble_v110_selector(
        bars,costs=costs,pip_size=pip_size,evaluation_end=end
    )
    core=_period(core_all,START,end)
    d1=_period(selected["D1_STAGGERED"],START,end)
    l12=_period(selected["M15_L12"],START,end)
    l20=_period(selected["M15_L20"],START,end)

    portfolios={
        "CORE_ONLY":tuple(core),
        "CORE_PLUS_D1":_portfolio(core,d1),
        "CORE_PLUS_L20":_portfolio(core,l20),
        "CORE_PLUS_D1_L20":_portfolio(core,d1,l20),
        "FULL_V110":_period(selector_all,START,end),
    }
    dates=_trading_dates(bars,start=START,end=end)

    out={}
    for name,trades in portfolios.items():
        out[name]={
            "metrics":_metrics(trades),
            "cash":_cash_path_stopout_safe(
                trades,spec=broker_spec,tiers=leverage_tiers,
                account_leverage=100.0,stopout_pct=50.0,trading_dates=dates,
            ),
        }

    full_trace=_trace_cash(
        portfolios["FULL_V110"],
        spec=broker_spec,tiers=leverage_tiers,
        evaluation_start=START,evaluation_end=end,
    )
    early_ledger=full_trace["ledger_to_first_1000"]
    exits=[x for x in early_ledger if x["event"]=="EXIT"]
    by_strategy={}
    for x in exits:
        s=x["strategy_id"]
        st=by_strategy.setdefault(s,{"exits":0,"pnl_usd":0.0})
        st["exits"]+=1
        st["pnl_usd"]+=float(x["pnl_usd"])

    return {
        "research_version":RESEARCH_VERSION,
        "artifact_contract":ARTIFACT_CONTRACT,
        "policy_effect":POLICY_EFFECT,
        "execution_influence":EXECUTION_INFLUENCE,
        "promotion_eligible":PROMOTION_ELIGIBLE,
        "live_execution_enabled":False,
        "contract":{
            "start":START.isoformat(),
            "strategy":"frozen V110 under provided stress costs",
            "account":"fresh $100 / 1:100 / fixed 0.01 / no risk-% cap / 50% stop-out survivability",
            "purpose":"attribution only; no strategy parameter changes",
        },
        "portfolios":out,
        "full_v110_bootstrap_trace":{
            "ending_balance_usd":full_trace["ending_balance_usd"],
            "first_1000_exit":full_trace["first_1000_exit"],
            "realized_pnl_to_first_1000_by_strategy":by_strategy,
            "ledger_to_first_1000":early_ledger,
        },
    }

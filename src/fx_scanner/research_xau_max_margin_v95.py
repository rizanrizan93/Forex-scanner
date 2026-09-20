from __future__ import annotations
from typing import Any, Sequence

from .demo_donchian_adaptive_tournament import TournamentTrade
from .models import ensure_utc
from .research_xau_100usd_bootstrap_v89 import _assemble
from .research_xau_100usd_leverage_v22 import _lot_feasible, _symbol_leverage
from .research_xau_margin_leverage_v21 import LeverageTier
from .research_xau_multihorizon_100usd_v20 import BrokerLotSpec, MAX_ACTIVE_POSITIONS
from .research_xau_m15_dual_strategy import M15ResearchCosts
from .research_xau_pullback_bootstrap_v91 import transform_v87_satellite

RESEARCH_VERSION="XAU_MAX_MARGIN_V95"
ARTIFACT_CONTRACT="XAU_MAX_MARGIN_V95_EVIDENCE_1"
POLICY_EFFECT="SHADOW_ONLY"
EXECUTION_INFLUENCE=False
PROMOTION_ELIGIBLE=False
STARTING_BALANCE_USD=100.0
ACCOUNT_LEVERAGE=100.0
MIN_LOT=0.01
LOT_STEP=0.01
MAX_LOT=0.50
TARGET_BALANCE=1000.0


def _largest_margin_lot(
    *,balance:float,current_margin:float,entry_price:float,
    spec:BrokerLotSpec,tiers:Sequence[LeverageTier],
)->tuple[float,float]:
    free=max(0.0,balance-current_margin)
    steps=int(round(MAX_LOT/LOT_STEP))
    for n in range(steps,0,-1):
        lot=round(n*LOT_STEP,2)
        if lot<MIN_LOT or not _lot_feasible(spec,lot):
            continue
        units=spec.contract_units_per_lot*lot
        notional=abs(entry_price)*units
        sym=_symbol_leverage(tiers,notional)
        lev=ACCOUNT_LEVERAGE if sym is None else min(ACCOUNT_LEVERAGE,sym)
        margin=notional/lev
        if margin<=free:
            return lot,margin
    return 0.0,0.0


def max_margin_cash_path(
    trades:Sequence[TournamentTrade],*,spec:BrokerLotSpec,tiers:Sequence[LeverageTier],
)->dict[str,Any]:
    balance=STARTING_BALANCE_USD
    peak=balance
    min_balance=balance
    max_dd_pct=0.0
    active:dict[int,dict[str,float]]={}
    opened=0
    margin_skips=0
    max_lot=0.0
    hit1000_at=None
    ruin=False
    lot_hist:dict[str,int]={}

    events=[]
    for idx,t in enumerate(sorted(trades,key=lambda x:(ensure_utc(x.entry_at),ensure_utc(x.exit_at)))):
        events.append((ensure_utc(t.entry_at),1,idx,"ENTRY",t))
        events.append((ensure_utc(t.exit_at),0,idx,"EXIT",t))
    events.sort(key=lambda x:(x[0],x[1],x[2]))

    for ts,_,idx,kind,t in events:
        if kind=="EXIT":
            state=active.pop(idx,None)
            if state is None:
                continue
            balance+=float(state["pnl_usd"])
            min_balance=min(min_balance,balance)
            peak=max(peak,balance)
            if peak>0:
                max_dd_pct=max(max_dd_pct,100.0*(peak-balance)/peak)
            if hit1000_at is None and balance>=TARGET_BALANCE:
                hit1000_at=ts.isoformat()
            if balance<=0:
                ruin=True
            continue

        if ruin or len(active)>=MAX_ACTIVE_POSITIONS:
            continue
        current_margin=sum(float(x["margin_usd"]) for x in active.values())
        lot,margin=_largest_margin_lot(
            balance=balance,current_margin=current_margin,
            entry_price=float(t.entry_price),spec=spec,tiers=tiers,
        )
        if lot<MIN_LOT:
            margin_skips+=1
            continue
        units=spec.contract_units_per_lot*lot
        risk_price=abs(float(t.entry_price)-float(t.stop_loss))
        pnl=float(t.net_r)*risk_price*units
        active[idx]={"margin_usd":margin,"pnl_usd":pnl}
        opened+=1
        max_lot=max(max_lot,lot)
        lot_hist[f"{lot:.2f}"]=lot_hist.get(f"{lot:.2f}",0)+1

    return {
        "starting_balance_usd":STARTING_BALANCE_USD,
        "ending_balance_usd":float(balance),
        "return_pct":float((balance/STARTING_BALANCE_USD-1.0)*100.0),
        "minimum_realized_balance_usd":float(min_balance),
        "max_realized_drawdown_pct":float(max_dd_pct),
        "opened_trades":opened,
        "margin_skips":margin_skips,
        "max_lot_used":max_lot,
        "lot_histogram":lot_hist,
        "hit_1000":hit1000_at is not None,
        "hit_1000_at":hit1000_at,
        "ruin":ruin,
    }


def evaluate_v95(
    bars,*,evaluation_start,evaluation_end,pip_size:float,costs:M15ResearchCosts,
    broker_spec:BrokerLotSpec,leverage_tiers:Sequence[LeverageTier],
)->dict[str,Any]:
    rows=tuple(sorted(bars,key=lambda x:ensure_utc(x.timestamp)))
    start=ensure_utc(evaluation_start);end=ensure_utc(evaluation_end)
    _,satellite,_,change_points,gates=_assemble(rows,costs=costs,pip_size=pip_size,end=end)
    baseline=tuple(t for t in satellite if start<=ensure_utc(t.entry_at)<end)
    displacement=transform_v87_satellite(
        rows,baseline,variant_id="DISPLACEMENT_50_RETEST_4",costs=costs
    )
    streams={"V87_NEXT_OPEN":baseline,"V91_DISPLACEMENT_50_RETEST_4":displacement}
    return {
        "research_version":RESEARCH_VERSION,
        "artifact_contract":ARTIFACT_CONTRACT,
        "policy_effect":POLICY_EFFECT,
        "execution_influence":EXECUTION_INFLUENCE,
        "promotion_eligible":PROMOTION_ELIGIBLE,
        "live_execution_enabled":False,
        "contract":{
            "starting_balance_usd":STARTING_BALANCE_USD,
            "account_leverage":ACCOUNT_LEVERAGE,
            "sizing":"MAXIMUM_LOT_ALLOWED_BY_CURRENT_FREE_MARGIN",
            "minimum_lot":MIN_LOT,
            "lot_step":LOT_STEP,
            "maximum_lot":MAX_LOT,
            "risk_pct_filter":None,
            "planned_stop_guard":False,
            "broker_stopout_model":False,
            "warning":"EXTREME_THEORETICAL_DIAGNOSTIC_NOT_EXECUTION_POLICY",
        },
        "change_points":list(change_points),
        "gates":gates,
        "variants":{
            k:max_margin_cash_path(v,spec=broker_spec,tiers=leverage_tiers)
            for k,v in streams.items()
        },
    }

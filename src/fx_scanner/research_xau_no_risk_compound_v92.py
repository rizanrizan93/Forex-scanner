from __future__ import annotations

from typing import Any, Mapping, Sequence

from .demo_donchian_adaptive_tournament import TournamentTrade, compute_metrics
from .models import ensure_utc
from .research_xau_100usd_bootstrap_v89 import _assemble
from .research_xau_100usd_leverage_v22 import _lot_feasible, _lot_for_balance, _symbol_leverage
from .research_xau_100usd_regime_cashpath_v88 import (
    ACCOUNT_LEVERAGE,
    PLANNED_STOP_MARGIN_FLOOR_PCT,
)
from .research_xau_margin_leverage_v21 import LeverageTier
from .research_xau_multihorizon_100usd_v20 import (
    BrokerLotSpec,
    MAX_ACTIVE_POSITIONS,
    STARTING_BALANCE_USD,
)
from .research_xau_m15_dual_strategy import M15ResearchCosts
from .research_xau_pullback_bootstrap_v91 import (
    transform_v87_satellite,
)

RESEARCH_VERSION="XAU_NO_RISK_COMPOUND_V92"
ARTIFACT_CONTRACT="XAU_NO_RISK_COMPOUND_V92_EVIDENCE_1"
POLICY_EFFECT="SHADOW_ONLY"
EXECUTION_INFLUENCE=False
PROMOTION_ELIGIBLE=False
DIAGNOSTIC_ONLY=True
LOT_MODE="BALANCE_STEP_100"
TARGET_BALANCE=1000.0
VARIANTS=("V87_NEXT_OPEN","V91_DISPLACEMENT_50_RETEST_4")


def aggressive_cash_path(
    trades: Sequence[TournamentTrade],
    *,
    spec: BrokerLotSpec,
    tiers: Sequence[LeverageTier],
    checkpoint_times: Mapping[str, Any],
) -> dict[str, Any]:
    balance=STARTING_BALANCE_USD
    peak=balance
    minimum_balance=balance
    max_dd_pct=0.0
    active:dict[int,dict[str,Any]]={}
    opened=0
    margin_skips=0
    guard_skips=0
    max_active=0
    max_lot_used=0.0
    hit_target_at=None
    checkpoints:dict[str,Any]={}
    lot_hist:dict[str,int]={}

    ordered=sorted(trades,key=lambda x:(ensure_utc(x.entry_at),ensure_utc(x.exit_at)))
    events=[]
    for idx,trade in enumerate(ordered):
        events.append((ensure_utc(trade.entry_at),1,idx,"ENTRY",trade))
        events.append((ensure_utc(trade.exit_at),0,idx,"EXIT",trade))
    events.sort(key=lambda x:(x[0],x[1],x[2]))

    cps=sorted((ensure_utc(v),k) for k,v in checkpoint_times.items())
    cp_i=0

    def record(label:str,at)->None:
        checkpoints[label]={
            "at":ensure_utc(at).isoformat(),
            "realized_balance_usd":float(balance),
            "active_positions":len(active),
        }

    for ts,_,idx,kind,trade in events:
        while cp_i<len(cps) and cps[cp_i][0]<=ts:
            record(cps[cp_i][1],cps[cp_i][0]); cp_i+=1

        if kind=="EXIT":
            state=active.pop(idx,None)
            if state is None:
                continue
            balance+=float(state["pnl_usd"])
            minimum_balance=min(minimum_balance,balance)
            peak=max(peak,balance)
            if peak>0:
                max_dd_pct=max(max_dd_pct,100.0*(peak-balance)/peak)
            if hit_target_at is None and balance>=TARGET_BALANCE:
                hit_target_at=ts.isoformat()
            continue

        if balance<=0:
            continue

        lot=_lot_for_balance(balance,LOT_MODE)
        if not _lot_feasible(spec,lot):
            margin_skips+=1
            continue
        if len(active)>=MAX_ACTIVE_POSITIONS:
            margin_skips+=1
            continue

        units=spec.contract_units_per_lot*lot
        notional=abs(float(trade.entry_price))*units
        symbol_lev=_symbol_leverage(tiers,notional)
        effective=ACCOUNT_LEVERAGE if symbol_lev is None else min(ACCOUNT_LEVERAGE,symbol_lev)
        margin=notional/effective
        current_margin=sum(float(x["margin_usd"]) for x in active.values())
        if balance-current_margin<margin:
            margin_skips+=1
            continue

        risk_price=abs(float(trade.entry_price)-float(trade.stop_loss))
        planned_loss=risk_price*units*(1.0+max(0.0,float(trade.cost_r)))
        candidate_margin=current_margin+margin
        candidate_loss=sum(float(x["planned_loss_usd"]) for x in active.values())+planned_loss
        worst_equity=balance-candidate_loss
        margin_level=float("inf") if candidate_margin<=0 else 100.0*worst_equity/candidate_margin
        if margin_level<=PLANNED_STOP_MARGIN_FLOOR_PCT:
            guard_skips+=1
            continue

        pnl_usd=float(trade.net_r)*risk_price*units
        active[idx]={
            "margin_usd":margin,
            "planned_loss_usd":planned_loss,
            "pnl_usd":pnl_usd,
            "lot":lot,
        }
        opened+=1
        max_active=max(max_active,len(active))
        max_lot_used=max(max_lot_used,lot)
        lot_hist[f"{lot:.2f}"]=lot_hist.get(f"{lot:.2f}",0)+1

    while cp_i<len(cps):
        record(cps[cp_i][1],cps[cp_i][0]); cp_i+=1

    return {
        "starting_balance_usd":STARTING_BALANCE_USD,
        "ending_balance_usd":float(balance),
        "return_pct":float((balance/STARTING_BALANCE_USD-1.0)*100.0),
        "minimum_realized_balance_usd":float(minimum_balance),
        "max_realized_drawdown_pct":float(max_dd_pct),
        "opened_trades":opened,
        "margin_skips":margin_skips,
        "planned_stop_guard_skips":guard_skips,
        "max_active_positions":max_active,
        "max_lot_used":max_lot_used,
        "lot_histogram":lot_hist,
        "hit_1000":hit_target_at is not None,
        "hit_1000_at":hit_target_at,
        "ruin":balance<=0,
        "checkpoints":checkpoints,
    }


def evaluate_v92(
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
    start=ensure_utc(evaluation_start); end=ensure_utc(evaluation_end)
    _,satellite,_,change_points,gates=_assemble(rows,costs=costs,pip_size=pip_size,end=end)
    baseline=tuple(t for t in satellite if start<=ensure_utc(t.entry_at)<end)
    displacement=transform_v87_satellite(
        rows,baseline,variant_id="DISPLACEMENT_50_RETEST_4",costs=costs
    )
    checkpoints={
        "START_2012":start,
        "START_2019":ensure_utc(era_windows["2019_2024"][0]),
        "START_2025":ensure_utc(era_windows["2025_2026YTD"][0]),
        "END_2026YTD":end,
    }
    streams={
        "V87_NEXT_OPEN":baseline,
        "V91_DISPLACEMENT_50_RETEST_4":displacement,
    }
    results={}
    for vid,trades in streams.items():
        results[vid]={
            "signal_metrics":compute_metrics(trades).payload(),
            "cash":aggressive_cash_path(
                trades,spec=broker_spec,tiers=leverage_tiers,
                checkpoint_times=checkpoints,
            ),
        }
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
            "lot_mode":LOT_MODE,
            "lot_rule":"0.01 per full $100 realized balance, capped by existing broker max lot",
            "risk_pct_filter":None,
            "planned_stop_margin_floor_pct":PLANNED_STOP_MARGIN_FLOOR_PCT,
            "target_balance_usd":TARGET_BALANCE,
            "calendar_era_routing":False,
            "diagnostic_only":True,
        },
        "change_points":list(change_points),
        "gates":gates,
        "variants":results,
    }

from __future__ import annotations
from typing import Any, Mapping, Sequence

from .demo_donchian_adaptive_tournament import compute_metrics, TournamentTrade
from .models import ensure_utc
from .research_xau_100usd_bootstrap_v89 import _assemble
from .research_xau_100usd_leverage_v22 import _lot_feasible, _symbol_leverage
from .research_xau_capital_ladder_v90 import STARTING_BALANCES, risk_capped_dynamic_cash_path
from .research_xau_fvg_ote_bootstrap_v93 import transform_v87_ict_entries
from .research_xau_margin_leverage_v21 import LeverageTier
from .research_xau_multihorizon_100usd_v20 import BrokerLotSpec, MAX_ACTIVE_POSITIONS
from .research_xau_m15_dual_strategy import M15ResearchCosts

RESEARCH_VERSION="XAU_FVG_CE_CAPITAL_V96"
ARTIFACT_CONTRACT="XAU_FVG_CE_CAPITAL_V96_EVIDENCE_1"
POLICY_EFFECT="SHADOW_ONLY"
EXECUTION_INFLUENCE=False
PROMOTION_ELIGIBLE=False
STARTING_BALANCE_USD=100.0
ACCOUNT_LEVERAGE=100.0
MIN_LOT=0.01
LOT_STEP=0.01
MAX_LOT=0.50
TARGET_BALANCE=1000.0
ENTRY_VARIANT="FVG_CE_4"


def _largest_margin_lot(balance:float,current_margin:float,entry_price:float,spec:BrokerLotSpec,tiers:Sequence[LeverageTier])->tuple[float,float]:
    free=max(0.0,balance-current_margin)
    for n in range(int(round(MAX_LOT/LOT_STEP)),0,-1):
        lot=round(n*LOT_STEP,2)
        if not _lot_feasible(spec,lot):
            continue
        units=spec.contract_units_per_lot*lot
        notional=abs(entry_price)*units
        sym=_symbol_leverage(tiers,notional)
        lev=ACCOUNT_LEVERAGE if sym is None else min(ACCOUNT_LEVERAGE,sym)
        margin=notional/lev
        if margin<=free:
            return lot,margin
    return 0.0,0.0


def max_margin_cash_path(trades:Sequence[TournamentTrade],*,spec:BrokerLotSpec,tiers:Sequence[LeverageTier])->dict[str,Any]:
    balance=STARTING_BALANCE_USD; peak=balance; min_balance=balance; max_dd_pct=0.0
    active:dict[int,dict[str,float]]={}
    opened=0; margin_skips=0; max_lot=0.0; hit1000_at=None; ruin=False
    events=[]
    for idx,t in enumerate(sorted(trades,key=lambda x:(ensure_utc(x.entry_at),ensure_utc(x.exit_at)))):
        events.append((ensure_utc(t.entry_at),1,idx,"ENTRY",t))
        events.append((ensure_utc(t.exit_at),0,idx,"EXIT",t))
    events.sort(key=lambda x:(x[0],x[1],x[2]))
    for ts,_,idx,kind,t in events:
        if kind=="EXIT":
            state=active.pop(idx,None)
            if state is None: continue
            balance+=float(state["pnl_usd"])
            min_balance=min(min_balance,balance); peak=max(peak,balance)
            if peak>0: max_dd_pct=max(max_dd_pct,100.0*(peak-balance)/peak)
            if hit1000_at is None and balance>=TARGET_BALANCE: hit1000_at=ts.isoformat()
            if balance<=0: ruin=True
            continue
        if ruin or len(active)>=MAX_ACTIVE_POSITIONS: continue
        current_margin=sum(float(x["margin_usd"]) for x in active.values())
        lot,margin=_largest_margin_lot(balance,current_margin,float(t.entry_price),spec,tiers)
        if lot<MIN_LOT:
            margin_skips+=1; continue
        units=spec.contract_units_per_lot*lot
        risk_price=abs(float(t.entry_price)-float(t.stop_loss))
        active[idx]={"margin_usd":margin,"pnl_usd":float(t.net_r)*risk_price*units}
        opened+=1; max_lot=max(max_lot,lot)
    return {
        "starting_balance_usd":STARTING_BALANCE_USD,
        "ending_balance_usd":float(balance),
        "return_pct":float((balance/STARTING_BALANCE_USD-1.0)*100.0),
        "minimum_realized_balance_usd":float(min_balance),
        "max_realized_drawdown_pct":float(max_dd_pct),
        "opened_trades":opened,"margin_skips":margin_skips,"max_lot_used":max_lot,
        "hit_1000":hit1000_at is not None,"hit_1000_at":hit1000_at,"ruin":ruin,
    }


def evaluate_v96(
    bars,*,evaluation_start,evaluation_end,pip_size:float,costs:M15ResearchCosts,
    broker_spec:BrokerLotSpec,leverage_tiers:Sequence[LeverageTier],
    era_windows:Mapping[str,tuple[Any,Any]],
)->dict[str,Any]:
    rows=tuple(sorted(bars,key=lambda x:ensure_utc(x.timestamp)))
    start=ensure_utc(evaluation_start);end=ensure_utc(evaluation_end)
    _,satellite,_,change_points,gates=_assemble(rows,costs=costs,pip_size=pip_size,end=end)
    baseline=tuple(t for t in satellite if start<=ensure_utc(t.entry_at)<end)
    fvg=transform_v87_ict_entries(rows,baseline,variant_id=ENTRY_VARIANT,costs=costs)
    checkpoints={
        "START_2012":start,
        "START_2019":ensure_utc(era_windows["2019_2024"][0]),
        "START_2025":ensure_utc(era_windows["2025_2026YTD"][0]),
        "END_2026YTD":end,
    }
    ladder={
        f"{int(b)}":risk_capped_dynamic_cash_path(
            fvg,starting_balance=b,spec=broker_spec,tiers=leverage_tiers,
            checkpoint_times=checkpoints,
        )
        for b in STARTING_BALANCES
    }
    return {
        "research_version":RESEARCH_VERSION,"artifact_contract":ARTIFACT_CONTRACT,
        "policy_effect":POLICY_EFFECT,"execution_influence":EXECUTION_INFLUENCE,
        "promotion_eligible":PROMOTION_ELIGIBLE,"live_execution_enabled":False,
        "exploratory_followup_after_v93":True,
        "contract":{
            "entry_variant":ENTRY_VARIANT,
            "risk5_ladder_starting_balances":list(STARTING_BALANCES),
            "max_margin_starting_balance_usd":STARTING_BALANCE_USD,
            "max_margin_risk_pct_filter":None,
            "max_margin_stop_guard":False,
            "account_leverage":ACCOUNT_LEVERAGE,
            "target_balance_usd":TARGET_BALANCE,
        },
        "signal_metrics":compute_metrics(fvg).payload(),
        "max_margin_100":max_margin_cash_path(fvg,spec=broker_spec,tiers=leverage_tiers),
        "risk5_capital_ladder":ladder,
        "change_points":list(change_points),"gates":gates,
    }

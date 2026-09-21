from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Sequence

from .demo_donchian_adaptive_tournament import TournamentTrade, compute_metrics
from .models import Bar, ensure_utc
from .research_xau_100usd_leverage_v22 import _lot_feasible, _symbol_leverage
from .research_xau_capital_preservation_v114 import build_capital_preservation_portfolio
from .research_xau_era_robustness_v31 import _dedupe_with_classic
from .research_xau_multihorizon_100usd_v20 import MAX_ACTIVE_POSITIONS
from .research_xau_v110_robustness_v111 import assemble_v110_selector
from .research_xau_v142_retest_entry_v143 import _h3_retest

RESEARCH_VERSION="XAU_GEOMETRY_ADAPTIVE_BOOTSTRAP_V151"
ARTIFACT_CONTRACT="XAU_GEOMETRY_ADAPTIVE_BOOTSTRAP_V151_EVIDENCE_1"
POLICY_EFFECT="SHADOW_ONLY"
EXECUTION_INFLUENCE=False
PROMOTION_ELIGIBLE=False

STARTING_BALANCE_USD=100.0
ACCOUNT_LEVERAGE=100.0
LOT=0.01
RISK_CAP_PCT=20.0
AGGREGATE_RISK_CAP_PCT=20.0
MARGIN_USAGE_CAP_PCT=50.0
STOPOUT_PCT=50.0

M15_MODE="BREAKOUT_LEVEL_RETEST_2BAR"
CORE_ID="V31_D1_TSMOM_CLASSIC"
D1_ID="V20_D1_TSMOM_C1_R200"
M15_IDS={"V20_M15_L12_ADX12_D1_R150","V20_M15_L20_ADX15_D1_R200"}

ERA_WINDOWS=(
    ("2012_2018",datetime(2012,1,1,tzinfo=timezone.utc),datetime(2019,1,1,tzinfo=timezone.utc)),
    ("2019_2024",datetime(2019,1,1,tzinfo=timezone.utc),datetime(2025,1,1,tzinfo=timezone.utc)),
    ("2025_2026YTD",datetime(2025,1,1,tzinfo=timezone.utc),datetime(2026,9,20,tzinfo=timezone.utc)),
)
START_SENSITIVITY=(2012,2015,2019,2022,2025)
VARIANTS=("V143_BOOTSTRAP_ONLY","D1_GEOMETRY_ONLY","BOOTSTRAP_PLUS_D1_GEOMETRY")


def _period(trades:Sequence[TournamentTrade],a,b)->tuple[TournamentTrade,...]:
    aa,bb=ensure_utc(a),ensure_utc(b)
    return tuple(t for t in trades if aa<=ensure_utc(t.entry_at)<bb)


def _metrics(trades): return compute_metrics(tuple(trades)).payload()


def _planned_loss(t:TournamentTrade,spec)->float:
    # Match the canonical V128/V129 runtime guard exactly. Transaction costs
    # are already present in trade.net_r and must not be charged a second time
    # to the pre-entry stop-loss budget.
    risk_price=abs(float(t.entry_price)-float(t.stop_loss))
    units=float(spec.contract_units_per_lot)*LOT
    return risk_price*units


def _margin(t:TournamentTrade,spec,tiers)->float:
    units=float(spec.contract_units_per_lot)*LOT
    notional=abs(float(t.entry_price))*units
    symbol_lev=_symbol_leverage(tiers,notional)
    effective=ACCOUNT_LEVERAGE if symbol_lev is None else min(ACCOUNT_LEVERAGE,symbol_lev)
    return notional/effective


def _family(t:TournamentTrade)->str:
    sid=str(t.strategy_id)
    if sid in M15_IDS:return "M15_BOOTSTRAP"
    if sid in {CORE_ID,D1_ID}:return "D1"
    return "OTHER"


def _variant_allows(t:TournamentTrade,variant:str)->bool:
    fam=_family(t)
    if variant=="V143_BOOTSTRAP_ONLY":return fam=="M15_BOOTSTRAP"
    if variant=="D1_GEOMETRY_ONLY":return fam=="D1"
    if variant=="BOOTSTRAP_PLUS_D1_GEOMETRY":return fam in {"M15_BOOTSTRAP","D1"}
    raise ValueError(f"V151_UNKNOWN_VARIANT:{variant}")


def _replay(
    trades:Sequence[TournamentTrade],*,
    variant:str,spec,tiers,evaluation_start,evaluation_end,
)->dict[str,Any]:
    start,end=ensure_utc(evaluation_start),ensure_utc(evaluation_end)
    rows=tuple(t for t in trades if start<=ensure_utc(t.entry_at)<end)
    balance=STARTING_BALANCE_USD
    peak=balance
    min_balance=balance
    max_dd=0.0
    active={}
    accepted=[]
    opened_by_family={"M15_BOOTSTRAP":0,"D1":0}
    skips={}
    first_d1=None
    first_1000=None

    # Exits happen before entries at the same timestamp. Entry candidates sharing
    # a timestamp are then ordered by fixed-0.01 planned loss, smallest first.
    # This is a geometry rule known before outcome and prevents an infeasible
    # wide-stop D1 order from blocking a feasible bootstrap M15 order.
    grouped={}
    for idx,t in enumerate(sorted(rows,key=lambda x:(ensure_utc(x.entry_at),ensure_utc(x.exit_at),x.strategy_id))):
        grouped.setdefault(ensure_utc(t.entry_at),[]).append((idx,t))

    exit_events={}
    for idx,t in enumerate(sorted(rows,key=lambda x:(ensure_utc(x.entry_at),ensure_utc(x.exit_at),x.strategy_id))):
        exit_events.setdefault(ensure_utc(t.exit_at),[]).append((idx,t))

    times=sorted(set(grouped)|set(exit_events))

    def skip(reason):
        skips[reason]=skips.get(reason,0)+1

    for ts in times:
        for idx,t in sorted(exit_events.get(ts,[]),key=lambda z:z[0]):
            st=active.pop(idx,None)
            if st is None:continue
            balance+=float(st["pnl_usd"])
            peak=max(peak,balance);min_balance=min(min_balance,balance)
            if peak>0:max_dd=max(max_dd,100.0*(peak-balance)/peak)
            if first_1000 is None and balance>=1000.0:
                first_1000=ts.isoformat()

        entries=sorted(
            grouped.get(ts,[]),
            key=lambda z:(_planned_loss(z[1],spec),0 if _family(z[1])=="M15_BOOTSTRAP" else 1,z[0]),
        )
        for idx,t in entries:
            if not _variant_allows(t,variant):
                continue
            if balance<=0:
                skip("BALANCE_NONPOSITIVE");continue
            if not _lot_feasible(spec,LOT):
                skip("LOT_NOT_FEASIBLE");continue
            if len(active)>=MAX_ACTIVE_POSITIONS:
                skip("MAX_ACTIVE_POSITIONS");continue

            loss=_planned_loss(t,spec)
            if loss>balance*(RISK_CAP_PCT/100.0)+1e-9:
                skip("PER_TRADE_RISK_CAP");continue
            current_risk=sum(float(x["planned_loss_usd"]) for x in active.values())
            if current_risk+loss>balance*(AGGREGATE_RISK_CAP_PCT/100.0)+1e-9:
                skip("AGGREGATE_RISK_CAP");continue

            margin=_margin(t,spec,tiers)
            current_margin=sum(float(x["margin_usd"]) for x in active.values())
            # Same semantics as V129: each new order may consume at most 50% of
            # current margin-free equity.
            margin_free=max(0.0,balance-current_margin)
            if margin>margin_free*(MARGIN_USAGE_CAP_PCT/100.0)+1e-9:
                skip("MARGIN_USAGE_CAP");continue

            candidate_margin=current_margin+margin
            worst_equity=balance-(current_risk+loss)
            margin_level=float("inf") if candidate_margin<=0 else 100.0*worst_equity/candidate_margin
            if margin_level<=STOPOUT_PCT:
                skip("PLANNED_STOPOUT_GUARD");continue

            risk_price=abs(float(t.entry_price)-float(t.stop_loss))
            units=float(spec.contract_units_per_lot)*LOT
            pnl=float(t.net_r)*risk_price*units
            active[idx]={"planned_loss_usd":loss,"margin_usd":margin,"pnl_usd":pnl}
            accepted.append(t)
            fam=_family(t)
            if fam in opened_by_family:opened_by_family[fam]+=1
            if fam=="D1" and first_d1 is None:
                first_d1={
                    "entry_at":ensure_utc(t.entry_at).isoformat(),
                    "strategy_id":str(t.strategy_id),
                    "balance_at_entry":float(balance),
                    "planned_loss_usd":float(loss),
                    "planned_loss_pct":100.0*loss/balance if balance>0 else None,
                }

    return {
        "variant":variant,
        "ending_balance_usd":float(balance),
        "return_pct":100.0*(balance/STARTING_BALANCE_USD-1.0),
        "minimum_balance_usd":float(min_balance),
        "max_realized_drawdown_pct":float(max_dd),
        "opened":len(accepted),
        "metrics":_metrics(accepted),
        "opened_by_family":opened_by_family,
        "skipped_by_reason":skips,
        "first_d1_accept":first_d1,
        "first_1000_at":first_1000,
    }


def _streams(rows:Sequence[Bar],*,costs,pip_size:float,evaluation_end):
    bars=tuple(sorted(rows,key=lambda x:ensure_utc(x.timestamp)))
    end=ensure_utc(evaluation_end)

    m15,fill=_h3_retest(
        bars,mode=M15_MODE,evaluation_end=end,pip_size=pip_size,costs=costs
    )

    _,gated_core,_,v114_diag=build_capital_preservation_portfolio(
        bars,costs=costs,pip_size=pip_size,evaluation_end=end
    )
    _,_,selected=assemble_v110_selector(
        bars,costs=costs,pip_size=pip_size,evaluation_end=end
    )
    d1_staggered=tuple(selected["D1_STAGGERED"])
    d1=_dedupe_with_classic((*gated_core,*d1_staggered))

    # Do not dedupe D1 against M15 before feasibility evaluation. A simultaneous
    # wide-stop D1 candidate must not erase a feasible M15 bootstrap candidate.
    universe=tuple(sorted((*m15,*d1),key=lambda t:(ensure_utc(t.entry_at),str(t.strategy_id))))
    return universe,{
        "m15_available":len(m15),
        "m15_fill_stats":fill,
        "d1_gated_core_available":len(gated_core),
        "d1_staggered_available":len(d1_staggered),
        "d1_after_internal_dedupe":len(d1),
        "v114_diagnostics":v114_diag,
    }


def evaluate_v151(rows:Sequence[Bar],*,evaluation_end,pip_size:float,costs,broker_spec,leverage_tiers):
    end=ensure_utc(evaluation_end)
    universe,diag=_streams(rows,costs=costs,pip_size=pip_size,evaluation_end=end)
    eras={}
    for label,a,b in ERA_WINDOWS:
        bb=min(ensure_utc(b),end)
        if ensure_utc(a)>=bb:continue
        eras[label]={
            v:_replay(universe,variant=v,spec=broker_spec,tiers=leverage_tiers,evaluation_start=a,evaluation_end=bb)
            for v in VARIANTS
        }
    starts={}
    for y in START_SENSITIVITY:
        a=datetime(y,1,1,tzinfo=timezone.utc)
        if a>=end:continue
        starts[str(y)]={
            v:_replay(universe,variant=v,spec=broker_spec,tiers=leverage_tiers,evaluation_start=a,evaluation_end=end)
            for v in VARIANTS
        }
    return {
        "research_version":RESEARCH_VERSION,
        "artifact_contract":ARTIFACT_CONTRACT,
        "policy_effect":POLICY_EFFECT,
        "execution_influence":EXECUTION_INFLUENCE,
        "promotion_eligible":PROMOTION_ELIGIBLE,
        "live_execution_enabled":False,
        "contract":{
            "bootstrap_signal":"V143 BREAKOUT_LEVEL_RETEST_2BAR; V132 C2 + V134 H1 STRICT; original structural stop",
            "d1_market_permission":"V114 CASH-state gated core + V110 causally selected D1_STAGGERED",
            "d1_unlock":"no balance threshold; each D1 trade must independently pass actual 0.01-lot geometry at current balance",
            "simultaneous_entry_priority":"smaller planned-loss USD first; M15 wins exact tie",
            "starting_balance_usd":STARTING_BALANCE_USD,
            "lot":LOT,
            "leverage":ACCOUNT_LEVERAGE,
            "risk_cap_pct":RISK_CAP_PCT,
            "aggregate_risk_cap_pct":AGGREGATE_RISK_CAP_PCT,
            "margin_free_usage_cap_pct":MARGIN_USAGE_CAP_PCT,
            "max_positions":MAX_ACTIVE_POSITIONS,
            "stopout_guard_pct":STOPOUT_PCT,
            "threshold_grid_search":False,
            "calendar_year_used_for_routing":False,
            "execution_authority":False,
        },
        "stream_diagnostics":diag,
        "eras":eras,
        "start_sensitivity":starts,
        "note":"V151 tests whether a robust/capital-compatible M15 retest stream can bootstrap fresh $100 equity until D1 becomes naturally feasible under the unchanged 20% risk contract.",
    }

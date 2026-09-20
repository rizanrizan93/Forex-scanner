from __future__ import annotations

from bisect import bisect_left
from datetime import datetime
from typing import Any, Mapping, Sequence

from .demo_donchian_adaptive_tournament import TournamentTrade, compute_metrics
from .models import Bar, ensure_utc
from .research_xau_100usd_stopout_v23 import _cash_path_stopout_safe
from .research_xau_capital_preservation_v114 import build_capital_preservation_portfolio
from .research_xau_changepoint_reset_router_v87 import (
    MIN_COMPLETED_TRADES,
    MIN_TRAILING_EXPECTANCY_R,
    MIN_TRAILING_PF,
)
from .research_xau_multihorizon_100usd_v20 import _limit_concurrency, _trading_dates
from .research_xau_public_master_benchmark_v116 import _aggregate, simulate_turtle_s2

RESEARCH_VERSION="XAU_ADAPTIVE_FAMILY_SELECTOR_V118"
ARTIFACT_CONTRACT="XAU_ADAPTIVE_FAMILY_SELECTOR_V118_EVIDENCE_1"
POLICY_EFFECT="SHADOW_ONLY"
EXECUTION_INFLUENCE=False
PROMOTION_ELIGIBLE=False

FAMILY_WINDOW_TRADES=MIN_COMPLETED_TRADES
FAMILIES=("TURTLE_S2","V114")
START_YEARS=(2012,2015,2019,2022,2025)


def _period(trades:Sequence[TournamentTrade],a,b)->tuple[TournamentTrade,...]:
    aa=ensure_utc(a);bb=ensure_utc(b)
    return tuple(t for t in trades if aa<=ensure_utc(t.entry_at)<bb)


def _metrics(trades):
    return compute_metrics(tuple(trades)).payload()


def _family_health_at(trades:Sequence[TournamentTrade], as_of)->dict[str,Any]:
    now=ensure_utc(as_of)
    completed=tuple(
        sorted(
            (t for t in trades if ensure_utc(t.exit_at)<now),
            key=lambda x:ensure_utc(x.exit_at),
        )
    )
    if len(completed)<FAMILY_WINDOW_TRADES:
        return {
            "active":False,
            "status":"INSUFFICIENT_SHADOW_HISTORY",
            "n":len(completed),
            "profit_factor":None,
            "expectancy_r":None,
            "net_r":None,
        }
    window=completed[-FAMILY_WINDOW_TRADES:]
    m=compute_metrics(window).payload()
    pf=m["profit_factor"]
    exp=m["expectancy_r"]
    active=bool(
        pf is not None
        and exp is not None
        and float(pf)>=MIN_TRAILING_PF
        and float(exp)>=MIN_TRAILING_EXPECTANCY_R
    )
    return {
        "active":active,
        "status":"ACTIVE" if active else "OFF_HEALTH",
        "n":len(window),
        "profit_factor":pf,
        "expectancy_r":exp,
        "net_r":float(m["gross_profit_r"])-float(m["gross_loss_r"]),
    }


def _choose_family(health:Mapping[str,Mapping[str,Any]])->str|None:
    active=[name for name in FAMILIES if bool(health[name]["active"])]
    if not active:
        return None
    # Transparent lexicographic choice, no weighted score:
    # highest causal expectancy, then PF, then fixed family name.
    active.sort(
        key=lambda name:(
            float(health[name]["expectancy_r"]),
            float(health[name]["profit_factor"]),
            name,
        ),
        reverse=True,
    )
    return active[0]


def build_adaptive_selector(
    *,
    turtle:Sequence[TournamentTrade],
    v114:Sequence[TournamentTrade],
)->tuple[tuple[TournamentTrade,...],dict[str,Any]]:
    streams={
        "TURTLE_S2":tuple(sorted(turtle,key=lambda x:ensure_utc(x.signal_at))),
        "V114":tuple(sorted(v114,key=lambda x:ensure_utc(x.signal_at))),
    }
    events=[]
    for family,trades in streams.items():
        for t in trades:
            events.append((ensure_utc(t.signal_at),family,t))
    events.sort(key=lambda x:(x[0],x[1],ensure_utc(x[2].entry_at)))

    selected=[]
    counts={"TURTLE_S2":0,"V114":0,"CASH":0}
    first_activation={"TURTLE_S2":None,"V114":None}
    transitions=[]
    last_family=None

    for ts,family,trade in events:
        health={
            "TURTLE_S2":_family_health_at(streams["TURTLE_S2"],ts),
            "V114":_family_health_at(streams["V114"],ts),
        }
        chosen=_choose_family(health)
        mode="CASH" if chosen is None else chosen
        if mode!=last_family:
            transitions.append({
                "at":ts.isoformat(),
                "mode":mode,
                "health":health,
            })
            last_family=mode
        if chosen is None:
            counts["CASH"]+=1
            continue
        if first_activation[chosen] is None:
            first_activation[chosen]=ts.isoformat()
        if family==chosen:
            selected.append(trade)
            counts[family]+=1

    selected=_limit_concurrency(tuple(selected))
    return selected,{
        "selection_contract":{
            "shadow_history_continues_while_not_selected":True,
            "window_completed_trades":FAMILY_WINDOW_TRADES,
            "minimum_pf":MIN_TRAILING_PF,
            "minimum_expectancy_r":MIN_TRAILING_EXPECTANCY_R,
            "winner_rule":"highest causal trailing expectancy, then PF; CASH if no family passes",
            "new_numeric_threshold":False,
            "calendar_year_used":False,
        },
        "selected_counts":counts,
        "first_activation":first_activation,
        "transitions":transitions,
    }


def evaluate_v118(
    rows:Sequence[Bar],*,
    evaluation_start,
    evaluation_end,
    pip_size:float,
    cost_scenarios:Mapping[str,Any],
    broker_spec,
    leverage_tiers,
)->dict[str,Any]:
    bars=tuple(sorted(rows,key=lambda x:ensure_utc(x.timestamp)))
    start=ensure_utc(evaluation_start);end=ensure_utc(evaluation_end)
    dates=_trading_dates(bars,start=start,end=end)
    d1=_aggregate(bars,"D1")

    scenarios={}
    for cost_id,costs in cost_scenarios.items():
        turtle_all=simulate_turtle_s2(d1,bars,costs)
        _,_,v114_all,v114_diag=build_capital_preservation_portfolio(
            bars,costs=costs,pip_size=pip_size,evaluation_end=end
        )
        adaptive_all,selector_diag=build_adaptive_selector(
            turtle=turtle_all,
            v114=v114_all,
        )

        turtle=_period(turtle_all,start,end)
        v114=_period(v114_all,start,end)
        adaptive=_period(adaptive_all,start,end)

        eras={}
        for era,a,b in (
            ("2012_2018",datetime(2012,1,1,tzinfo=start.tzinfo),datetime(2019,1,1,tzinfo=start.tzinfo)),
            ("2019_2024",datetime(2019,1,1,tzinfo=start.tzinfo),datetime(2025,1,1,tzinfo=start.tzinfo)),
            ("2025_2026YTD",datetime(2025,1,1,tzinfo=start.tzinfo),end),
        ):
            eras[era]={
                "turtle_shadow":_metrics(_period(turtle,a,b)),
                "v114_shadow":_metrics(_period(v114,a,b)),
                "adaptive":_metrics(_period(adaptive,a,b)),
            }

        start_sensitivity={}
        for y in START_YEARS:
            a=datetime(y,1,1,tzinfo=start.tzinfo)
            if a>=end:continue
            start_sensitivity[str(y)]=_metrics(_period(adaptive,a,end))

        cash=_cash_path_stopout_safe(
            adaptive,
            spec=broker_spec,
            tiers=leverage_tiers,
            account_leverage=100.0,
            stopout_pct=50.0,
            trading_dates=dates,
        )

        scenarios[cost_id]={
            "full":{
                "turtle_shadow":_metrics(turtle),
                "v114_shadow":_metrics(v114),
                "adaptive":_metrics(adaptive),
            },
            "eras":eras,
            "start_sensitivity":start_sensitivity,
            "selector_diagnostics":selector_diag,
            "v114_diagnostics":v114_diag,
            "cash_fixed_001_no_risk_cap":cash,
        }

    return {
        "research_version":RESEARCH_VERSION,
        "artifact_contract":ARTIFACT_CONTRACT,
        "policy_effect":POLICY_EFFECT,
        "execution_influence":EXECUTION_INFLUENCE,
        "promotion_eligible":PROMOTION_ELIGIBLE,
        "live_execution_enabled":False,
        "contract":{
            "families":list(FAMILIES),
            "family_health_window_completed_trades":FAMILY_WINDOW_TRADES,
            "family_health_thresholds":"frozen V40/V47 >=30 / PF>=1.10 / expectancy>=+0.05R",
            "family_selection":"highest causal trailing expectancy then PF",
            "cash_when_no_family_active":True,
            "starting_balance_usd":100.0,
            "account_leverage":100.0,
            "lot":"fixed 0.01",
            "risk_pct_filter":None,
            "broker_stopout_pct":50.0,
            "parameter_search":False,
            "calendar_year_used_for_routing":False,
        },
        "scenarios":scenarios,
        "note":"V118 is a top-level adaptive family selector. Turtle and V114 continue learning in shadow regardless of account execution. The account allocates only to the family with currently proven causal health, otherwise CASH.",
    }

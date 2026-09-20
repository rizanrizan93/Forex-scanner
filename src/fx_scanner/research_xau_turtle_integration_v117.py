from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Sequence

from .demo_donchian_adaptive_tournament import TournamentTrade, compute_metrics
from .models import Bar, ensure_utc
from .research_xau_100usd_stopout_v23 import _cash_path_stopout_safe
from .research_xau_capital_preservation_v114 import build_capital_preservation_portfolio
from .research_xau_multihorizon_100usd_v20 import _limit_concurrency, _trading_dates
from .research_xau_public_master_benchmark_v116 import _aggregate, simulate_turtle_s2

RESEARCH_VERSION="XAU_TURTLE_INTEGRATION_V117"
ARTIFACT_CONTRACT="XAU_TURTLE_INTEGRATION_V117_EVIDENCE_1"
POLICY_EFFECT="SHADOW_ONLY"
EXECUTION_INFLUENCE=False
PROMOTION_ELIGIBLE=False

START_YEARS=(2012,2015,2019,2022,2025)


def _period(trades:Sequence[TournamentTrade],a,b)->tuple[TournamentTrade,...]:
    aa=ensure_utc(a);bb=ensure_utc(b)
    return tuple(t for t in trades if aa<=ensure_utc(t.entry_at)<bb)


def _metrics(trades):
    return compute_metrics(tuple(trades)).payload()


def _conservative_dedupe(trades:Sequence[TournamentTrade])->tuple[TournamentTrade,...]:
    # Avoid accidental double counting only when two families enter the same
    # XAU direction at the exact same timestamp. Otherwise keep independent signals.
    chosen={}
    priority={
        "RICHARD_DENNIS_ECKHARDT_TURTLE_S2_SINGLE_UNIT":2,
    }
    for t in trades:
        key=(ensure_utc(t.entry_at),str(t.direction).upper())
        cur=chosen.get(key)
        if cur is None:
            chosen[key]=t
            continue
        curp=priority.get(cur.strategy_id,1)
        newp=priority.get(t.strategy_id,1)
        if newp>curp:
            chosen[key]=t
    return tuple(sorted(chosen.values(),key=lambda x:(ensure_utc(x.entry_at),x.strategy_id)))


def evaluate_v117(
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
    d1=_aggregate(bars,"D1")
    dates=_trading_dates(bars,start=start,end=end)

    scenarios={}
    for cost_id,costs in cost_scenarios.items():
        turtle_all=simulate_turtle_s2(d1,bars,costs)
        turtle=_period(turtle_all,start,end)

        _,_,v114_all,v114_diag=build_capital_preservation_portfolio(
            bars,costs=costs,pip_size=pip_size,evaluation_end=end
        )
        v114=_period(v114_all,start,end)

        combined=_limit_concurrency(
            _conservative_dedupe((*v114,*turtle))
        )

        eras={}
        for era,a,b in (
            ("2012_2018",datetime(2012,1,1,tzinfo=start.tzinfo),datetime(2019,1,1,tzinfo=start.tzinfo)),
            ("2019_2024",datetime(2019,1,1,tzinfo=start.tzinfo),datetime(2025,1,1,tzinfo=start.tzinfo)),
            ("2025_2026YTD",datetime(2025,1,1,tzinfo=start.tzinfo),end),
        ):
            eras[era]={
                "turtle":_metrics(_period(turtle,a,b)),
                "v114":_metrics(_period(v114,a,b)),
                "combined":_metrics(_period(combined,a,b)),
            }

        start_sensitivity={}
        for y in START_YEARS:
            a=datetime(y,1,1,tzinfo=start.tzinfo)
            if a>=end:
                continue
            start_sensitivity[str(y)]={
                "turtle":_metrics(_period(turtle,a,end)),
                "combined":_metrics(_period(combined,a,end)),
            }

        annual={}
        for y in range(start.year,end.year+1):
            a=datetime(y,1,1,tzinfo=start.tzinfo)
            b=min(datetime(y+1,1,1,tzinfo=start.tzinfo),end)
            if a>=end:
                continue
            annual[str(y)]={
                "turtle":_metrics(_period(turtle,a,b)),
                "combined":_metrics(_period(combined,a,b)),
            }

        cash={}
        for name,trades in (
            ("turtle",turtle),
            ("v114",v114),
            ("combined",combined),
        ):
            cash[name]=_cash_path_stopout_safe(
                trades,
                spec=broker_spec,
                tiers=leverage_tiers,
                account_leverage=100.0,
                stopout_pct=50.0,
                trading_dates=dates,
            )

        scenarios[cost_id]={
            "full":{
                "turtle":_metrics(turtle),
                "v114":_metrics(v114),
                "combined":_metrics(combined),
            },
            "eras":eras,
            "start_sensitivity":start_sensitivity,
            "annual":annual,
            "cash_fixed_001_no_risk_cap":cash,
            "v114_diagnostics":v114_diag,
        }

    return {
        "research_version":RESEARCH_VERSION,
        "artifact_contract":ARTIFACT_CONTRACT,
        "policy_effect":POLICY_EFFECT,
        "execution_influence":EXECUTION_INFLUENCE,
        "promotion_eligible":PROMOTION_ELIGIBLE,
        "live_execution_enabled":False,
        "contract":{
            "turtle_rules":"frozen V116 corrected causal Turtle S2: 55D breakout / 20D opposite exit / N20 / 2N stop / single unit",
            "turtle_parameter_search":False,
            "v114_routing":"corrected frozen CASH-state routing",
            "combined_policy":"independent XAU alpha positions, exact same timestamp+direction conservatively deduped, max concurrency inherited",
            "cash_path":"$100 start / 1:100 / fixed 0.01 / no risk-percent cap / 50% stop-out survivability",
            "cost_scenarios":list(cost_scenarios.keys()),
            "start_sensitivity_years":list(START_YEARS),
            "calendar_year_used_for_routing":False,
        },
        "scenarios":scenarios,
        "note":"V117 does not tune Turtle or V114. It tests whether the independently robust Turtle family improves the tiny-account path and fills the 2019-24 gap.",
    }

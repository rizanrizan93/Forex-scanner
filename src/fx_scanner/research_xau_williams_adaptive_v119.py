from __future__ import annotations

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
from .research_xau_public_master_benchmark_v116 import (
    _aggregate,
    _cost_r,
    _day_key,
    _first_touch_direction,
    _m15_by_utc_day,
    _mk_trade,
    simulate_turtle_s2,
)

RESEARCH_VERSION="XAU_WILLIAMS_ADAPTIVE_V119"
ARTIFACT_CONTRACT="XAU_WILLIAMS_ADAPTIVE_V119_EVIDENCE_1"
POLICY_EFFECT="SHADOW_ONLY"
EXECUTION_INFLUENCE=False
PROMOTION_ELIGIBLE=False

WILLIAMS_ID="LARRY_WILLIAMS_DAILY_RANGE_BREAKOUT_BASIC"
FAMILIES=("WILLIAMS","TURTLE_S2","V114")
FAMILY_WINDOW_TRADES=MIN_COMPLETED_TRADES


def _period(trades:Sequence[TournamentTrade],a,b)->tuple[TournamentTrade,...]:
    aa=ensure_utc(a);bb=ensure_utc(b)
    return tuple(t for t in trades if aa<=ensure_utc(t.entry_at)<bb)


def _metrics(trades):
    return compute_metrics(tuple(trades)).payload()


def simulate_williams_basic(d1, m15_rows:Sequence[Bar], costs)->tuple[TournamentTrade,...]:
    """Portable clean-room encoding of Williams' published basic daily range breakout.

    Entry:
      today's open +/- 100% of the previous day's high-low range.
    Protective stop:
      50% of the previous day's range from entry.
    Profit exit:
      first subsequent daily opening that is profitable versus entry.

    No parameter search. One position at a time. Same-M15 entry/stop ambiguity
    is stop-first. Overnight adverse gaps through the stop exit at the worse open.
    """
    intraday=_m15_by_utc_day(m15_rows)
    trades=[]
    i=1
    while i<len(d1)-1:
        prev_range=float(d1[i-1].high)-float(d1[i-1].low)
        if prev_range<=0:
            i+=1;continue

        buy=float(d1[i].open)+prev_range
        sell=float(d1[i].open)-prev_range
        day=intraday.get(_day_key(d1[i].timestamp),())
        direction,touch_idx=_first_touch_direction(day,buy,sell)
        if direction in (None,"AMBIGUOUS") or touch_idx is None:
            i+=1;continue

        entry=buy if direction=="LONG" else sell
        risk=0.5*prev_range
        stop=entry-risk if direction=="LONG" else entry+risk
        entry_at=ensure_utc(day[touch_idx].timestamp)

        # Check stop from the trigger M15 bar through the remainder of entry day.
        stopped=False
        exit_at=None
        exitp=None
        exit_reason=None
        exit_daily_i=i
        entry_bar=day[touch_idx]
        if (direction=="LONG" and float(entry_bar.low)<=stop) or (
            direction=="SHORT" and float(entry_bar.high)>=stop
        ):
            stopped=True
            exit_at=entry_at
            exitp=stop
            exit_reason="STOP_FIRST_ENTRY_M15"
        else:
            for bar in day[touch_idx+1:]:
                if (direction=="LONG" and float(bar.low)<=stop) or (
                    direction=="SHORT" and float(bar.high)>=stop
                ):
                    stopped=True
                    exit_at=ensure_utc(bar.timestamp)
                    exitp=stop
                    exit_reason="PROTECTIVE_STOP"
                    break

        if stopped:
            c=_cost_r(risk,0.0,costs)
            trades.append(_mk_trade(
                WILLIAMS_ID,direction,d1[i].timestamp,entry_at,exit_at,
                i,i,entry,exitp,risk,stop,0.0,-1.0,c,0,exit_reason
            ))
            i+=1
            continue

        done=False
        for j in range(i+1,len(d1)):
            openp=float(d1[j].open)
            gap_stop=(direction=="LONG" and openp<=stop) or (
                direction=="SHORT" and openp>=stop
            )
            profitable=(direction=="LONG" and openp>entry) or (
                direction=="SHORT" and openp<entry
            )

            if gap_stop:
                exitp=openp
                exit_at=ensure_utc(d1[j].timestamp)
                exit_reason="GAP_THROUGH_STOP"
                gross=(exitp-entry)/risk if direction=="LONG" else (entry-exitp)/risk
                hold_days=float(j-i)
                c=_cost_r(risk,hold_days,costs)
                trades.append(_mk_trade(
                    WILLIAMS_ID,direction,d1[i].timestamp,entry_at,exit_at,
                    i,j,entry,exitp,risk,stop,0.0,gross,c,int(j-i),exit_reason
                ))
                i=j+1;done=True;break

            if profitable:
                exitp=openp
                exit_at=ensure_utc(d1[j].timestamp)
                exit_reason="FIRST_PROFITABLE_OPEN"
                gross=(exitp-entry)/risk if direction=="LONG" else (entry-exitp)/risk
                hold_days=float(j-i)
                c=_cost_r(risk,hold_days,costs)
                trades.append(_mk_trade(
                    WILLIAMS_ID,direction,d1[i].timestamp,entry_at,exit_at,
                    i,j,entry,exitp,risk,stop,0.0,gross,c,int(j-i),exit_reason
                ))
                i=j+1;done=True;break

            next_day=intraday.get(_day_key(d1[j].timestamp),())
            stop_bar=None
            for bar in next_day:
                if (direction=="LONG" and float(bar.low)<=stop) or (
                    direction=="SHORT" and float(bar.high)>=stop
                ):
                    stop_bar=bar;break
            if stop_bar is not None:
                exitp=stop
                exit_at=ensure_utc(stop_bar.timestamp)
                exit_reason="PROTECTIVE_STOP"
                hold_days=float(j-i)
                c=_cost_r(risk,hold_days,costs)
                trades.append(_mk_trade(
                    WILLIAMS_ID,direction,d1[i].timestamp,entry_at,exit_at,
                    i,j,entry,exitp,risk,stop,0.0,-1.0,c,int(j-i),exit_reason
                ))
                i=j+1;done=True;break

        if not done:
            i+=1

    return tuple(trades)


def _family_health_at(trades:Sequence[TournamentTrade],as_of)->dict[str,Any]:
    now=ensure_utc(as_of)
    completed=tuple(sorted(
        (t for t in trades if ensure_utc(t.exit_at)<now),
        key=lambda x:ensure_utc(x.exit_at),
    ))
    if len(completed)<FAMILY_WINDOW_TRADES:
        return {"active":False,"status":"INSUFFICIENT_SHADOW_HISTORY","n":len(completed),
                "profit_factor":None,"expectancy_r":None,"net_r":None}
    window=completed[-FAMILY_WINDOW_TRADES:]
    m=compute_metrics(window).payload()
    pf=m["profit_factor"];exp=m["expectancy_r"]
    active=bool(
        pf is not None and exp is not None
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


def build_selector(streams:Mapping[str,Sequence[TournamentTrade]]):
    normalized={k:tuple(sorted(v,key=lambda x:ensure_utc(x.signal_at))) for k,v in streams.items()}
    events=[]
    for family,trades in normalized.items():
        for t in trades:
            events.append((ensure_utc(t.signal_at),family,t))
    events.sort(key=lambda x:(x[0],x[1],ensure_utc(x[2].entry_at)))

    selected=[]
    transitions=[]
    last_mode=None
    selected_counts={**{k:0 for k in FAMILIES},"CASH":0}
    first_activation={k:None for k in FAMILIES}

    for ts,family,trade in events:
        health={name:_family_health_at(normalized[name],ts) for name in FAMILIES}
        active=[name for name in FAMILIES if health[name]["active"]]
        if active:
            active.sort(key=lambda name:(
                float(health[name]["expectancy_r"]),
                float(health[name]["profit_factor"]),
                name,
            ),reverse=True)
            mode=active[0]
        else:
            mode="CASH"

        if mode!=last_mode:
            transitions.append({"at":ts.isoformat(),"mode":mode,"health":health})
            last_mode=mode

        if mode=="CASH":
            selected_counts["CASH"]+=1
            continue
        if first_activation[mode] is None:
            first_activation[mode]=ts.isoformat()
        if family==mode:
            selected.append(trade)
            selected_counts[family]+=1

    return _limit_concurrency(tuple(selected)),{
        "family_health_window":FAMILY_WINDOW_TRADES,
        "minimum_pf":MIN_TRAILING_PF,
        "minimum_expectancy_r":MIN_TRAILING_EXPECTANCY_R,
        "selection":"highest causal expectancy then PF; otherwise CASH",
        "selected_counts":selected_counts,
        "first_activation":first_activation,
        "transitions":transitions,
    }


def evaluate_v119(
    rows:Sequence[Bar],*,
    evaluation_start,evaluation_end,pip_size:float,
    cost_scenarios:Mapping[str,Any],broker_spec,leverage_tiers,
)->dict[str,Any]:
    bars=tuple(sorted(rows,key=lambda x:ensure_utc(x.timestamp)))
    start=ensure_utc(evaluation_start);end=ensure_utc(evaluation_end)
    dates=_trading_dates(bars,start=start,end=end)
    d1=_aggregate(bars,"D1")
    scenarios={}

    for cost_id,costs in cost_scenarios.items():
        williams_all=simulate_williams_basic(d1,bars,costs)
        turtle_all=simulate_turtle_s2(d1,bars,costs)
        _,_,v114_all,v114_diag=build_capital_preservation_portfolio(
            bars,costs=costs,pip_size=pip_size,evaluation_end=end
        )
        adaptive_all,selector_diag=build_selector({
            "WILLIAMS":williams_all,
            "TURTLE_S2":turtle_all,
            "V114":v114_all,
        })

        streams={
            "williams_shadow":_period(williams_all,start,end),
            "turtle_shadow":_period(turtle_all,start,end),
            "v114_shadow":_period(v114_all,start,end),
            "adaptive":_period(adaptive_all,start,end),
        }

        eras={}
        for era,a,b in (
            ("2012_2018",datetime(2012,1,1,tzinfo=start.tzinfo),datetime(2019,1,1,tzinfo=start.tzinfo)),
            ("2019_2024",datetime(2019,1,1,tzinfo=start.tzinfo),datetime(2025,1,1,tzinfo=start.tzinfo)),
            ("2025_2026YTD",datetime(2025,1,1,tzinfo=start.tzinfo),end),
        ):
            eras[era]={name:_metrics(_period(trades,a,b)) for name,trades in streams.items()}

        cash=_cash_path_stopout_safe(
            streams["adaptive"],
            spec=broker_spec,tiers=leverage_tiers,
            account_leverage=100.0,stopout_pct=50.0,trading_dates=dates,
        )

        scenarios[cost_id]={
            "full":{name:_metrics(trades) for name,trades in streams.items()},
            "eras":eras,
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
            "williams_entry":"today open +/- 100% previous day high-low range",
            "williams_stop":"50% previous day range from entry",
            "williams_exit":"first profitable subsequent opening; protective stop always active",
            "williams_source_model":"portable clean-room encoding of Larry Williams published basic daily range breakout",
            "family_health":"last 30 completed shadow trades; PF>=1.10; expectancy>=+0.05R",
            "family_selection":"highest causal expectancy then PF; else CASH",
            "starting_balance_usd":100.0,
            "account_leverage":100.0,
            "lot":"fixed 0.01",
            "risk_pct_filter":None,
            "broker_stopout_pct":50.0,
            "parameter_search":False,
            "calendar_year_used_for_routing":False,
        },
        "scenarios":scenarios,
        "note":"V119 adds a capital-compatible Williams volatility-breakout family to the adaptive selector without retuning Turtle or V114.",
    }

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Sequence

from .demo_donchian_adaptive_tournament import TournamentTrade, compute_metrics
from .models import Bar, ensure_utc
from .research_xau_100usd_stopout_v23 import _cash_path_stopout_safe
from .research_xau_multihorizon_100usd_v20 import _trading_dates
from .research_xau_v110_robustness_v111 import assemble_v110_selector

RESEARCH_VERSION="XAU_2025_CHAMPION_DEPLOYMENT_V120"
ARTIFACT_CONTRACT="XAU_2025_CHAMPION_DEPLOYMENT_V120_EVIDENCE_1"
POLICY_EFFECT="SHADOW_ONLY"
EXECUTION_INFLUENCE=False
PROMOTION_ELIGIBLE=False

START_POINTS=(
    ("2025-01-01", datetime(2025,1,1)),
    ("2025-04-01", datetime(2025,4,1)),
    ("2025-07-01", datetime(2025,7,1)),
    ("2025-10-01", datetime(2025,10,1)),
    ("2026-01-01", datetime(2026,1,1)),
    ("2026-04-01", datetime(2026,4,1)),
    ("2026-07-01", datetime(2026,7,1)),
)


def _period(trades:Sequence[TournamentTrade], start, end)->tuple[TournamentTrade,...]:
    a=ensure_utc(start);b=ensure_utc(end)
    return tuple(t for t in trades if a<=ensure_utc(t.entry_at)<b)


def _metrics(trades):
    return compute_metrics(tuple(trades)).payload()


def evaluate_v120(
    rows:Sequence[Bar],*,
    evaluation_end,
    pip_size:float,
    cost_scenarios:Mapping[str,Any],
    broker_spec,
    leverage_tiers,
)->dict[str,Any]:
    bars=tuple(sorted(rows,key=lambda x:ensure_utc(x.timestamp)))
    end=ensure_utc(evaluation_end)
    tz=end.tzinfo
    scenarios={}

    for cost_id,costs in cost_scenarios.items():
        core_all,selector_all,selected=assemble_v110_selector(
            bars,costs=costs,pip_size=pip_size,evaluation_end=end
        )
        windows={}
        for label,naive_start in START_POINTS:
            start=naive_start.replace(tzinfo=tz)
            if start>=end:
                continue
            selector=_period(selector_all,start,end)
            core=_period(core_all,start,end)
            dates=_trading_dates(bars,start=start,end=end)
            cash=_cash_path_stopout_safe(
                selector,
                spec=broker_spec,
                tiers=leverage_tiers,
                account_leverage=100.0,
                stopout_pct=50.0,
                trading_dates=dates,
            )
            contributions={
                name:_metrics(_period(trades,start,end))
                for name,trades in selected.items()
            }
            windows[label]={
                "start":start.isoformat(),
                "end_exclusive":end.isoformat(),
                "selector_metrics":_metrics(selector),
                "core_metrics":_metrics(core),
                "selected_strategy_contribution":contributions,
                "cash_fresh_100_fixed_001":cash,
            }

        scenarios[cost_id]={
            "windows":windows,
            "full_selector_trade_count":len(selector_all),
        }

    return {
        "research_version":RESEARCH_VERSION,
        "artifact_contract":ARTIFACT_CONTRACT,
        "policy_effect":POLICY_EFFECT,
        "execution_influence":EXECUTION_INFLUENCE,
        "promotion_eligible":PROMOTION_ELIGIBLE,
        "live_execution_enabled":False,
        "contract":{
            "strategy":"exact frozen V110 2025-2026 champion selector",
            "families":"D1 Classic core + V110 D1 Staggered + M15 L12 + M15 L20",
            "routing_changes":False,
            "starting_balance_usd":100.0,
            "account_leverage":100.0,
            "lot":"fixed 0.01",
            "risk_pct_filter":None,
            "broker_stopout_pct":50.0,
            "warmup_history":"full 2011+ history retained before each fresh-account start",
            "start_points":[x[0] for x in START_POINTS],
            "calendar_dates_used_for_routing":False,
            "calendar_dates_used_for_evaluation_windows":True,
            "parameter_search":False,
        },
        "scenarios":scenarios,
        "note":"V120 does not alter V110. It asks only whether the high-profit 2025-2026 setup remains attractive when a fresh $100 account begins at different points inside the same broad era.",
    }

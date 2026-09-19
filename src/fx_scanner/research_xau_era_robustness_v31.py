from __future__ import annotations

from dataclasses import asdict
from typing import Any, Sequence

from .demo_donchian_adaptive_tournament import compute_metrics
from .models import Bar, ensure_utc
from .research_xau_100usd_stopout_v23 import _cash_path_stopout_safe
from .research_xau_margin_leverage_v21 import LeverageTier
from .research_xau_multihorizon_100usd_v20 import (
    BrokerLotSpec,
    _period,
    _portfolio_candidates,
    _trading_dates,
)

RESEARCH_VERSION = "XAU_ERA_ROBUSTNESS_V31"
ARTIFACT_CONTRACT = "XAU_ERA_ROBUSTNESS_V31_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
DIAGNOSTIC_ONLY = True

ACCOUNT_LEVERAGE = 100.0
MARGIN_FLOOR_PCT = 150.0
PORTFOLIOS = ("D1_ONLY","D1_PLUS_L20","D1_PLUS_L12_L20")


def _direction_metrics(trades):
    long_t=tuple(x for x in trades if str(x.direction).upper()=="LONG")
    short_t=tuple(x for x in trades if str(x.direction).upper()=="SHORT")
    return {
        "long": compute_metrics(long_t).payload(),
        "short": compute_metrics(short_t).payload(),
    }


def evaluate_era(
    bars: Sequence[Bar],
    *,
    era_id: str,
    era_start,
    era_end,
    pip_size: float,
    base_costs,
    stressed_costs,
    broker_spec: BrokerLotSpec,
    leverage_tiers: Sequence[LeverageTier],
) -> dict[str,Any]:
    rows=tuple(sorted(bars,key=lambda x:ensure_utc(x.timestamp)))
    start=ensure_utc(era_start); end=ensure_utc(era_end)
    if not rows:
        raise ValueError("V31_EMPTY_HISTORY")
    if ensure_utc(rows[0].timestamp) >= start:
        raise ValueError("V31_WARMUP_REQUIRED")

    candidates=_portfolio_candidates(
        rows,base_costs=base_costs,stressed_costs=stressed_costs,pip_size=pip_size
    )
    dates=_trading_dates(rows,start=start,end=end)
    out={}
    for portfolio_id in PORTFOLIOS:
        trades=_period(candidates[portfolio_id]["stress"],start=start,end=end)
        cash=_cash_path_stopout_safe(
            trades,spec=broker_spec,tiers=leverage_tiers,
            account_leverage=ACCOUNT_LEVERAGE,
            stopout_pct=MARGIN_FLOOR_PCT,
            trading_dates=dates,
        )
        out[portfolio_id]={
            "available_trades":len(trades),
            "metrics":compute_metrics(trades).payload(),
            "direction_metrics":_direction_metrics(trades),
            "cash_fixed_001":cash,
        }

    return {
        "research_version":RESEARCH_VERSION,
        "policy_effect":POLICY_EFFECT,
        "execution_influence":EXECUTION_INFLUENCE,
        "live_execution_enabled":False,
        "diagnostic_only":DIAGNOSTIC_ONLY,
        "promotion_eligible":False,
        "era_id":era_id,
        "era_start":start.isoformat(),
        "era_end_exclusive":end.isoformat(),
        "history_rows":len(rows),
        "history_start":ensure_utc(rows[0].timestamp).isoformat(),
        "history_end":ensure_utc(rows[-1].timestamp).isoformat(),
        "account_contract":{
            "starting_balance_usd":100.0,
            "fixed_lot":0.01,
            "account_leverage":ACCOUNT_LEVERAGE,
            "planned_stop_margin_floor_pct":MARGIN_FLOOR_PCT,
            "risk_pct_filter":None,
            "broker_volume":asdict(broker_spec),
            "dynamic_leverage_tiers":[asdict(x) for x in leverage_tiers],
        },
        "portfolio_results":out,
        "interpretation":(
            "Alternate-feed era robustness using Dukascopy BID M15 plus explicit broker-like "
            "transaction-cost stress. Exact V20/V24 D1+M15 signal rules are unchanged. "
            "Results are historical diagnostics only and do not grant execution authority."
        ),
    }

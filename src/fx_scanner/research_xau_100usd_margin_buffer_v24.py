from __future__ import annotations

from dataclasses import asdict
from typing import Any, Sequence

from .models import ensure_utc
from .research_xau_margin_leverage_v21 import LeverageTier
from .research_xau_multihorizon_100usd_v20 import (
    BrokerLotSpec,
    _period,
    _portfolio_candidates,
    _trading_dates,
)
from .research_xau_100usd_stopout_v23 import _cash_path_stopout_safe

RESEARCH_VERSION = "XAU_100USD_MARGIN_BUFFER_V24"
ARTIFACT_CONTRACT = "XAU_100USD_MARGIN_BUFFER_V24_EVIDENCE_1"
SYMBOL = "XAUUSD"
EXECUTION_INFLUENCE = False
POLICY_EFFECT = "SHADOW_ONLY"
DIAGNOSTIC_ONLY = True

ACCOUNT_LEVERAGES = (50.0, 100.0, 200.0, 500.0)
MARGIN_FLOORS_PCT = (50.0, 80.0, 100.0, 150.0)
PORTFOLIOS = ("D1_PLUS_L20", "D1_PLUS_L12_L20")


def evaluate_v24(
    rows,
    *,
    pip_size: float,
    base_costs,
    stressed_costs,
    broker_spec: BrokerLotSpec,
    leverage_tiers: Sequence[LeverageTier],
) -> dict[str, Any]:
    bars = tuple(sorted(rows, key=lambda x: ensure_utc(x.timestamp)))
    if len(bars) < 100_000:
        raise ValueError("V24_M15_HISTORY_TOO_SHORT")
    split_i = max(20_000, min(len(bars) - 1, int(len(bars) * 0.75)))
    split_time = ensure_utc(bars[split_i].timestamp)
    hold_dates = _trading_dates(bars, start=split_time)

    candidates = _portfolio_candidates(
        bars,
        base_costs=base_costs,
        stressed_costs=stressed_costs,
        pip_size=pip_size,
    )

    matrix = {}
    for portfolio_id in PORTFOLIOS:
        holdout = _period(candidates[portfolio_id]["stress"], start=split_time)
        scenarios = []
        for floor_pct in MARGIN_FLOORS_PCT:
            for leverage in ACCOUNT_LEVERAGES:
                row = _cash_path_stopout_safe(
                    holdout,
                    spec=broker_spec,
                    tiers=leverage_tiers,
                    account_leverage=leverage,
                    stopout_pct=floor_pct,
                    trading_dates=hold_dates,
                )
                row["planned_margin_floor_pct"] = floor_pct
                scenarios.append(row)
        matrix[portfolio_id] = {
            "available_holdout_trades": len(holdout),
            "scenarios": scenarios,
        }

    return {
        "research_version": RESEARCH_VERSION,
        "policy_effect": POLICY_EFFECT,
        "execution_influence": EXECUTION_INFLUENCE,
        "diagnostic_only": DIAGNOSTIC_ONLY,
        "promotion_eligible": False,
        "symbol": SYMBOL,
        "history": {"m15_rows": len(bars), "split_time": split_time.isoformat()},
        "broker_volume": {
            **asdict(broker_spec),
            "contract_units_per_lot": broker_spec.contract_units_per_lot,
        },
        "dynamic_leverage_tiers": [asdict(x) for x in leverage_tiers],
        "account_leverages": list(ACCOUNT_LEVERAGES),
        "planned_margin_floors_pct": list(MARGIN_FLOORS_PCT),
        "portfolio_scenarios": matrix,
        "interpretation_contract": {
            "50_pct": "published broker stop-out boundary; no operating buffer",
            "80_pct": "lowest observed cTrader margin-call notification threshold",
            "100_pct": "published FP Markets margin-call level",
            "150_pct": "higher observed cTrader notification threshold / conservative buffer",
        },
        "contract": {
            "starting_balance_usd": 100.0,
            "fixed_lot": 0.01,
            "risk_pct_filter": None,
            "server_side_sl_tp_required_for_future_demo_execution": True,
            "holdout_already_exposed": True,
        },
        "note": (
            "The margin-floor sensitivity is a broker-operability test, not a risk-per-trade rule. "
            "All results are post-hoc diagnostics and require prospective DEMO validation."
        ),
    }

from __future__ import annotations

from collections import defaultdict
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from .demo_donchian_adaptive_tournament import TournamentTrade, compute_metrics
from .models import Bar, ensure_utc
from .research_xau_causal_regime_edge_gate_v47 import (
    FAMILY_MAP,
    _family_streams,
    _route_family_candidates,
    gate_family_causally,
)
from .research_xau_hierarchical_regime_router_v35 import (
    _Asof,
    _direction_metrics,
    _max_losing_streak,
    _period,
    _resample_completed,
    build_h1_context,
)
from .research_xau_multihorizon_100usd_v20 import _trading_dates
from .research_xau_m15_dual_strategy import M15ResearchCosts
from .research_xau_secular_regime_router_v46 import build_secular_d1

RESEARCH_VERSION = "XAU_WVF_CONTEXT_V58"
ARTIFACT_CONTRACT = "XAU_WVF_CONTEXT_V58_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
PROMOTION_ELIGIBLE = False
DIAGNOSTIC_ONLY = True

BASE_ROUTE = "LONG_REACCEL_COST10"
WVF_LOOKBACK_H1 = 22
WVF_PERCENTILE_WINDOW = 50
WVF_PERCENTILE = 0.85
WVF_STATES = ("EXTREME", "NON_EXTREME", "UNAVAILABLE")


def _metrics(trades: Sequence[TournamentTrade]) -> dict[str, Any]:
    return compute_metrics(tuple(trades)).payload()


def _stats(trades: Sequence[TournamentTrade], trading_days: int) -> dict[str, Any]:
    values = tuple(trades)
    return {
        "trades": len(values),
        "trades_per_day": 0.0 if trading_days <= 0 else len(values) / float(trading_days),
        "max_losing_streak": _max_losing_streak(values),
        "metrics": _metrics(values),
        "direction_metrics": _direction_metrics(values),
    }


def build_h1_wvf_context(rows: Sequence[Bar]) -> pd.DataFrame:
    h1 = _resample_completed(rows, "1h").copy()
    highest = h1["close"].rolling(
        WVF_LOOKBACK_H1,
        min_periods=WVF_LOOKBACK_H1,
    ).max()
    h1["wvf"] = (
        (highest - h1["low"])
        / highest.replace(0.0, np.nan)
        * 100.0
    )
    h1["wvf_threshold"] = (
        h1["wvf"]
        .shift(1)
        .rolling(
            WVF_PERCENTILE_WINDOW,
            min_periods=WVF_PERCENTILE_WINDOW,
        )
        .quantile(WVF_PERCENTILE)
    )
    h1["wvf_extreme"] = (
        np.isfinite(h1["wvf"])
        & np.isfinite(h1["wvf_threshold"])
        & (h1["wvf"] >= h1["wvf_threshold"])
    )
    return h1


def _wvf_state(row: Mapping[str, Any] | None) -> str:
    if row is None:
        return "UNAVAILABLE"
    wvf = float(row.get("wvf", np.nan))
    threshold = float(row.get("wvf_threshold", np.nan))
    if not np.isfinite(wvf) or not np.isfinite(threshold):
        return "UNAVAILABLE"
    return "EXTREME" if wvf >= threshold else "NON_EXTREME"


def _bucket(
    trades: Sequence[TournamentTrade],
    *,
    wvf_context: pd.DataFrame,
    trading_days: int,
) -> dict[str, Any]:
    lookup = _Asof(wvf_context)
    groups: dict[str, list[TournamentTrade]] = defaultdict(list)
    ratios: dict[str, list[float]] = defaultdict(list)

    for trade in trades:
        row = lookup.row(trade.signal_at)
        state = _wvf_state(row)
        groups[state].append(trade)
        if row is not None:
            wvf = float(row.get("wvf", np.nan))
            threshold = float(row.get("wvf_threshold", np.nan))
            if np.isfinite(wvf) and np.isfinite(threshold) and threshold > 0.0:
                ratios[state].append(wvf / threshold)

    return {
        "all": _stats(tuple(trades), trading_days),
        "states": {
            state: {
                **_stats(tuple(groups.get(state, ())), trading_days),
                "mean_wvf_to_threshold": (
                    sum(ratios[state]) / len(ratios[state])
                    if ratios.get(state) else None
                ),
            }
            for state in WVF_STATES
        },
    }


def evaluate_v58(
    bars: Sequence[Bar],
    *,
    era_id: str,
    era_start,
    era_end,
    pip_size: float,
    cost_scenarios: Mapping[str, M15ResearchCosts],
) -> dict[str, Any]:
    rows = tuple(sorted(bars, key=lambda x: ensure_utc(x.timestamp)))
    if not rows:
        raise ValueError("V58_EMPTY_HISTORY")

    start = ensure_utc(era_start)
    end = ensure_utc(era_end)
    d1_context = build_secular_d1(rows)
    h1_context = build_h1_context(rows)
    wvf_context = build_h1_wvf_context(rows)

    full_dates = _trading_dates(
        rows,
        start=ensure_utc(rows[0].timestamp),
        end=end,
    )
    era_dates = _trading_dates(rows, start=start, end=end)
    trading_days = len(era_dates)

    scenario_results: dict[str, Any] = {}
    for cost_id, costs in cost_scenarios.items():
        annotated_by_family = _family_streams(
            rows,
            costs=costs,
            pip_size=pip_size,
            d1_context=d1_context,
            h1_context=h1_context,
        )

        families: dict[str, Any] = {}
        ungated_all: list[TournamentTrade] = []
        gated_all: list[TournamentTrade] = []

        for family in FAMILY_MAP:
            candidate = _route_family_candidates(
                annotated_by_family[family],
                route=BASE_ROUTE,
            )
            gated, gate = gate_family_causally(
                candidate,
                trading_dates=full_dates,
            )
            ungated_era = _period(candidate, start=start, end=end)
            gated_era = _period(gated, start=start, end=end)
            ungated_all.extend(ungated_era)
            gated_all.extend(gated_era)
            families[family] = {
                "gate": gate,
                "ungated_wvf": _bucket(
                    ungated_era,
                    wvf_context=wvf_context,
                    trading_days=trading_days,
                ),
                "gated_wvf": _bucket(
                    gated_era,
                    wvf_context=wvf_context,
                    trading_days=trading_days,
                ),
            }

        ungated_all = sorted(
            ungated_all,
            key=lambda x: (ensure_utc(x.entry_at), str(x.strategy_id)),
        )
        gated_all = sorted(
            gated_all,
            key=lambda x: (ensure_utc(x.entry_at), str(x.strategy_id)),
        )
        scenario_results[cost_id] = {
            "families": families,
            "combined_ungated": _bucket(
                tuple(ungated_all),
                wvf_context=wvf_context,
                trading_days=trading_days,
            ),
            "combined_gated": _bucket(
                tuple(gated_all),
                wvf_context=wvf_context,
                trading_days=trading_days,
            ),
        }

    return {
        "research_version": RESEARCH_VERSION,
        "artifact_contract": ARTIFACT_CONTRACT,
        "policy_effect": POLICY_EFFECT,
        "execution_influence": EXECUTION_INFLUENCE,
        "promotion_eligible": PROMOTION_ELIGIBLE,
        "live_execution_enabled": False,
        "diagnostic_only": DIAGNOSTIC_ONLY,
        "era_id": era_id,
        "era_start": start.isoformat(),
        "era_end_exclusive": end.isoformat(),
        "trading_days": trading_days,
        "preregistered_contract": {
            "base_route": BASE_ROUTE,
            "wvf_formula": "(highest completed H1 close 22 - H1 low) / highest close 22 * 100",
            "wvf_extreme_threshold": "current WVF >= prior-50-completed-H1 85th percentile",
            "wvf_parameters_identical_to_v49": True,
            "states": list(WVF_STATES),
            "trade_filter_applied": False,
            "position_sizing_changed": False,
            "signal_logic_retuned": False,
            "threshold_grid_search": False,
            "selection_uses_future_outcomes": False,
            "execution_authority": False,
        },
        "scenario_results": scenario_results,
        "note": (
            "V58 tests Williams VIX Fix only as contemporaneous volatility/capitulation context "
            "for the broader frozen reacceleration route. It does not use WVF as an entry signal, "
            "trade filter, or sizing rule."
        ),
    }

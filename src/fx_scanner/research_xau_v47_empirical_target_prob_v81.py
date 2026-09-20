from __future__ import annotations

from bisect import bisect_right
from collections import defaultdict
from datetime import datetime, timezone
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
    _direction_metrics,
    _max_losing_streak,
    _period,
    _resample_completed,
    build_h1_context,
)
from .research_xau_multihorizon_100usd_v20 import _trading_dates
from .research_xau_m15_dual_strategy import M15ResearchCosts
from .research_xau_secular_regime_router_v46 import build_secular_d1

RESEARCH_VERSION = "XAU_V47_EMPIRICAL_TARGET_PROB_V81"
ARTIFACT_CONTRACT = "XAU_V47_EMPIRICAL_TARGET_PROB_V81_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
PROMOTION_ELIGIBLE = False
DIAGNOSTIC_ONLY = True

FULL_START = datetime(2012, 1, 1, tzinfo=timezone.utc)
FULL_END = datetime(2026, 9, 20, tzinfo=timezone.utc)
FROZEN_ROUTE = "SECULAR_BULL_REACCEL_LONG_COST10"
REQUIRED_COSTS = ("LOW_1700", "V24_STRESS_4675")
LOOKBACK_DAYS = 60

PROBABILITY_BUCKETS = (
    "LE_0_10",
    "GT_0_10_LE_0_25",
    "GT_0_25_LE_0_50",
    "GT_0_50",
    "UNAVAILABLE",
)


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


def _unique(trades: Sequence[TournamentTrade]) -> tuple[TournamentTrade, ...]:
    seen: set[tuple[Any, ...]] = set()
    output: list[TournamentTrade] = []
    for trade in sorted(
        trades,
        key=lambda x: (
            ensure_utc(x.signal_at),
            str(x.strategy_id),
            ensure_utc(x.entry_at),
        ),
    ):
        key = (
            str(trade.strategy_id),
            ensure_utc(trade.signal_at),
            ensure_utc(trade.entry_at),
            ensure_utc(trade.exit_at),
            str(trade.direction),
        )
        if key in seen:
            continue
        seen.add(key)
        output.append(trade)
    return tuple(output)


def build_daily_range_history(rows: Sequence[Bar]) -> pd.DataFrame:
    d1 = _resample_completed(rows, "1D").copy()
    d1["daily_range"] = d1["high"] - d1["low"]
    return d1


def _probability_bucket(value: float | None) -> str:
    if value is None or not np.isfinite(float(value)):
        return "UNAVAILABLE"
    x = float(value)
    if x <= 0.10:
        return "LE_0_10"
    if x <= 0.25:
        return "GT_0_10_LE_0_25"
    if x <= 0.50:
        return "GT_0_25_LE_0_50"
    return "GT_0_50"


def _geometry(
    trade: TournamentTrade,
    *,
    rows: Sequence[Bar],
    d1_frame: pd.DataFrame,
    d1_times: Sequence[datetime],
    d1_ranges: Sequence[float],
) -> dict[str, Any]:
    signal_at = ensure_utc(trade.signal_at)
    d1_index = bisect_right(d1_times, signal_at) - 1
    if d1_index < LOOKBACK_DAYS - 1:
        return {
            "available": False,
            "historical_exceedance_probability": None,
            "bucket": "UNAVAILABLE",
            "projected_total_daily_range": None,
            "current_completed_daily_range": None,
            "target_distance": abs(float(trade.take_profit) - float(trade.entry_price)),
            "prior_median_range": None,
            "prior_q75_range": None,
        }

    history = [
        float(x)
        for x in d1_ranges[d1_index - LOOKBACK_DAYS + 1 : d1_index + 1]
        if np.isfinite(float(x)) and float(x) > 0.0
    ]
    if len(history) != LOOKBACK_DAYS:
        return {
            "available": False,
            "historical_exceedance_probability": None,
            "bucket": "UNAVAILABLE",
            "projected_total_daily_range": None,
            "current_completed_daily_range": None,
            "target_distance": abs(float(trade.take_profit) - float(trade.entry_price)),
            "prior_median_range": None,
            "prior_q75_range": None,
        }

    day_start = d1_times[d1_index]
    signal_index = int(trade.signal_index)
    if signal_index < 0 or signal_index >= len(rows):
        return {
            "available": False,
            "historical_exceedance_probability": None,
            "bucket": "UNAVAILABLE",
            "projected_total_daily_range": None,
            "current_completed_daily_range": None,
            "target_distance": abs(float(trade.take_profit) - float(trade.entry_price)),
            "prior_median_range": float(np.median(history)),
            "prior_q75_range": float(np.quantile(history, 0.75)),
        }

    day_rows: list[Bar] = []
    index = signal_index
    while index >= 0:
        row = rows[index]
        stamp = ensure_utc(row.timestamp)
        if stamp < day_start:
            break
        if stamp <= signal_at:
            day_rows.append(row)
        index -= 1
    if not day_rows:
        return {
            "available": False,
            "historical_exceedance_probability": None,
            "bucket": "UNAVAILABLE",
            "projected_total_daily_range": None,
            "current_completed_daily_range": None,
            "target_distance": abs(float(trade.take_profit) - float(trade.entry_price)),
            "prior_median_range": float(np.median(history)),
            "prior_q75_range": float(np.quantile(history, 0.75)),
        }

    current_high = max(float(row.high) for row in day_rows)
    current_low = min(float(row.low) for row in day_rows)
    target = float(trade.take_profit)
    direction = str(trade.direction).upper()

    if direction == "LONG":
        projected_high = max(current_high, target)
        projected_low = current_low
    else:
        projected_high = current_high
        projected_low = min(current_low, target)

    current_range = current_high - current_low
    projected_range = projected_high - projected_low
    probability = sum(1 for value in history if value >= projected_range) / float(LOOKBACK_DAYS)

    return {
        "available": True,
        "historical_exceedance_probability": probability,
        "bucket": _probability_bucket(probability),
        "projected_total_daily_range": projected_range,
        "current_completed_daily_range": current_range,
        "additional_range_needed": max(0.0, projected_range - current_range),
        "target_distance": abs(target - float(trade.entry_price)),
        "prior_median_range": float(np.median(history)),
        "prior_q75_range": float(np.quantile(history, 0.75)),
        "projected_to_median": projected_range / float(np.median(history)),
        "projected_to_q75": projected_range / float(np.quantile(history, 0.75)),
    }


def _build_geometry_map(
    rows: Sequence[Bar],
    trades: Sequence[TournamentTrade],
) -> dict[tuple[Any, ...], dict[str, Any]]:
    d1 = build_daily_range_history(rows)
    times = [
        ensure_utc(x.to_pydatetime() if hasattr(x, "to_pydatetime") else x)
        for x in d1["time"]
    ]
    ranges = [float(x) for x in d1["daily_range"]]

    output: dict[tuple[Any, ...], dict[str, Any]] = {}
    for trade in trades:
        key = (
            str(trade.strategy_id),
            ensure_utc(trade.signal_at),
            ensure_utc(trade.entry_at),
            str(trade.direction),
        )
        output[key] = _geometry(
            trade,
            rows=rows,
            d1_frame=d1,
            d1_times=times,
            d1_ranges=ranges,
        )
    return output


def _trade_key(trade: TournamentTrade) -> tuple[Any, ...]:
    return (
        str(trade.strategy_id),
        ensure_utc(trade.signal_at),
        ensure_utc(trade.entry_at),
        str(trade.direction),
    )


def _payload(
    trades: Sequence[TournamentTrade],
    *,
    geometry_map: Mapping[tuple[Any, ...], Mapping[str, Any]],
    trading_days: int,
) -> dict[str, Any]:
    groups: dict[str, list[TournamentTrade]] = defaultdict(list)
    winner_prob: list[float] = []
    loser_prob: list[float] = []
    winner_projected_median: list[float] = []
    loser_projected_median: list[float] = []

    for trade in trades:
        geometry = geometry_map.get(_trade_key(trade), {})
        bucket = str(geometry.get("bucket") or "UNAVAILABLE")
        if bucket not in PROBABILITY_BUCKETS:
            bucket = "UNAVAILABLE"
        groups[bucket].append(trade)

        probability = geometry.get("historical_exceedance_probability")
        projected_to_median = geometry.get("projected_to_median")
        winner = float(trade.net_r) > 0.0
        if probability is not None:
            (winner_prob if winner else loser_prob).append(float(probability))
        if projected_to_median is not None:
            (winner_projected_median if winner else loser_projected_median).append(
                float(projected_to_median)
            )

    def mean(values: Sequence[float]) -> float | None:
        return None if not values else sum(values) / float(len(values))

    return {
        "all": _stats(tuple(trades), trading_days),
        "probability_buckets": {
            bucket: _stats(tuple(groups.get(bucket, ())), trading_days)
            for bucket in PROBABILITY_BUCKETS
        },
        "winner_loser_geometry": {
            "winner_mean_exceedance_probability": mean(winner_prob),
            "loser_mean_exceedance_probability": mean(loser_prob),
            "winner_mean_projected_to_median": mean(winner_projected_median),
            "loser_mean_projected_to_median": mean(loser_projected_median),
        },
    }


def _slice(
    trades: Sequence[TournamentTrade],
    *,
    start: datetime,
    end: datetime,
) -> tuple[TournamentTrade, ...]:
    return tuple(
        trade
        for trade in trades
        if start <= ensure_utc(trade.entry_at) < end
    )


def evaluate_v81(
    bars: Sequence[Bar],
    *,
    pip_size: float,
    cost_scenarios: Mapping[str, M15ResearchCosts],
) -> dict[str, Any]:
    rows = tuple(sorted(bars, key=lambda x: ensure_utc(x.timestamp)))
    if not rows:
        raise ValueError("V81_EMPTY_HISTORY")
    missing = [x for x in REQUIRED_COSTS if x not in cost_scenarios]
    if missing:
        raise ValueError(f"V81_MISSING_REQUIRED_COSTS:{missing}")

    d1_context = build_secular_d1(rows)
    h1_context = build_h1_context(rows)
    full_dates = _trading_dates(
        rows,
        start=ensure_utc(rows[0].timestamp),
        end=FULL_END,
    )
    era_dates = _trading_dates(rows, start=FULL_START, end=FULL_END)
    era_days = len(era_dates)

    scenarios: dict[str, Any] = {}
    for cost_id in REQUIRED_COSTS:
        costs = cost_scenarios[cost_id]
        annotated = _family_streams(
            rows,
            costs=costs,
            pip_size=pip_size,
            d1_context=d1_context,
            h1_context=h1_context,
        )

        gated_all: list[TournamentTrade] = []
        family_gates: dict[str, Any] = {}
        for family in FAMILY_MAP:
            candidate = _route_family_candidates(
                annotated[family],
                route=FROZEN_ROUTE,
            )
            gated, gate = gate_family_causally(
                candidate,
                trading_dates=full_dates,
            )
            gated = _period(gated, start=FULL_START, end=FULL_END)
            gated_all.extend(gated)
            family_gates[family] = {
                **gate,
                "era_metrics": _metrics(gated),
            }

        satellite = _unique(gated_all)
        geometry_map = _build_geometry_map(rows, satellite)

        annual: dict[str, Any] = {}
        for year in range(FULL_START.year, FULL_END.year + 1):
            start = datetime(year, 1, 1, tzinfo=timezone.utc)
            end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
            period = _slice(satellite, start=start, end=end)
            if not period:
                continue
            days = sum(1 for d in era_dates if start.date() <= d < end.date())
            annual[str(year)] = _payload(
                period,
                geometry_map=geometry_map,
                trading_days=days,
            )

        windows: dict[str, Any] = {}
        for label, start, end in (
            (
                "WEAK_2022_2024",
                datetime(2022, 1, 1, tzinfo=timezone.utc),
                datetime(2025, 1, 1, tzinfo=timezone.utc),
            ),
            (
                "RECENT_2025_2026YTD",
                datetime(2025, 1, 1, tzinfo=timezone.utc),
                FULL_END,
            ),
        ):
            period = _slice(satellite, start=start, end=end)
            days = sum(1 for d in era_dates if start.date() <= d < end.date())
            windows[label] = _payload(
                period,
                geometry_map=geometry_map,
                trading_days=days,
            )

        scenarios[cost_id] = {
            "family_gates": family_gates,
            "satellite": _stats(satellite, era_days),
            "full_period": _payload(
                satellite,
                geometry_map=geometry_map,
                trading_days=era_days,
            ),
            "annual": annual,
            "diagnostic_windows": windows,
        }

    return {
        "research_version": RESEARCH_VERSION,
        "artifact_contract": ARTIFACT_CONTRACT,
        "policy_effect": POLICY_EFFECT,
        "execution_influence": EXECUTION_INFLUENCE,
        "promotion_eligible": PROMOTION_ELIGIBLE,
        "live_execution_enabled": False,
        "diagnostic_only": DIAGNOSTIC_ONLY,
        "period_start": FULL_START.isoformat(),
        "period_end_exclusive": FULL_END.isoformat(),
        "preregistered_contract": {
            "base_route": FROZEN_ROUTE,
            "required_costs": list(REQUIRED_COSTS),
            "lookback_completed_daily_ranges": LOOKBACK_DAYS,
            "credibility_measure": "fraction of prior 60 completed D1 ranges >= projected total current-day range if unchanged TP is reached",
            "probability_buckets": list(PROBABILITY_BUCKETS),
            "current_day_range_uses_completed_m15_only": True,
            "entry_changed": False,
            "stop_changed": False,
            "target_changed": False,
            "trade_filter_applied": False,
            "probability_bucket_selected_as_winner": False,
            "threshold_grid_search": False,
            "selection_uses_future_outcomes": False,
            "execution_authority": False,
        },
        "scenarios": scenarios,
        "note": (
            "V81 is a transparent AIR-style historical target-credibility diagnostic. It does not "
            "claim to reproduce proprietary AIRV3 logic. It converts the unchanged V47 target into "
            "an empirical prior-60-session range exceedance probability using only information "
            "available at signal time."
        ),
    }

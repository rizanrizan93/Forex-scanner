from __future__ import annotations

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
    _Asof,
    _direction_metrics,
    _max_losing_streak,
    _period,
    _resample_completed,
    _wilder_atr,
    build_h1_context,
)
from .research_xau_multihorizon_100usd_v20 import _trading_dates
from .research_xau_m15_dual_strategy import M15ResearchCosts
from .research_xau_secular_regime_router_v46 import build_secular_d1

RESEARCH_VERSION = "XAU_V47_TARGET_CREDIBILITY_V74"
ARTIFACT_CONTRACT = "XAU_V47_TARGET_CREDIBILITY_V74_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
PROMOTION_ELIGIBLE = False
DIAGNOSTIC_ONLY = True

FULL_START = datetime(2012, 1, 1, tzinfo=timezone.utc)
FULL_END = datetime(2026, 9, 20, tzinfo=timezone.utc)
FROZEN_ROUTE = "SECULAR_BULL_REACCEL_LONG_COST10"
REQUIRED_COSTS = ("LOW_1700", "V24_STRESS_4675")

H1_ATR_PERIOD = 14
D1_RANGE_LOOKBACK = 60

STOP_ATR_BUCKETS = (
    "LE_0_50",
    "GT_0_50_LE_1_00",
    "GT_1_00_LE_1_50",
    "GT_1_50",
    "UNAVAILABLE",
)
TARGET_RANGE_BUCKETS = (
    "LE_0_25",
    "GT_0_25_LE_0_50",
    "GT_0_50_LE_0_75",
    "GT_0_75",
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


def build_h1_noise_context(rows: Sequence[Bar]) -> pd.DataFrame:
    h1 = _resample_completed(rows, "1h").copy()
    h1["atr14"] = _wilder_atr(h1, H1_ATR_PERIOD)
    return h1


def build_d1_range_context(rows: Sequence[Bar]) -> pd.DataFrame:
    d1 = _resample_completed(rows, "1D").copy()
    d1["daily_range"] = d1["high"] - d1["low"]
    # At a signal timestamp, the as-of row is already a fully completed D1 bar.
    # Therefore the rolling window below contains completed history only.
    rolling = d1["daily_range"].rolling(
        D1_RANGE_LOOKBACK,
        min_periods=D1_RANGE_LOOKBACK,
    )
    d1["range_median60"] = rolling.median()
    d1["range_q75_60"] = rolling.quantile(0.75)
    return d1


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if np.isfinite(number) else None


def _stop_bucket(value: float | None) -> str:
    if value is None:
        return "UNAVAILABLE"
    if value <= 0.50:
        return "LE_0_50"
    if value <= 1.00:
        return "GT_0_50_LE_1_00"
    if value <= 1.50:
        return "GT_1_00_LE_1_50"
    return "GT_1_50"


def _target_bucket(value: float | None) -> str:
    if value is None:
        return "UNAVAILABLE"
    if value <= 0.25:
        return "LE_0_25"
    if value <= 0.50:
        return "GT_0_25_LE_0_50"
    if value <= 0.75:
        return "GT_0_50_LE_0_75"
    return "GT_0_75"


def _geometry(
    trade: TournamentTrade,
    *,
    h1_lookup: _Asof,
    d1_range_lookup: _Asof,
) -> dict[str, Any]:
    h1 = h1_lookup.row(trade.signal_at)
    d1 = d1_range_lookup.row(trade.signal_at)

    atr14 = None if h1 is None else _finite(h1.get("atr14"))
    median60 = None if d1 is None else _finite(d1.get("range_median60"))
    q75_60 = None if d1 is None else _finite(d1.get("range_q75_60"))

    stop_distance = abs(float(trade.entry_price) - float(trade.stop_loss))
    target_distance = abs(float(trade.take_profit) - float(trade.entry_price))

    stop_to_h1_atr = (
        None
        if atr14 is None or atr14 <= 0.0
        else stop_distance / atr14
    )
    target_to_median = (
        None
        if median60 is None or median60 <= 0.0
        else target_distance / median60
    )
    target_to_q75 = (
        None
        if q75_60 is None or q75_60 <= 0.0
        else target_distance / q75_60
    )

    return {
        "stop_distance": stop_distance,
        "target_distance": target_distance,
        "h1_atr14": atr14,
        "d1_range_median60": median60,
        "d1_range_q75_60": q75_60,
        "stop_to_h1_atr": stop_to_h1_atr,
        "target_to_d1_median60": target_to_median,
        "target_to_d1_q75_60": target_to_q75,
        "stop_bucket": _stop_bucket(stop_to_h1_atr),
        "target_bucket": _target_bucket(target_to_median),
    }


def _payload(
    trades: Sequence[TournamentTrade],
    *,
    h1_lookup: _Asof,
    d1_range_lookup: _Asof,
    trading_days: int,
) -> dict[str, Any]:
    stop_groups: dict[str, list[TournamentTrade]] = defaultdict(list)
    target_groups: dict[str, list[TournamentTrade]] = defaultdict(list)
    winner_stop: list[float] = []
    loser_stop: list[float] = []
    winner_target: list[float] = []
    loser_target: list[float] = []
    winner_target_q75: list[float] = []
    loser_target_q75: list[float] = []

    for trade in trades:
        row = _geometry(
            trade,
            h1_lookup=h1_lookup,
            d1_range_lookup=d1_range_lookup,
        )
        stop_groups[str(row["stop_bucket"])].append(trade)
        target_groups[str(row["target_bucket"])].append(trade)

        is_winner = float(trade.net_r) > 0.0
        for value, winners, losers in (
            (row["stop_to_h1_atr"], winner_stop, loser_stop),
            (row["target_to_d1_median60"], winner_target, loser_target),
            (row["target_to_d1_q75_60"], winner_target_q75, loser_target_q75),
        ):
            if value is None:
                continue
            (winners if is_winner else losers).append(float(value))

    def mean(values: Sequence[float]) -> float | None:
        return None if not values else sum(values) / float(len(values))

    return {
        "all": _stats(tuple(trades), trading_days),
        "stop_to_h1_atr": {
            bucket: _stats(tuple(stop_groups.get(bucket, ())), trading_days)
            for bucket in STOP_ATR_BUCKETS
        },
        "target_to_d1_median60": {
            bucket: _stats(tuple(target_groups.get(bucket, ())), trading_days)
            for bucket in TARGET_RANGE_BUCKETS
        },
        "winner_loser_geometry": {
            "winner_mean_stop_to_h1_atr": mean(winner_stop),
            "loser_mean_stop_to_h1_atr": mean(loser_stop),
            "winner_mean_target_to_d1_median60": mean(winner_target),
            "loser_mean_target_to_d1_median60": mean(loser_target),
            "winner_mean_target_to_d1_q75_60": mean(winner_target_q75),
            "loser_mean_target_to_d1_q75_60": mean(loser_target_q75),
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


def evaluate_v74(
    bars: Sequence[Bar],
    *,
    pip_size: float,
    cost_scenarios: Mapping[str, M15ResearchCosts],
) -> dict[str, Any]:
    rows = tuple(sorted(bars, key=lambda x: ensure_utc(x.timestamp)))
    if not rows:
        raise ValueError("V74_EMPTY_HISTORY")
    missing = [x for x in REQUIRED_COSTS if x not in cost_scenarios]
    if missing:
        raise ValueError(f"V74_MISSING_REQUIRED_COSTS:{missing}")

    d1_context = build_secular_d1(rows)
    h1_context = build_h1_context(rows)
    h1_noise = build_h1_noise_context(rows)
    d1_ranges = build_d1_range_context(rows)
    h1_lookup = _Asof(h1_noise)
    d1_range_lookup = _Asof(d1_ranges)

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
                h1_lookup=h1_lookup,
                d1_range_lookup=d1_range_lookup,
                trading_days=days,
            )

        windows = {}
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
                h1_lookup=h1_lookup,
                d1_range_lookup=d1_range_lookup,
                trading_days=days,
            )

        scenarios[cost_id] = {
            "family_gates": family_gates,
            "satellite": _stats(satellite, era_days),
            "full_period": _payload(
                satellite,
                h1_lookup=h1_lookup,
                d1_range_lookup=d1_range_lookup,
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
            "h1_noise_measure": "completed-H1 Wilder ATR14",
            "d1_target_credibility_measure": "target distance / completed prior-history D1 range distribution",
            "d1_range_lookback_completed_days": D1_RANGE_LOOKBACK,
            "stop_atr_buckets": list(STOP_ATR_BUCKETS),
            "target_median_range_buckets": list(TARGET_RANGE_BUCKETS),
            "bucket_thresholds_are_economic_diagnostics_not_optimized": True,
            "entry_changed": False,
            "stop_changed": False,
            "target_changed": False,
            "trade_filter_applied": False,
            "bucket_selected_as_winner": False,
            "threshold_grid_search": False,
            "selection_uses_future_outcomes": False,
            "execution_authority": False,
        },
        "scenarios": scenarios,
        "note": (
            "V74 tests stop-noise and target-credibility geometry only. The frozen V47 entry, "
            "stop and target are not modified. Any bucket separation is hypothesis generation "
            "and cannot become a rule without independent causal/prospective validation."
        ),
    }

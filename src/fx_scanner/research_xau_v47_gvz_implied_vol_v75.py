from __future__ import annotations

from collections import defaultdict
from datetime import datetime, time, timedelta, timezone
from math import isfinite, sqrt
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
    build_h1_context,
)
from .research_xau_multihorizon_100usd_v20 import _trading_dates
from .research_xau_m15_dual_strategy import M15ResearchCosts
from .research_xau_secular_regime_router_v46 import build_secular_d1

RESEARCH_VERSION = "XAU_V47_GVZ_IMPLIED_VOL_V75"
ARTIFACT_CONTRACT = "XAU_V47_GVZ_IMPLIED_VOL_V75_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
PROMOTION_ELIGIBLE = False
DIAGNOSTIC_ONLY = True

FULL_START = datetime(2012, 1, 1, tzinfo=timezone.utc)
FULL_END = datetime(2026, 9, 20, tzinfo=timezone.utc)
FROZEN_ROUTE = "SECULAR_BULL_REACCEL_LONG_COST10"
REQUIRED_COSTS = ("LOW_1700", "V24_STRESS_4675")

GVZ_LOOKBACK = 252
GVZ_STATES = ("Q1_LOW", "Q2", "Q3", "Q4", "Q5_HIGH", "UNAVAILABLE")
STOP_IV_BUCKETS = (
    "LE_0_25",
    "GT_0_25_LE_0_50",
    "GT_0_50_LE_1_00",
    "GT_1_00",
    "UNAVAILABLE",
)
TARGET_IV_BUCKETS = (
    "LE_0_50",
    "GT_0_50_LE_1_00",
    "GT_1_00_LE_1_50",
    "GT_1_50",
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


def build_gvz_context(
    rows: Sequence[tuple[datetime, float]],
) -> pd.DataFrame:
    ordered = sorted(
        (
            (ensure_utc(stamp), float(value))
            for stamp, value in rows
            if isfinite(float(value)) and float(value) > 0.0
        ),
        key=lambda x: x[0],
    )
    records: list[dict[str, Any]] = []
    history: list[float] = []

    for stamp, value in ordered:
        if len(history) >= GVZ_LOOKBACK:
            sample = np.asarray(history[-GVZ_LOOKBACK:], dtype=float)
            q20, q40, q60, q80 = (
                float(np.quantile(sample, 0.20)),
                float(np.quantile(sample, 0.40)),
                float(np.quantile(sample, 0.60)),
                float(np.quantile(sample, 0.80)),
            )
            if value <= q20:
                state = "Q1_LOW"
            elif value <= q40:
                state = "Q2"
            elif value <= q60:
                state = "Q3"
            elif value <= q80:
                state = "Q4"
            else:
                state = "Q5_HIGH"
        else:
            q20 = q40 = q60 = q80 = float("nan")
            state = "UNAVAILABLE"

        records.append(
            {
                "time": stamp,
                "gvz_close": value,
                "gvz_state": state,
                "q20": q20,
                "q40": q40,
                "q60": q60,
                "q80": q80,
            }
        )
        history.append(value)

    return pd.DataFrame.from_records(records)


def availability_timestamp(date_value: datetime) -> datetime:
    """
    FRED/Cboe daily GVZ is a close. Make it available only from 00:00 UTC
    on the following calendar day. This is intentionally conservative:
    no same-day XAU signal can see that day's final GVZ close.
    """
    day = ensure_utc(date_value).date()
    return datetime.combine(
        day + timedelta(days=1),
        time.min,
        tzinfo=timezone.utc,
    )


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if np.isfinite(number) else None


def _stop_bucket(value: float | None) -> str:
    if value is None:
        return "UNAVAILABLE"
    if value <= 0.25:
        return "LE_0_25"
    if value <= 0.50:
        return "GT_0_25_LE_0_50"
    if value <= 1.00:
        return "GT_0_50_LE_1_00"
    return "GT_1_00"


def _target_bucket(value: float | None) -> str:
    if value is None:
        return "UNAVAILABLE"
    if value <= 0.50:
        return "LE_0_50"
    if value <= 1.00:
        return "GT_0_50_LE_1_00"
    if value <= 1.50:
        return "GT_1_00_LE_1_50"
    return "GT_1_50"


def _geometry(
    trade: TournamentTrade,
    *,
    gvz_lookup: _Asof,
) -> dict[str, Any]:
    row = gvz_lookup.row(trade.signal_at)
    if row is None:
        return {
            "gvz_close": None,
            "gvz_state": "UNAVAILABLE",
            "implied_1d_move": None,
            "stop_to_implied_1d": None,
            "target_to_implied_1d": None,
            "stop_bucket": "UNAVAILABLE",
            "target_bucket": "UNAVAILABLE",
        }

    gvz = _finite(row.get("gvz_close"))
    state = str(row.get("gvz_state") or "UNAVAILABLE")
    if state not in GVZ_STATES:
        state = "UNAVAILABLE"

    entry = float(trade.entry_price)
    implied_1d = (
        None
        if gvz is None or gvz <= 0.0 or entry <= 0.0
        else entry * (gvz / 100.0) / sqrt(252.0)
    )
    stop_distance = abs(entry - float(trade.stop_loss))
    target_distance = abs(float(trade.take_profit) - entry)
    stop_ratio = (
        None
        if implied_1d is None or implied_1d <= 0.0
        else stop_distance / implied_1d
    )
    target_ratio = (
        None
        if implied_1d is None or implied_1d <= 0.0
        else target_distance / implied_1d
    )
    return {
        "gvz_close": gvz,
        "gvz_state": state,
        "implied_1d_move": implied_1d,
        "stop_to_implied_1d": stop_ratio,
        "target_to_implied_1d": target_ratio,
        "stop_bucket": _stop_bucket(stop_ratio),
        "target_bucket": _target_bucket(target_ratio),
    }


def _payload(
    trades: Sequence[TournamentTrade],
    *,
    gvz_lookup: _Asof,
    trading_days: int,
) -> dict[str, Any]:
    state_groups: dict[str, list[TournamentTrade]] = defaultdict(list)
    stop_groups: dict[str, list[TournamentTrade]] = defaultdict(list)
    target_groups: dict[str, list[TournamentTrade]] = defaultdict(list)
    winner_stop: list[float] = []
    loser_stop: list[float] = []
    winner_target: list[float] = []
    loser_target: list[float] = []

    for trade in trades:
        row = _geometry(trade, gvz_lookup=gvz_lookup)
        state_groups[str(row["gvz_state"])].append(trade)
        stop_groups[str(row["stop_bucket"])].append(trade)
        target_groups[str(row["target_bucket"])].append(trade)
        is_winner = float(trade.net_r) > 0.0
        stop_ratio = row["stop_to_implied_1d"]
        target_ratio = row["target_to_implied_1d"]
        if stop_ratio is not None:
            (winner_stop if is_winner else loser_stop).append(float(stop_ratio))
        if target_ratio is not None:
            (winner_target if is_winner else loser_target).append(float(target_ratio))

    def mean(values: Sequence[float]) -> float | None:
        return None if not values else sum(values) / float(len(values))

    return {
        "all": _stats(tuple(trades), trading_days),
        "gvz_states": {
            state: _stats(tuple(state_groups.get(state, ())), trading_days)
            for state in GVZ_STATES
        },
        "stop_to_implied_1d": {
            bucket: _stats(tuple(stop_groups.get(bucket, ())), trading_days)
            for bucket in STOP_IV_BUCKETS
        },
        "target_to_implied_1d": {
            bucket: _stats(tuple(target_groups.get(bucket, ())), trading_days)
            for bucket in TARGET_IV_BUCKETS
        },
        "winner_loser_geometry": {
            "winner_mean_stop_to_implied_1d": mean(winner_stop),
            "loser_mean_stop_to_implied_1d": mean(loser_stop),
            "winner_mean_target_to_implied_1d": mean(winner_target),
            "loser_mean_target_to_implied_1d": mean(loser_target),
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


def evaluate_v75(
    bars: Sequence[Bar],
    *,
    gvz_rows: Sequence[tuple[datetime, float]],
    pip_size: float,
    cost_scenarios: Mapping[str, M15ResearchCosts],
) -> dict[str, Any]:
    price_rows = tuple(sorted(bars, key=lambda x: ensure_utc(x.timestamp)))
    if not price_rows:
        raise ValueError("V75_EMPTY_HISTORY")
    missing = [x for x in REQUIRED_COSTS if x not in cost_scenarios]
    if missing:
        raise ValueError(f"V75_MISSING_REQUIRED_COSTS:{missing}")

    gvz_context = build_gvz_context(gvz_rows)
    if gvz_context.empty:
        raise ValueError("V75_GVZ_EMPTY")
    gvz_lookup = _Asof(gvz_context)

    d1_context = build_secular_d1(price_rows)
    h1_context = build_h1_context(price_rows)
    full_dates = _trading_dates(
        price_rows,
        start=ensure_utc(price_rows[0].timestamp),
        end=FULL_END,
    )
    era_dates = _trading_dates(price_rows, start=FULL_START, end=FULL_END)
    era_days = len(era_dates)

    scenarios: dict[str, Any] = {}
    for cost_id in REQUIRED_COSTS:
        costs = cost_scenarios[cost_id]
        annotated = _family_streams(
            price_rows,
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
                gvz_lookup=gvz_lookup,
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
                gvz_lookup=gvz_lookup,
                trading_days=days,
            )

        scenarios[cost_id] = {
            "family_gates": family_gates,
            "satellite": _stats(satellite, era_days),
            "full_period": _payload(
                satellite,
                gvz_lookup=gvz_lookup,
                trading_days=era_days,
            ),
            "annual": annual,
            "diagnostic_windows": windows,
        }

    first_time = str(gvz_context.iloc[0]["time"])
    last_time = str(gvz_context.iloc[-1]["time"])
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
        "gvz_context": {
            "rows": len(gvz_context),
            "first_available_time": first_time,
            "last_available_time": last_time,
            "lookback_valid_closes": GVZ_LOOKBACK,
        },
        "preregistered_contract": {
            "base_route": FROZEN_ROUTE,
            "required_costs": list(REQUIRED_COSTS),
            "external_series": "CBOE Gold ETF Volatility Index / FRED GVZCLS",
            "external_series_use": "prior completed daily close only",
            "availability_rule": "daily close becomes available at 00:00 UTC next calendar day",
            "gvz_state_lookback_valid_closes": GVZ_LOOKBACK,
            "gvz_states": list(GVZ_STATES),
            "implied_move_formula": "entry_price * GVZ/100 / sqrt(252)",
            "stop_implied_move_buckets": list(STOP_IV_BUCKETS),
            "target_implied_move_buckets": list(TARGET_IV_BUCKETS),
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
            "V75 uses actual prior-completed daily implied volatility from GVZ as context and "
            "as an expected-move denominator. It does not modify the frozen V47 entry, SL, TP, "
            "sizing, or execution authority."
        ),
    }

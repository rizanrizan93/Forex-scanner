from __future__ import annotations

from collections import defaultdict
from datetime import datetime, time, timedelta, timezone
from math import isfinite, log, sqrt
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from .demo_donchian_adaptive_tournament import TournamentTrade, compute_metrics
from .models import Bar, ensure_utc
from .research_multisymbol_m15_breakout_v18 import (
    extract_signals as extract_m15_breakout,
    simulate as simulate_m15,
)
from .research_xau_hierarchical_regime_router_v35 import (
    L12_ID,
    L20_ID,
    _Asof,
    _direction_metrics,
    _max_losing_streak,
    _period,
)
from .research_xau_multihorizon_100usd_v20 import M15_VARIANTS
from .research_xau_m15_dual_strategy import M15ResearchCosts

RESEARCH_VERSION = "XAU_REALIZED_SKEW_STATE_V64"
ARTIFACT_CONTRACT = "XAU_REALIZED_SKEW_STATE_V64_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
PROMOTION_ELIGIBLE = False
DIAGNOSTIC_ONLY = True

PRIOR_DAYS_WINDOW = 120
SKEW_STATES = (
    "Q1_MOST_NEGATIVE",
    "Q2",
    "Q3",
    "Q4",
    "Q5_MOST_POSITIVE",
    "UNAVAILABLE",
)
FAMILY_IDS = {"L12": L12_ID, "L20": L20_ID}


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


def _realized_skew(returns: Sequence[float]) -> float | None:
    values = [float(x) for x in returns if isfinite(float(x))]
    n = len(values)
    if n < 8:
        return None
    rv = sum(x * x for x in values)
    if rv <= 0.0:
        return None
    return sqrt(float(n)) * sum(x ** 3 for x in values) / (rv ** 1.5)


def build_prior_day_skew_context(rows: Sequence[Bar]) -> pd.DataFrame:
    bars = tuple(sorted(rows, key=lambda x: ensure_utc(x.timestamp)))
    by_day: dict[Any, list[Bar]] = defaultdict(list)
    for bar in bars:
        by_day[ensure_utc(bar.timestamp).date()].append(bar)

    records: list[dict[str, Any]] = []
    for day in sorted(by_day):
        day_rows = sorted(by_day[day], key=lambda x: ensure_utc(x.timestamp))
        rets: list[float] = []
        previous_close: float | None = None
        for bar in day_rows:
            close = float(bar.close)
            if previous_close is not None and previous_close > 0.0 and close > 0.0:
                rets.append(log(close / previous_close))
            previous_close = close
        skew = _realized_skew(rets)
        rv = sum(x * x for x in rets) if rets else None
        records.append(
            {
                "source_day": day,
                "time": datetime.combine(
                    day + timedelta(days=1),
                    time.min,
                    tzinfo=timezone.utc,
                ),
                "realized_skew": np.nan if skew is None else float(skew),
                "realized_variance": np.nan if rv is None else float(rv),
                "intraday_returns": len(rets),
            }
        )

    frame = pd.DataFrame.from_records(records)
    if frame.empty:
        return frame
    prior = frame["realized_skew"].shift(1)
    rolling = prior.rolling(
        PRIOR_DAYS_WINDOW,
        min_periods=PRIOR_DAYS_WINDOW,
    )
    frame["q20"] = rolling.quantile(0.20)
    frame["q40"] = rolling.quantile(0.40)
    frame["q60"] = rolling.quantile(0.60)
    frame["q80"] = rolling.quantile(0.80)
    frame["prior_median"] = rolling.quantile(0.50)

    states: list[str] = []
    for _, row in frame.iterrows():
        values = [
            float(row.get("realized_skew", np.nan)),
            float(row.get("q20", np.nan)),
            float(row.get("q40", np.nan)),
            float(row.get("q60", np.nan)),
            float(row.get("q80", np.nan)),
        ]
        if not all(np.isfinite(x) for x in values):
            states.append("UNAVAILABLE")
            continue
        skew, q20, q40, q60, q80 = values
        if skew <= q20:
            states.append("Q1_MOST_NEGATIVE")
        elif skew <= q40:
            states.append("Q2")
        elif skew <= q60:
            states.append("Q3")
        elif skew <= q80:
            states.append("Q4")
        else:
            states.append("Q5_MOST_POSITIVE")
    frame["skew_state"] = states
    return frame


def _annotate(
    trades: Sequence[TournamentTrade],
    *,
    context: pd.DataFrame,
) -> tuple[tuple[TournamentTrade, str, float | None], ...]:
    if context.empty:
        return tuple((trade, "UNAVAILABLE", None) for trade in trades)
    lookup = _Asof(context)
    output: list[tuple[TournamentTrade, str, float | None]] = []
    for trade in trades:
        row = lookup.row(trade.signal_at)
        if row is None:
            output.append((trade, "UNAVAILABLE", None))
            continue
        state = str(row.get("skew_state") or "UNAVAILABLE")
        raw = float(row.get("realized_skew", np.nan))
        output.append(
            (
                trade,
                state if state in SKEW_STATES else "UNAVAILABLE",
                raw if np.isfinite(raw) else None,
            )
        )
    return tuple(output)


def _bucket_payload(
    trades: Sequence[TournamentTrade],
    *,
    context: pd.DataFrame,
    trading_days: int,
) -> dict[str, Any]:
    annotated = _annotate(trades, context=context)
    groups: dict[str, list[TournamentTrade]] = defaultdict(list)
    skews: dict[str, list[float]] = defaultdict(list)
    for trade, state, skew in annotated:
        groups[state].append(trade)
        if skew is not None:
            skews[state].append(float(skew))
    return {
        "all": _stats(tuple(trades), trading_days),
        "states": {
            state: {
                **_stats(tuple(groups.get(state, ())), trading_days),
                "mean_realized_skew": (
                    sum(skews[state]) / len(skews[state])
                    if skews.get(state) else None
                ),
            }
            for state in SKEW_STATES
        },
    }


def evaluate_v64(
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
        raise ValueError("V64_EMPTY_HISTORY")

    start = ensure_utc(era_start)
    end = ensure_utc(era_end)
    trading_dates = sorted(
        {
            ensure_utc(row.timestamp).date()
            for row in rows
            if start <= ensure_utc(row.timestamp) < end
        }
    )
    trading_days = len(trading_dates)
    context = build_prior_day_skew_context(rows)

    variants = {
        family: next(x for x in M15_VARIANTS if x.variant_id == variant_id)
        for family, variant_id in FAMILY_IDS.items()
    }
    signals = {
        family: extract_m15_breakout(rows, variant=variant)
        for family, variant in variants.items()
    }

    scenario_results: dict[str, Any] = {}
    for cost_id, costs in cost_scenarios.items():
        by_family: dict[str, tuple[TournamentTrade, ...]] = {}
        combined: list[TournamentTrade] = []
        for family in FAMILY_IDS:
            trades = simulate_m15(
                rows,
                signals=signals[family],
                costs=costs,
                pip_size=pip_size,
            )
            era_trades = _period(trades, start=start, end=end)
            by_family[family] = era_trades
            combined.extend(era_trades)

        combined = sorted(
            combined,
            key=lambda x: (
                ensure_utc(x.entry_at),
                str(x.strategy_id),
                str(x.direction),
            ),
        )
        scenario_results[cost_id] = {
            "families": {
                family: _bucket_payload(
                    trades,
                    context=context,
                    trading_days=trading_days,
                )
                for family, trades in by_family.items()
            },
            "combined": _bucket_payload(
                tuple(combined),
                context=context,
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
        "era_trading_days": trading_days,
        "preregistered_contract": {
            "realized_skew_formula": "sqrt(N)*sum(r_i^3)/(sum(r_i^2)^(3/2)); M15 log returns within prior completed UTC day",
            "minimum_intraday_returns_for_day": 8,
            "prior_days_window": PRIOR_DAYS_WINDOW,
            "state_definition": "quintiles of the most recently completed day's realized skew versus the prior-only 120 completed-day distribution",
            "states": list(SKEW_STATES),
            "entry_families": FAMILY_IDS,
            "entry_signal_logic_retuned": False,
            "trade_filter_applied": False,
            "skew_quintile_selected_as_winner": False,
            "threshold_grid_search": False,
            "selection_uses_future_outcomes": False,
            "execution_authority": False,
        },
        "scenario_results": scenario_results,
        "note": (
            "V64 is a realized-moment context diagnostic. It tests whether prior-day intraday "
            "gold skewness contains stable conditional information for the frozen L12/L20 "
            "families before any skewness-based filter or strategy is defined."
        ),
    }

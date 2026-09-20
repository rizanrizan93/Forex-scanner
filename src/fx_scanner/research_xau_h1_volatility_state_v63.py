from __future__ import annotations

from collections import defaultdict
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
    _resample_completed,
    _wilder_atr,
)
from .research_xau_multihorizon_100usd_v20 import M15_VARIANTS
from .research_xau_m15_dual_strategy import M15ResearchCosts

RESEARCH_VERSION = "XAU_H1_VOLATILITY_STATE_V63"
ARTIFACT_CONTRACT = "XAU_H1_VOLATILITY_STATE_V63_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
PROMOTION_ELIGIBLE = False
DIAGNOSTIC_ONLY = True

H1_ATR_PERIOD = 14
PRIOR_WINDOW_H1 = 120
VOL_STATES = ("Q1_LOW", "Q2", "Q3", "Q4", "Q5_HIGH", "UNAVAILABLE")
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


def build_h1_volatility_context(rows: Sequence[Bar]) -> pd.DataFrame:
    h1 = _resample_completed(rows, "1h").copy()
    h1["atr14"] = _wilder_atr(h1, H1_ATR_PERIOD)
    prior = h1["atr14"].shift(1)
    rolling = prior.rolling(PRIOR_WINDOW_H1, min_periods=PRIOR_WINDOW_H1)
    h1["q20"] = rolling.quantile(0.20)
    h1["q40"] = rolling.quantile(0.40)
    h1["q60"] = rolling.quantile(0.60)
    h1["q80"] = rolling.quantile(0.80)
    h1["prior_median"] = rolling.quantile(0.50)

    states: list[str] = []
    for _, row in h1.iterrows():
        values = [
            float(row.get("atr14", np.nan)),
            float(row.get("q20", np.nan)),
            float(row.get("q40", np.nan)),
            float(row.get("q60", np.nan)),
            float(row.get("q80", np.nan)),
        ]
        if not all(np.isfinite(x) for x in values):
            states.append("UNAVAILABLE")
            continue
        atr, q20, q40, q60, q80 = values
        if atr <= q20:
            states.append("Q1_LOW")
        elif atr <= q40:
            states.append("Q2")
        elif atr <= q60:
            states.append("Q3")
        elif atr <= q80:
            states.append("Q4")
        else:
            states.append("Q5_HIGH")
    h1["vol_state"] = states
    h1["atr_to_prior_median"] = (
        h1["atr14"] / h1["prior_median"].replace(0.0, np.nan)
    )
    return h1


def _annotate(
    trades: Sequence[TournamentTrade],
    *,
    context: pd.DataFrame,
) -> tuple[tuple[TournamentTrade, str, float | None], ...]:
    lookup = _Asof(context)
    output: list[tuple[TournamentTrade, str, float | None]] = []
    for trade in trades:
        row = lookup.row(trade.signal_at)
        if row is None:
            output.append((trade, "UNAVAILABLE", None))
            continue
        state = str(row.get("vol_state") or "UNAVAILABLE")
        ratio_raw = float(row.get("atr_to_prior_median", np.nan))
        ratio = ratio_raw if np.isfinite(ratio_raw) else None
        output.append((trade, state if state in VOL_STATES else "UNAVAILABLE", ratio))
    return tuple(output)


def _bucket_payload(
    trades: Sequence[TournamentTrade],
    *,
    context: pd.DataFrame,
    trading_days: int,
) -> dict[str, Any]:
    annotated = _annotate(trades, context=context)
    groups: dict[str, list[TournamentTrade]] = defaultdict(list)
    ratios: dict[str, list[float]] = defaultdict(list)
    for trade, state, ratio in annotated:
        groups[state].append(trade)
        if ratio is not None:
            ratios[state].append(float(ratio))
    return {
        "all": _stats(tuple(trades), trading_days),
        "states": {
            state: {
                **_stats(tuple(groups.get(state, ())), trading_days),
                "mean_atr_to_prior_median": (
                    sum(ratios[state]) / len(ratios[state])
                    if ratios.get(state) else None
                ),
            }
            for state in VOL_STATES
        },
    }


def evaluate_v63(
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
        raise ValueError("V63_EMPTY_HISTORY")

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
    context = build_h1_volatility_context(rows)

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
        for family, variant in variants.items():
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
            "h1_atr_period": H1_ATR_PERIOD,
            "prior_window_completed_h1_bars": PRIOR_WINDOW_H1,
            "state_definition": "causal quintiles of current completed-H1 ATR14 versus prior-only 120-H1 ATR14 distribution",
            "states": list(VOL_STATES),
            "entry_families": FAMILY_IDS,
            "entry_signal_logic_retuned": False,
            "trade_filter_applied": False,
            "quintile_selected_as_winner": False,
            "threshold_grid_search": False,
            "selection_uses_future_outcomes": False,
            "execution_authority": False,
        },
        "scenario_results": scenario_results,
        "note": (
            "V63 is a volatility-state diagnostic, not a squeeze strategy. It asks whether the "
            "frozen L12/L20 breakout families have stable conditional expectancy across causal "
            "pre-signal H1 ATR quintiles before any compression/expansion filter is defined."
        ),
    }

from __future__ import annotations

from collections import defaultdict
from math import isfinite
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

RESEARCH_VERSION = "XAU_H1_STRUCTURE_CONTEXT_V56"
ARTIFACT_CONTRACT = "XAU_H1_STRUCTURE_CONTEXT_V56_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
PROMOTION_ELIGIBLE = False
DIAGNOSTIC_ONLY = True

FROZEN_ROUTE = "SECULAR_BULL_REACCEL_LONG_COST10"
PIVOT_LEFT = 2
PIVOT_RIGHT = 2

STRUCTURE_STATES = (
    "BULL_HH_HL",
    "BEAR_LH_LL",
    "MIXED_OR_RANGE",
    "INSUFFICIENT",
)
BREAK_EVENTS = (
    "BULL_BOS",
    "BULL_MSS",
    "BEAR_BOS",
    "BEAR_MSS",
    "NONE",
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


def _structure_state(
    swing_highs: Sequence[tuple[Any, float]],
    swing_lows: Sequence[tuple[Any, float]],
) -> str:
    if len(swing_highs) < 2 or len(swing_lows) < 2:
        return "INSUFFICIENT"
    prev_h, last_h = float(swing_highs[-2][1]), float(swing_highs[-1][1])
    prev_l, last_l = float(swing_lows[-2][1]), float(swing_lows[-1][1])
    if last_h > prev_h and last_l > prev_l:
        return "BULL_HH_HL"
    if last_h < prev_h and last_l < prev_l:
        return "BEAR_LH_LL"
    return "MIXED_OR_RANGE"


def build_h1_structure_context(rows: Sequence[Bar]) -> pd.DataFrame:
    h1 = _resample_completed(rows, "1h").copy()
    if h1.empty:
        return h1

    highs = [float(x) for x in h1["high"]]
    lows = [float(x) for x in h1["low"]]
    closes = [float(x) for x in h1["close"]]
    times = list(h1["time"])

    swing_highs: list[tuple[Any, float]] = []
    swing_lows: list[tuple[Any, float]] = []

    states: list[str] = []
    last_breaks: list[str] = []
    bars_since_break: list[int | None] = []
    last_swing_highs: list[float] = []
    last_swing_lows: list[float] = []

    last_break_event = "NONE"
    last_break_index: int | None = None

    for i in range(len(h1)):
        # A pivot at i-PIVOT_RIGHT becomes knowable only now, after the
        # required right-side H1 bars are fully closed.
        pivot = i - PIVOT_RIGHT
        if pivot >= PIVOT_LEFT and pivot + PIVOT_RIGHT < len(h1):
            ph = highs[pivot]
            if (
                ph > max(highs[pivot - PIVOT_LEFT:pivot])
                and ph > max(highs[pivot + 1:pivot + 1 + PIVOT_RIGHT])
            ):
                swing_highs.append((times[pivot], ph))

            pl = lows[pivot]
            if (
                pl < min(lows[pivot - PIVOT_LEFT:pivot])
                and pl < min(lows[pivot + 1:pivot + 1 + PIVOT_RIGHT])
            ):
                swing_lows.append((times[pivot], pl))

        state_before_break = _structure_state(swing_highs, swing_lows)
        latest_high = float(swing_highs[-1][1]) if swing_highs else float("nan")
        latest_low = float(swing_lows[-1][1]) if swing_lows else float("nan")

        event = None
        if i > 0 and isfinite(latest_high):
            if closes[i - 1] <= latest_high and closes[i] > latest_high:
                event = (
                    "BULL_BOS"
                    if state_before_break == "BULL_HH_HL"
                    else "BULL_MSS"
                )
        if event is None and i > 0 and isfinite(latest_low):
            if closes[i - 1] >= latest_low and closes[i] < latest_low:
                event = (
                    "BEAR_BOS"
                    if state_before_break == "BEAR_LH_LL"
                    else "BEAR_MSS"
                )

        if event is not None:
            last_break_event = event
            last_break_index = i

        states.append(state_before_break)
        last_breaks.append(last_break_event)
        bars_since_break.append(
            None if last_break_index is None else i - last_break_index
        )
        last_swing_highs.append(latest_high)
        last_swing_lows.append(latest_low)

    h1["swing_structure_state"] = states
    h1["last_break_event"] = last_breaks
    h1["bars_since_last_break"] = bars_since_break
    h1["last_confirmed_swing_high"] = last_swing_highs
    h1["last_confirmed_swing_low"] = last_swing_lows
    return h1


def _annotate_trade_structure(
    trades: Sequence[TournamentTrade],
    *,
    structure_context: pd.DataFrame,
) -> tuple[tuple[TournamentTrade, dict[str, Any]], ...]:
    lookup = _Asof(structure_context)
    output: list[tuple[TournamentTrade, dict[str, Any]]] = []
    for trade in trades:
        row = lookup.row(trade.signal_at)
        if row is None:
            continue
        output.append(
            (
                trade,
                {
                    "structure_state": str(
                        row.get("swing_structure_state", "INSUFFICIENT")
                    ),
                    "last_break_event": str(row.get("last_break_event", "NONE")),
                    "bars_since_last_break": (
                        None
                        if row.get("bars_since_last_break") is None
                        or (
                            isinstance(row.get("bars_since_last_break"), float)
                            and np.isnan(float(row.get("bars_since_last_break")))
                        )
                        else int(row.get("bars_since_last_break"))
                    ),
                },
            )
        )
    return tuple(output)


def _bucketed(
    trades: Sequence[TournamentTrade],
    *,
    structure_context: pd.DataFrame,
    trading_days: int,
) -> dict[str, Any]:
    annotated = _annotate_trade_structure(
        trades,
        structure_context=structure_context,
    )
    output: dict[str, Any] = {
        "all": _stats(tuple(x[0] for x in annotated), trading_days),
        "structure_state": {},
        "last_break_event": {},
        "last_break_direction": {},
    }

    groups: dict[str, list[TournamentTrade]] = defaultdict(list)
    for trade, row in annotated:
        groups[str(row["structure_state"])].append(trade)
    output["structure_state"] = {
        key: _stats(tuple(values), trading_days)
        for key, values in sorted(groups.items())
    }

    groups = defaultdict(list)
    for trade, row in annotated:
        groups[str(row["last_break_event"])].append(trade)
    output["last_break_event"] = {
        key: _stats(tuple(values), trading_days)
        for key, values in sorted(groups.items())
    }

    groups = defaultdict(list)
    for trade, row in annotated:
        event = str(row["last_break_event"])
        direction = (
            "BULL_BREAK"
            if event.startswith("BULL_")
            else "BEAR_BREAK"
            if event.startswith("BEAR_")
            else "NONE"
        )
        groups[direction].append(trade)
    output["last_break_direction"] = {
        key: _stats(tuple(values), trading_days)
        for key, values in sorted(groups.items())
    }

    ages = [
        int(row["bars_since_last_break"])
        for _, row in annotated
        if row["bars_since_last_break"] is not None
    ]
    output["break_age_h1_bars"] = {
        "count": len(ages),
        "mean": (sum(ages) / len(ages)) if ages else None,
        "min": min(ages) if ages else None,
        "max": max(ages) if ages else None,
    }
    return output


def evaluate_v56(
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
        raise ValueError("V56_EMPTY_HISTORY")

    start = ensure_utc(era_start)
    end = ensure_utc(era_end)
    d1_context = build_secular_d1(rows)
    h1_context = build_h1_context(rows)
    structure_context = build_h1_structure_context(rows)

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
        combined: list[TournamentTrade] = []
        for family in FAMILY_MAP:
            candidate = _route_family_candidates(
                annotated_by_family[family],
                route=FROZEN_ROUTE,
            )
            gated, gate = gate_family_causally(
                candidate,
                trading_dates=full_dates,
            )
            era_gated = _period(gated, start=start, end=end)
            combined.extend(era_gated)
            families[family] = {
                "gate": gate,
                "structure": _bucketed(
                    era_gated,
                    structure_context=structure_context,
                    trading_days=trading_days,
                ),
            }

        combined = tuple(
            sorted(
                combined,
                key=lambda x: (ensure_utc(x.entry_at), str(x.strategy_id)),
            )
        )
        scenario_results[cost_id] = {
            "families": families,
            "combined_gated_satellite": _bucketed(
                combined,
                structure_context=structure_context,
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
            "frozen_route": FROZEN_ROUTE,
            "pivot_definition": {
                "timeframe": "H1_COMPLETED",
                "left_bars": PIVOT_LEFT,
                "right_bars": PIVOT_RIGHT,
                "confirmation_delay_h1_bars": PIVOT_RIGHT,
            },
            "bull_structure": "last two confirmed swing highs rise AND last two confirmed swing lows rise",
            "bear_structure": "last two confirmed swing highs fall AND last two confirmed swing lows fall",
            "bos_mss": (
                "H1 close crosses latest confirmed swing; BOS when prior confirmed structure "
                "already agrees with break direction, MSS otherwise"
            ),
            "trade_filter_applied": False,
            "ema_h1_permission_replaced": False,
            "signal_logic_retuned": False,
            "pivot_grid_search": False,
            "selection_uses_future_outcomes": False,
            "execution_authority": False,
        },
        "scenario_results": scenario_results,
        "note": (
            "V56 measures whether causally confirmed H1 HH/HL-LH/LL structure and the most "
            "recent BOS/MSS add information to the frozen V47/V48 satellite. It does not "
            "filter, resize, or alter entries, SL, or TP."
        ),
    }

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from math import sqrt
from typing import Any, Mapping, Sequence

from .demo_donchian_adaptive_tournament import TournamentTrade, compute_metrics
from .models import Bar, ensure_utc
from .research_xau_canonical_ict_context_v65 import _build_context_map, _signal_key
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
from .research_xau_v47_target_credibility_v74 import build_d1_range_context

RESEARCH_VERSION = "XAU_V47_SWEEP_TARGET_OVERLAP_V79"
ARTIFACT_CONTRACT = "XAU_V47_SWEEP_TARGET_OVERLAP_V79_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
PROMOTION_ELIGIBLE = False
DIAGNOSTIC_ONLY = True

FULL_START = datetime(2012, 1, 1, tzinfo=timezone.utc)
FULL_END = datetime(2026, 9, 20, tzinfo=timezone.utc)
FROZEN_ROUTE = "SECULAR_BULL_REACCEL_LONG_COST10"
REQUIRED_COSTS = ("LOW_1700", "V24_STRESS_4675")
TARGET_THRESHOLD = 0.75
CELLS = (
    "SWEEP_TARGET_GT",
    "SWEEP_TARGET_LE",
    "NONSWEEP_TARGET_GT",
    "NONSWEEP_TARGET_LE",
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
    out: list[TournamentTrade] = []
    for trade in sorted(
        trades,
        key=lambda x: (ensure_utc(x.signal_at), str(x.strategy_id)),
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
        out.append(trade)
    return tuple(out)


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None


def _cell(
    trade: TournamentTrade,
    *,
    ict_context: Mapping[tuple[str, Any, str], Mapping[str, Any]],
    d1_range_lookup: _Asof,
) -> tuple[str, float | None]:
    ict = ict_context.get(_signal_key(trade))
    d1 = d1_range_lookup.row(trade.signal_at)
    median60 = None if d1 is None else _finite(d1.get("range_median60"))
    target_distance = abs(float(trade.take_profit) - float(trade.entry_price))
    ratio = (
        None
        if median60 is None or median60 <= 0.0
        else target_distance / median60
    )
    if ict is None or ratio is None:
        return "UNAVAILABLE", ratio

    sweep = bool(ict.get("swept_liquidity"))
    target_gt = float(ratio) > TARGET_THRESHOLD
    if sweep and target_gt:
        return "SWEEP_TARGET_GT", ratio
    if sweep and not target_gt:
        return "SWEEP_TARGET_LE", ratio
    if not sweep and target_gt:
        return "NONSWEEP_TARGET_GT", ratio
    return "NONSWEEP_TARGET_LE", ratio


def _phi(counts: Mapping[str, int]) -> float | None:
    a = int(counts.get("SWEEP_TARGET_GT", 0))
    b = int(counts.get("SWEEP_TARGET_LE", 0))
    c = int(counts.get("NONSWEEP_TARGET_GT", 0))
    d = int(counts.get("NONSWEEP_TARGET_LE", 0))
    denom = sqrt(float((a + b) * (c + d) * (a + c) * (b + d)))
    if denom <= 0.0:
        return None
    return (a * d - b * c) / denom


def _payload(
    trades: Sequence[TournamentTrade],
    *,
    ict_context,
    d1_range_lookup: _Asof,
    trading_days: int,
) -> dict[str, Any]:
    groups: dict[str, list[TournamentTrade]] = defaultdict(list)
    ratios: dict[str, list[float]] = defaultdict(list)
    for trade in trades:
        cell, ratio = _cell(
            trade,
            ict_context=ict_context,
            d1_range_lookup=d1_range_lookup,
        )
        groups[cell].append(trade)
        if ratio is not None:
            ratios[cell].append(float(ratio))

    counts = {cell: len(groups.get(cell, ())) for cell in CELLS}
    known = sum(counts[cell] for cell in CELLS if cell != "UNAVAILABLE")
    target_gt = counts["SWEEP_TARGET_GT"] + counts["NONSWEEP_TARGET_GT"]
    sweep = counts["SWEEP_TARGET_GT"] + counts["SWEEP_TARGET_LE"]

    return {
        "all": _stats(tuple(trades), trading_days),
        "cells": {
            cell: {
                **_stats(tuple(groups.get(cell, ())), trading_days),
                "mean_target_to_prior60_d1_median": (
                    None
                    if not ratios.get(cell)
                    else sum(ratios[cell]) / len(ratios[cell])
                ),
            }
            for cell in CELLS
        },
        "association": {
            "known_trades": known,
            "sweep_count": sweep,
            "target_gt_count": target_gt,
            "sweep_rate": None if known <= 0 else sweep / float(known),
            "target_gt_rate": None if known <= 0 else target_gt / float(known),
            "target_gt_rate_given_sweep": (
                None if sweep <= 0 else counts["SWEEP_TARGET_GT"] / float(sweep)
            ),
            "target_gt_rate_given_nonsweep": (
                None
                if (known - sweep) <= 0
                else counts["NONSWEEP_TARGET_GT"] / float(known - sweep)
            ),
            "phi_sweep_vs_target_gt": _phi(counts),
        },
    }


def _slice(trades, *, start: datetime, end: datetime):
    return tuple(
        trade
        for trade in trades
        if start <= ensure_utc(trade.entry_at) < end
    )


def evaluate_v79(
    bars: Sequence[Bar],
    *,
    pip_size: float,
    cost_scenarios: Mapping[str, M15ResearchCosts],
) -> dict[str, Any]:
    rows = tuple(sorted(bars, key=lambda x: ensure_utc(x.timestamp)))
    if not rows:
        raise ValueError("V79_EMPTY_HISTORY")
    missing = [x for x in REQUIRED_COSTS if x not in cost_scenarios]
    if missing:
        raise ValueError(f"V79_MISSING_REQUIRED_COSTS:{missing}")

    d1_context = build_secular_d1(rows)
    h1_context = build_h1_context(rows)
    d1_range_context = build_d1_range_context(rows)
    d1_range_lookup = _Asof(d1_range_context)
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
        ict_context = _build_context_map(rows, satellite)

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
                ict_context=ict_context,
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
                ict_context=ict_context,
                d1_range_lookup=d1_range_lookup,
                trading_days=days,
            )

        scenarios[cost_id] = {
            "family_gates": family_gates,
            "satellite": _stats(satellite, era_days),
            "full_period": _payload(
                satellite,
                ict_context=ict_context,
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
            "sweep_definition": "canonical ICT_XAU_M15_EXECUTION_CONTEXT_V1 swept_liquidity presence",
            "target_definition": "unchanged V47 target distance / prior-60 completed-D1 median range",
            "target_threshold": TARGET_THRESHOLD,
            "purpose": "dependency and overlap audit only",
            "combined_filter_created": False,
            "cell_selected_as_winner": False,
            "trade_filter_applied": False,
            "threshold_grid_search": False,
            "selection_uses_future_outcomes": False,
            "execution_authority": False,
        },
        "scenarios": scenarios,
        "note": (
            "V79 quantifies dependence between the independently frozen V69 liquidity-sweep "
            "hypothesis and V77 target-credibility hypothesis. It does not combine them into "
            "a strategy or alter either prospective experiment."
        ),
    }

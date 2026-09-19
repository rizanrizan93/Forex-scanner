from __future__ import annotations

from collections import defaultdict
from typing import Any, Mapping, Sequence

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
    build_h1_context,
)
from .research_xau_multihorizon_100usd_v20 import _trading_dates
from .research_xau_m15_dual_strategy import M15ResearchCosts
from .research_xau_secular_regime_router_v46 import build_secular_d1

RESEARCH_VERSION = "XAU_ROUND_NUMBER_GEOMETRY_V55"
ARTIFACT_CONTRACT = "XAU_ROUND_NUMBER_GEOMETRY_V55_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
PROMOTION_ELIGIBLE = False
DIAGNOSTIC_ONLY = True

FROZEN_ROUTE = "SECULAR_BULL_REACCEL_LONG_COST10"
MAJOR_STEP = 100.0
MINOR_STEP = 10.0


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


def _next_level_above(price: float, step: float) -> float:
    import math
    quotient = price / step
    if abs(quotient - round(quotient)) < 1e-12:
        return price + step
    return math.ceil(quotient) * step


def _next_level_below(price: float, step: float) -> float:
    import math
    quotient = price / step
    if abs(quotient - round(quotient)) < 1e-12:
        return price - step
    return math.floor(quotient) * step


def _is_major(level: float) -> bool:
    return abs(level / MAJOR_STEP - round(level / MAJOR_STEP)) < 1e-12


def _barrier_geometry(trade: TournamentTrade) -> dict[str, Any]:
    direction = str(trade.direction).upper()
    if direction != "LONG":
        raise ValueError("V55_FROZEN_ROUTE_EXPECTS_LONG_ONLY")

    entry = float(trade.entry_price)
    stop = float(trade.stop_loss)
    target = float(trade.take_profit)
    risk = entry - stop
    if risk <= 0.0 or target <= entry:
        raise ValueError("V55_INVALID_LONG_GEOMETRY")

    one_r = entry + risk

    major_ahead = _next_level_above(entry, MAJOR_STEP)
    minor_ahead = _next_level_above(entry, MINOR_STEP)
    if _is_major(minor_ahead):
        minor_ahead += MINOR_STEP

    major_behind = _next_level_below(entry, MAJOR_STEP)
    minor_behind = _next_level_below(entry, MINOR_STEP)
    if _is_major(minor_behind):
        minor_behind -= MINOR_STEP

    major_before_1r = major_ahead <= one_r
    major_before_tp = major_ahead <= target
    minor_before_1r = minor_ahead <= one_r
    minor_before_tp = minor_ahead <= target

    major_between_stop_entry = stop <= major_behind < entry
    minor_between_stop_entry = stop <= minor_behind < entry

    major_target_bucket = (
        "MAJOR_BEFORE_1R"
        if major_before_1r
        else "MAJOR_AFTER_1R_BEFORE_TP"
        if major_before_tp
        else "NO_MAJOR_BEFORE_TP"
    )
    minor_target_bucket = (
        "MINOR_BEFORE_1R"
        if minor_before_1r
        else "MINOR_AFTER_1R_BEFORE_TP"
        if minor_before_tp
        else "NO_MINOR_BEFORE_TP"
    )
    major_stop_bucket = (
        "MAJOR_BETWEEN_ENTRY_STOP"
        if major_between_stop_entry
        else "NO_MAJOR_BETWEEN_ENTRY_STOP"
    )
    minor_stop_bucket = (
        "MINOR_BETWEEN_ENTRY_STOP"
        if minor_between_stop_entry
        else "NO_MINOR_BETWEEN_ENTRY_STOP"
    )

    return {
        "major_target_bucket": major_target_bucket,
        "minor_target_bucket": minor_target_bucket,
        "major_stop_bucket": major_stop_bucket,
        "minor_stop_bucket": minor_stop_bucket,
        "major_ahead_distance_r": (major_ahead - entry) / risk,
        "minor_ahead_distance_r": (minor_ahead - entry) / risk,
        "major_behind_distance_r": (entry - major_behind) / risk,
        "minor_behind_distance_r": (entry - minor_behind) / risk,
    }


def _bucketed(
    trades: Sequence[TournamentTrade],
    *,
    trading_days: int,
) -> dict[str, Any]:
    values = tuple(trades)
    annotations = tuple((trade, _barrier_geometry(trade)) for trade in values)

    output: dict[str, Any] = {
        "all": _stats(values, trading_days),
        "major_target": {},
        "minor_target": {},
        "major_stop": {},
        "minor_stop": {},
    }
    for key, out_key in (
        ("major_target_bucket", "major_target"),
        ("minor_target_bucket", "minor_target"),
        ("major_stop_bucket", "major_stop"),
        ("minor_stop_bucket", "minor_stop"),
    ):
        groups: dict[str, list[TournamentTrade]] = defaultdict(list)
        for trade, geo in annotations:
            groups[str(geo[key])].append(trade)
        output[out_key] = {
            group: _stats(tuple(group_trades), trading_days)
            for group, group_trades in sorted(groups.items())
        }

    if annotations:
        output["continuous_geometry"] = {
            "major_ahead_distance_r_mean": sum(
                float(geo["major_ahead_distance_r"]) for _, geo in annotations
            ) / len(annotations),
            "minor_ahead_distance_r_mean": sum(
                float(geo["minor_ahead_distance_r"]) for _, geo in annotations
            ) / len(annotations),
            "major_behind_distance_r_mean": sum(
                float(geo["major_behind_distance_r"]) for _, geo in annotations
            ) / len(annotations),
            "minor_behind_distance_r_mean": sum(
                float(geo["minor_behind_distance_r"]) for _, geo in annotations
            ) / len(annotations),
        }
    return output


def evaluate_v55(
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
        raise ValueError("V55_EMPTY_HISTORY")

    start = ensure_utc(era_start)
    end = ensure_utc(era_end)
    d1_context = build_secular_d1(rows)
    h1_context = build_h1_context(rows)
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
                "geometry": _bucketed(
                    era_gated,
                    trading_days=trading_days,
                ),
            }

        combined = sorted(
            combined,
            key=lambda x: (ensure_utc(x.entry_at), str(x.strategy_id)),
        )
        scenario_results[cost_id] = {
            "families": families,
            "combined_gated_satellite": _bucketed(
                tuple(combined),
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
            "frozen_entry_families": FAMILY_MAP,
            "major_barrier_usd": MAJOR_STEP,
            "minor_barrier_usd": MINOR_STEP,
            "minor_class_excludes_major_levels": True,
            "target_buckets": [
                "BARRIER_BEFORE_1R",
                "BARRIER_AFTER_1R_BEFORE_TP",
                "NO_BARRIER_BEFORE_TP",
            ],
            "stop_buckets": [
                "BARRIER_BETWEEN_ENTRY_STOP",
                "NO_BARRIER_BETWEEN_ENTRY_STOP",
            ],
            "trade_filter_applied": False,
            "target_or_stop_modified": False,
            "threshold_grid_search": False,
            "selection_uses_future_outcomes": False,
            "execution_authority": False,
        },
        "scenario_results": scenario_results,
        "note": (
            "V55 is a conditional geometry study on the already-frozen V47/V48 satellite. "
            "It does not reject or modify any trade. It tests whether round-number barriers "
            "in the TP path or between entry and SL are associated with materially different expectancy."
        ),
    }

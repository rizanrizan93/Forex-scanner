from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
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

RESEARCH_VERSION = "XAU_V47_HTF_LIQUIDITY_V84"
ARTIFACT_CONTRACT = "XAU_V47_HTF_LIQUIDITY_V84_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
PROMOTION_ELIGIBLE = False
DIAGNOSTIC_ONLY = True

FULL_START = datetime(2012, 1, 1, tzinfo=timezone.utc)
FULL_END = datetime(2026, 9, 20, tzinfo=timezone.utc)
FROZEN_ROUTE = "SECULAR_BULL_REACCEL_LONG_COST10"
REQUIRED_COSTS = ("LOW_1700", "V24_STRESS_4675")

HTF_STATES = (
    "NONE",
    "PREV_WEEK_LOW_RECLAIM",
    "PREV_MONTH_LOW_RECLAIM",
    "BOTH_RECLAIM",
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


def _week_key(stamp: datetime) -> tuple[int, int]:
    iso = ensure_utc(stamp).isocalendar()
    return int(iso.year), int(iso.week)


def _month_key(stamp: datetime) -> tuple[int, int]:
    value = ensure_utc(stamp)
    return value.year, value.month


def _period_maps(
    rows: Sequence[Bar],
) -> tuple[
    dict[tuple[int, int], float],
    dict[tuple[int, int], float],
    dict[tuple[int, int], int],
    dict[tuple[int, int], int],
    dict[tuple[int, int], tuple[int, int] | None],
    dict[tuple[int, int], tuple[int, int] | None],
]:
    week_lows: dict[tuple[int, int], float] = {}
    month_lows: dict[tuple[int, int], float] = {}
    week_first_index: dict[tuple[int, int], int] = {}
    month_first_index: dict[tuple[int, int], int] = {}

    for index, row in enumerate(rows):
        stamp = ensure_utc(row.timestamp)
        wk = _week_key(stamp)
        mk = _month_key(stamp)
        week_first_index.setdefault(wk, index)
        month_first_index.setdefault(mk, index)
        week_lows[wk] = min(week_lows.get(wk, float("inf")), float(row.low))
        month_lows[mk] = min(month_lows.get(mk, float("inf")), float(row.low))

    weeks = sorted(week_lows)
    months = sorted(month_lows)
    prev_week = {
        key: (None if i == 0 else weeks[i - 1])
        for i, key in enumerate(weeks)
    }
    prev_month = {
        key: (None if i == 0 else months[i - 1])
        for i, key in enumerate(months)
    }
    return (
        week_lows,
        month_lows,
        week_first_index,
        month_first_index,
        prev_week,
        prev_month,
    )


def _trade_context(
    rows: Sequence[Bar],
    trade: TournamentTrade,
    *,
    week_lows: Mapping[tuple[int, int], float],
    month_lows: Mapping[tuple[int, int], float],
    week_first_index: Mapping[tuple[int, int], int],
    month_first_index: Mapping[tuple[int, int], int],
    prev_week: Mapping[tuple[int, int], tuple[int, int] | None],
    prev_month: Mapping[tuple[int, int], tuple[int, int] | None],
) -> dict[str, Any]:
    index = int(trade.signal_index)
    if index < 0 or index >= len(rows):
        return {"state": "UNAVAILABLE"}

    signal_bar = rows[index]
    signal_at = ensure_utc(signal_bar.timestamp)
    wk = _week_key(signal_at)
    mk = _month_key(signal_at)
    prev_wk = prev_week.get(wk)
    prev_mk = prev_month.get(mk)
    if prev_wk is None or prev_mk is None:
        return {"state": "UNAVAILABLE"}

    previous_week_low = float(week_lows[prev_wk])
    previous_month_low = float(month_lows[prev_mk])

    week_start = int(week_first_index[wk])
    month_start = int(month_first_index[mk])
    current_week_rows = rows[week_start:index + 1]
    current_month_rows = rows[month_start:index + 1]
    if not current_week_rows or not current_month_rows:
        return {"state": "UNAVAILABLE"}

    current_week_min = min(float(row.low) for row in current_week_rows)
    current_month_min = min(float(row.low) for row in current_month_rows)
    signal_close = float(signal_bar.close)

    week_breached = current_week_min < previous_week_low
    month_breached = current_month_min < previous_month_low
    week_reclaimed = bool(week_breached and signal_close > previous_week_low)
    month_reclaimed = bool(month_breached and signal_close > previous_month_low)

    week_same_bar_sweep = any(
        float(row.low) < previous_week_low and float(row.close) > previous_week_low
        for row in current_week_rows
    )
    month_same_bar_sweep = any(
        float(row.low) < previous_month_low and float(row.close) > previous_month_low
        for row in current_month_rows
    )

    if week_reclaimed and month_reclaimed:
        state = "BOTH_RECLAIM"
    elif week_reclaimed:
        state = "PREV_WEEK_LOW_RECLAIM"
    elif month_reclaimed:
        state = "PREV_MONTH_LOW_RECLAIM"
    else:
        state = "NONE"

    return {
        "state": state,
        "previous_week_low": previous_week_low,
        "previous_month_low": previous_month_low,
        "week_breached": week_breached,
        "month_breached": month_breached,
        "week_reclaimed": week_reclaimed,
        "month_reclaimed": month_reclaimed,
        "week_same_bar_sweep_seen": week_same_bar_sweep,
        "month_same_bar_sweep_seen": month_same_bar_sweep,
        "signal_close_above_previous_week_low": signal_close > previous_week_low,
        "signal_close_above_previous_month_low": signal_close > previous_month_low,
    }


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
    context_map: Mapping[tuple[Any, ...], Mapping[str, Any]],
    trading_days: int,
) -> dict[str, Any]:
    state_groups: dict[str, list[TournamentTrade]] = defaultdict(list)
    bool_groups: dict[str, dict[bool, list[TournamentTrade]]] = {
        "week_reclaimed": {True: [], False: []},
        "month_reclaimed": {True: [], False: []},
        "week_same_bar_sweep_seen": {True: [], False: []},
        "month_same_bar_sweep_seen": {True: [], False: []},
    }

    for trade in trades:
        ctx = context_map.get(_trade_key(trade), {"state": "UNAVAILABLE"})
        state = str(ctx.get("state") or "UNAVAILABLE")
        if state not in HTF_STATES:
            state = "UNAVAILABLE"
        state_groups[state].append(trade)

        for feature in bool_groups:
            value = bool(ctx.get(feature, False))
            bool_groups[feature][value].append(trade)

    return {
        "all": _stats(tuple(trades), trading_days),
        "states": {
            state: _stats(tuple(state_groups.get(state, ())), trading_days)
            for state in HTF_STATES
        },
        "boolean_features": {
            feature: {
                "TRUE": _stats(tuple(groups[True]), trading_days),
                "FALSE": _stats(tuple(groups[False]), trading_days),
            }
            for feature, groups in bool_groups.items()
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


def evaluate_v84(
    bars: Sequence[Bar],
    *,
    pip_size: float,
    cost_scenarios: Mapping[str, M15ResearchCosts],
) -> dict[str, Any]:
    rows = tuple(sorted(bars, key=lambda x: ensure_utc(x.timestamp)))
    if not rows:
        raise ValueError("V84_EMPTY_HISTORY")
    missing = [x for x in REQUIRED_COSTS if x not in cost_scenarios]
    if missing:
        raise ValueError(f"V84_MISSING_REQUIRED_COSTS:{missing}")

    (
        week_lows,
        month_lows,
        week_first_index,
        month_first_index,
        prev_week,
        prev_month,
    ) = _period_maps(rows)

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
        context_map = {
            _trade_key(trade): _trade_context(
                rows,
                trade,
                week_lows=week_lows,
                month_lows=month_lows,
                week_first_index=week_first_index,
                month_first_index=month_first_index,
                prev_week=prev_week,
                prev_month=prev_month,
            )
            for trade in satellite
        }

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
                context_map=context_map,
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
                context_map=context_map,
                trading_days=days,
            )

        scenarios[cost_id] = {
            "family_gates": family_gates,
            "satellite": _stats(satellite, era_days),
            "full_period": _payload(
                satellite,
                context_map=context_map,
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
            "weekly_reference": "immediately prior completed ISO week low",
            "monthly_reference": "immediately prior completed UTC calendar month low",
            "reclaim_definition": "current period traded below prior-period low AND signal M15 close is back above that low",
            "same_bar_sweep_definition": "any completed M15 bar in current period has low below prior-period low and closes above it",
            "states": list(HTF_STATES),
            "numeric_thresholds_added": False,
            "trade_filter_applied": False,
            "state_selected_as_winner": False,
            "v69_forward_contract_changed": False,
            "selection_uses_future_outcomes": False,
            "execution_authority": False,
        },
        "scenarios": scenarios,
        "note": (
            "V84 tests higher-timeframe sell-side liquidity sweeps/reclaims at prior-week and "
            "prior-month lows as context for the frozen long-only V47 satellite. It is diagnostic "
            "only and does not alter any trade or the active V69/V77 forward experiments."
        ),
    }

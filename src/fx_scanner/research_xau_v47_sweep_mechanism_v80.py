from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Sequence

from .demo_donchian_adaptive_tournament import TournamentTrade, compute_metrics
from .demo_xau_m15_ict_layer import (
    DISPLACEMENT_BODY_ATR,
    LIQUIDITY_SWEEP_LOOKBACK,
    _completed_rows,
    evaluate_ict_execution_context,
)
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

RESEARCH_VERSION = "XAU_V47_SWEEP_MECHANISM_V80"
ARTIFACT_CONTRACT = "XAU_V47_SWEEP_MECHANISM_V80_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
PROMOTION_ELIGIBLE = False
DIAGNOSTIC_ONLY = True

FULL_START = datetime(2012, 1, 1, tzinfo=timezone.utc)
FULL_END = datetime(2026, 9, 20, tzinfo=timezone.utc)
FROZEN_ROUTE = "SECULAR_BULL_REACCEL_LONG_COST10"
REQUIRED_COSTS = ("LOW_1700", "V24_STRESS_4675")
CONTEXT_WINDOW_M15 = 700

SEQUENCE_STATES = (
    "NO_SWEEP",
    "SWEEP_NO_POST_DISPLACEMENT",
    "SWEEP_POST_DISPLACEMENT_NO_FVG",
    "SWEEP_POST_DISPLACEMENT_FVG",
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


def _levels_from_context(context, direction: str) -> dict[str, float | None]:
    if direction == "LONG":
        return {
            "PDL": context.previous_day_low,
            "ASIA_LOW": context.asian_low,
            "LONDON_LOW": context.london_low,
            "NEW_YORK_LOW": context.new_york_low,
        }
    return {
        "PDH": context.previous_day_high,
        "ASIA_HIGH": context.asian_high,
        "LONDON_HIGH": context.london_high,
        "NEW_YORK_HIGH": context.new_york_high,
    }


def _is_directional_displacement(bar: Bar, *, direction: str, atr_value: float) -> bool:
    body = abs(float(bar.close) - float(bar.open))
    candle_range = max(float(bar.high) - float(bar.low), 1e-12)
    if direction == "LONG":
        close_location = (float(bar.close) - float(bar.low)) / candle_range
        directional = float(bar.close) > float(bar.open) and close_location >= 0.70
    else:
        close_location = (float(bar.high) - float(bar.close)) / candle_range
        directional = float(bar.close) < float(bar.open) and close_location >= 0.70
    return directional and body >= DISPLACEMENT_BODY_ATR * float(atr_value)


def _latest_sweep_index(
    rows: Sequence[Bar],
    *,
    direction: str,
    levels: Mapping[str, float | None],
) -> tuple[int | None, tuple[str, ...]]:
    start = max(0, len(rows) - LIQUIDITY_SWEEP_LOOKBACK)
    latest: int | None = None
    latest_names: list[str] = []
    for index in range(start, len(rows)):
        row = rows[index]
        names: list[str] = []
        for name, value in levels.items():
            if value is None:
                continue
            level = float(value)
            swept = (
                float(row.low) < level and float(row.close) > level
                if direction == "LONG"
                else float(row.high) > level and float(row.close) < level
            )
            if swept:
                names.append(name)
        if names:
            latest = index
            latest_names = names
    return latest, tuple(sorted(set(latest_names)))


def _post_sweep_displacement_index(
    rows: Sequence[Bar],
    *,
    sweep_index: int,
    direction: str,
    atr_value: float,
) -> int | None:
    latest: int | None = None
    for index in range(sweep_index, len(rows)):
        if _is_directional_displacement(
            rows[index],
            direction=direction,
            atr_value=atr_value,
        ):
            latest = index
    return latest


def _fvg_created_after(
    rows: Sequence[Bar],
    *,
    start_index: int,
    direction: str,
) -> bool:
    for index in range(max(2, start_index), len(rows)):
        left = rows[index - 2]
        current = rows[index]
        if direction == "LONG" and float(current.low) > float(left.high):
            return True
        if direction == "SHORT" and float(current.high) < float(left.low):
            return True
    return False


def _sequence_context(
    rows: Sequence[Bar],
    trade: TournamentTrade,
) -> dict[str, Any]:
    signal_at = ensure_utc(trade.signal_at)
    as_of = signal_at + timedelta(minutes=15)
    start = max(0, int(trade.signal_index) - CONTEXT_WINDOW_M15 + 1)
    end = min(len(rows), int(trade.signal_index) + 1)
    window = tuple(rows[start:end])
    if not window:
        return {
            "state": "UNAVAILABLE",
            "sweep_sources": (),
            "sweep_at": None,
            "displacement_at": None,
            "post_sweep_fvg_created": False,
        }

    direction = str(trade.direction).upper()
    context = evaluate_ict_execution_context(
        window,
        direction=direction,
        atr_value=float(trade.atr_at_signal),
        as_of=as_of,
    )
    completed = _completed_rows(window, as_of=as_of)
    if not context.available or not completed:
        return {
            "state": "UNAVAILABLE",
            "sweep_sources": (),
            "sweep_at": None,
            "displacement_at": None,
            "post_sweep_fvg_created": False,
        }

    levels = _levels_from_context(context, direction)
    sweep_index, sweep_sources = _latest_sweep_index(
        completed,
        direction=direction,
        levels=levels,
    )
    if sweep_index is None:
        return {
            "state": "NO_SWEEP",
            "sweep_sources": (),
            "sweep_at": None,
            "displacement_at": None,
            "post_sweep_fvg_created": False,
        }

    displacement_index = _post_sweep_displacement_index(
        completed,
        sweep_index=sweep_index,
        direction=direction,
        atr_value=float(trade.atr_at_signal),
    )
    if displacement_index is None:
        return {
            "state": "SWEEP_NO_POST_DISPLACEMENT",
            "sweep_sources": sweep_sources,
            "sweep_at": ensure_utc(completed[sweep_index].timestamp).isoformat(),
            "displacement_at": None,
            "post_sweep_fvg_created": False,
        }

    fvg_created = _fvg_created_after(
        completed,
        start_index=displacement_index,
        direction=direction,
    )
    state = (
        "SWEEP_POST_DISPLACEMENT_FVG"
        if fvg_created
        else "SWEEP_POST_DISPLACEMENT_NO_FVG"
    )
    return {
        "state": state,
        "sweep_sources": sweep_sources,
        "sweep_at": ensure_utc(completed[sweep_index].timestamp).isoformat(),
        "displacement_at": ensure_utc(completed[displacement_index].timestamp).isoformat(),
        "post_sweep_fvg_created": bool(fvg_created),
    }


def _payload(
    trades: Sequence[TournamentTrade],
    *,
    rows: Sequence[Bar],
    trading_days: int,
) -> dict[str, Any]:
    groups: dict[str, list[TournamentTrade]] = defaultdict(list)
    source_groups: dict[str, list[TournamentTrade]] = defaultdict(list)
    sweep_any: list[TournamentTrade] = []
    sweep_post_disp: list[TournamentTrade] = []

    for trade in trades:
        ctx = _sequence_context(rows, trade)
        state = str(ctx["state"])
        if state not in SEQUENCE_STATES:
            state = "UNAVAILABLE"
        groups[state].append(trade)

        sources = tuple(ctx.get("sweep_sources") or ())
        for source in sources:
            source_groups[str(source)].append(trade)

        if state.startswith("SWEEP_"):
            sweep_any.append(trade)
        if state in {
            "SWEEP_POST_DISPLACEMENT_NO_FVG",
            "SWEEP_POST_DISPLACEMENT_FVG",
        }:
            sweep_post_disp.append(trade)

    return {
        "all": _stats(tuple(trades), trading_days),
        "states": {
            state: _stats(tuple(groups.get(state, ())), trading_days)
            for state in SEQUENCE_STATES
        },
        "sweep_any": _stats(tuple(sweep_any), trading_days),
        "sweep_post_displacement": _stats(tuple(sweep_post_disp), trading_days),
        "sweep_sources": {
            source: _stats(tuple(values), trading_days)
            for source, values in sorted(source_groups.items())
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


def evaluate_v80(
    bars: Sequence[Bar],
    *,
    pip_size: float,
    cost_scenarios: Mapping[str, M15ResearchCosts],
) -> dict[str, Any]:
    rows = tuple(sorted(bars, key=lambda x: ensure_utc(x.timestamp)))
    if not rows:
        raise ValueError("V80_EMPTY_HISTORY")
    missing = [x for x in REQUIRED_COSTS if x not in cost_scenarios]
    if missing:
        raise ValueError(f"V80_MISSING_REQUIRED_COSTS:{missing}")

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
                rows=rows,
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
                rows=rows,
                trading_days=days,
            )

        scenarios[cost_id] = {
            "family_gates": family_gates,
            "satellite": _stats(satellite, era_days),
            "full_period": _payload(
                satellite,
                rows=rows,
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
            "canonical_sweep_lookback_m15": LIQUIDITY_SWEEP_LOOKBACK,
            "canonical_displacement_body_atr": DISPLACEMENT_BODY_ATR,
            "displacement_close_location_min": 0.70,
            "sequence_states": list(SEQUENCE_STATES),
            "post_sweep_fvg_definition": "same frozen three-candle directional FVG geometry after latest sweep and displacement",
            "entry_changed": False,
            "stop_changed": False,
            "target_changed": False,
            "v69_forward_contract_changed": False,
            "trade_filter_applied": False,
            "sequence_state_selected_as_winner": False,
            "threshold_grid_search": False,
            "selection_uses_future_outcomes": False,
            "execution_authority": False,
        },
        "scenarios": scenarios,
        "note": (
            "V80 is a mechanism audit for the already-frozen V69 sweep hypothesis. It asks whether "
            "historical sweep expectancy is associated with a subsequent canonical M15 displacement "
            "and FVG creation before the V47 signal. It cannot change the V69 forward experiment."
        ),
    }

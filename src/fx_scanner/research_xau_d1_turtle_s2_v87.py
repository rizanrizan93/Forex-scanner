from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from .demo_donchian_adaptive_tournament import TournamentTrade, compute_metrics
from .models import Bar, ensure_utc
from .research_xau_hierarchical_regime_router_v35 import (
    _Asof,
    _direction_metrics,
    _max_losing_streak,
    _period,
    _resample_completed,
    _wilder_atr,
)
from .research_xau_m15_dual_strategy import M15ResearchCosts
from .research_xau_multihorizon_100usd_v20 import _trading_dates

RESEARCH_VERSION = "XAU_D1_TURTLE_S2_V87"
ARTIFACT_CONTRACT = "XAU_D1_TURTLE_S2_V87_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
PROMOTION_ELIGIBLE = False
DIAGNOSTIC_ONLY = True

ENTRY_DAYS = 55
EXIT_DAYS = 20
N_DAYS = 20
INITIAL_STOP_N = 2.0
PIP_SIZE = 0.01
STRATEGY_ID = "V87_D1_TURTLE_S2_SINGLE_UNIT_55_20_2N"


@dataclass(slots=True)
class _Active:
    direction: int
    signal_at: Any
    entry_at: Any
    entry_index: int
    entry_price: float
    n_value: float
    risk_price: float
    initial_stop: float


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


def build_daily_turtle_context(rows: Sequence[Bar]) -> pd.DataFrame:
    d1 = _resample_completed(rows, "1D").copy()
    d1["n20"] = _wilder_atr(d1, N_DAYS)
    d1["entry_high55"] = d1["high"].rolling(
        ENTRY_DAYS,
        min_periods=ENTRY_DAYS,
    ).max()
    d1["entry_low55"] = d1["low"].rolling(
        ENTRY_DAYS,
        min_periods=ENTRY_DAYS,
    ).min()
    d1["exit_low20"] = d1["low"].rolling(
        EXIT_DAYS,
        min_periods=EXIT_DAYS,
    ).min()
    d1["exit_high20"] = d1["high"].rolling(
        EXIT_DAYS,
        min_periods=EXIT_DAYS,
    ).max()
    return d1


def _cost_r(
    *,
    risk_pips: float,
    entry_at,
    exit_at,
    costs: M15ResearchCosts,
) -> float:
    if risk_pips <= 0.0:
        raise ValueError("V87_INVALID_RISK_PIPS")
    elapsed_days = max(
        0.0,
        (ensure_utc(exit_at) - ensure_utc(entry_at)).total_seconds() / 86400.0,
    )
    total_pips = (
        float(costs.spread_pips) * float(costs.spread_multiplier)
        + float(costs.slippage_pips) * float(costs.slippage_multiplier)
        + float(costs.commission_pips_round_trip)
        + float(costs.swap_pips_per_day) * elapsed_days
    )
    return total_pips / risk_pips


def _finite_row(row: Mapping[str, Any] | None) -> bool:
    if row is None:
        return False
    keys = (
        "n20",
        "entry_high55",
        "entry_low55",
        "exit_low20",
        "exit_high20",
    )
    try:
        return all(isfinite(float(row.get(key))) for key in keys)
    except (TypeError, ValueError):
        return False


def _exit_trade(
    *,
    active: _Active,
    exit_at,
    exit_index: int,
    exit_price: float,
    costs: M15ResearchCosts,
    reason: str,
) -> TournamentTrade:
    direction = int(active.direction)
    gross_r = direction * (float(exit_price) - float(active.entry_price)) / float(
        active.risk_price
    )
    cost_r = _cost_r(
        risk_pips=float(active.risk_price) / PIP_SIZE,
        entry_at=active.entry_at,
        exit_at=exit_at,
        costs=costs,
    )
    return TournamentTrade(
        STRATEGY_ID,
        "XAUUSD",
        "LONG" if direction > 0 else "SHORT",
        active.signal_at,
        active.entry_at,
        ensure_utc(exit_at),
        active.entry_index,
        int(exit_index),
        float(active.entry_price),
        float(exit_price),
        float(active.n_value),
        float(active.initial_stop),
        float("nan"),
        float(gross_r),
        float(cost_r),
        float(gross_r - cost_r),
        int(exit_index - active.entry_index),
        str(reason),
    )


def simulate_v87(
    rows: Sequence[Bar],
    *,
    costs: M15ResearchCosts,
) -> tuple[TournamentTrade, ...]:
    bars = tuple(sorted(rows, key=lambda x: ensure_utc(x.timestamp)))
    if not bars:
        return ()
    daily = build_daily_turtle_context(bars)
    lookup = _Asof(daily)

    active: _Active | None = None
    output: list[TournamentTrade] = []

    for i, bar in enumerate(bars):
        stamp = ensure_utc(bar.timestamp)
        context = lookup.row(stamp)
        if not _finite_row(context):
            continue
        assert context is not None

        # Existing position is managed first. The 20-day opposite channel is a
        # trailing exit and can supersede the original 2N protective stop.
        if active is not None:
            if active.direction > 0:
                channel = float(context["exit_low20"])
                protective = max(float(active.initial_stop), channel)
                if float(bar.low) <= protective:
                    fill = (
                        float(bar.open)
                        if float(bar.open) < protective
                        else protective
                    )
                    reason = (
                        "INITIAL_2N_STOP"
                        if protective <= float(active.initial_stop) + 1e-12
                        else "DONCHIAN_20D_EXIT"
                    )
                    output.append(
                        _exit_trade(
                            active=active,
                            exit_at=stamp,
                            exit_index=i,
                            exit_price=fill,
                            costs=costs,
                            reason=reason,
                        )
                    )
                    active = None
                    # Never re-enter on the same M15 bar after an exit because
                    # intrabar ordering is unknowable from OHLC.
                    continue
            else:
                channel = float(context["exit_high20"])
                protective = min(float(active.initial_stop), channel)
                if float(bar.high) >= protective:
                    fill = (
                        float(bar.open)
                        if float(bar.open) > protective
                        else protective
                    )
                    reason = (
                        "INITIAL_2N_STOP"
                        if protective >= float(active.initial_stop) - 1e-12
                        else "DONCHIAN_20D_EXIT"
                    )
                    output.append(
                        _exit_trade(
                            active=active,
                            exit_at=stamp,
                            exit_index=i,
                            exit_price=fill,
                            costs=costs,
                            reason=reason,
                        )
                    )
                    active = None
                    continue

        if active is not None:
            continue

        upper = float(context["entry_high55"])
        lower = float(context["entry_low55"])
        n_value = float(context["n20"])
        if n_value <= 0.0:
            continue

        long_trigger = float(bar.high) >= upper
        short_trigger = float(bar.low) <= lower

        # A bar crossing both 55-day channels is path-ambiguous. Skip rather
        # than inventing which stop order filled first.
        if long_trigger and short_trigger:
            continue
        if not long_trigger and not short_trigger:
            continue

        if long_trigger:
            direction = 1
            entry = max(float(bar.open), upper)
            stop = entry - INITIAL_STOP_N * n_value
        else:
            direction = -1
            entry = min(float(bar.open), lower)
            stop = entry + INITIAL_STOP_N * n_value

        risk = INITIAL_STOP_N * n_value
        if not isfinite(entry) or not isfinite(stop) or risk <= 0.0:
            continue

        new_active = _Active(
            direction=direction,
            signal_at=stamp,
            entry_at=stamp,
            entry_index=i,
            entry_price=entry,
            n_value=n_value,
            risk_price=risk,
            initial_stop=stop,
        )

        # Conservative entry-bar handling: if OHLC also spans the initial stop,
        # count the stop. The low/high may have occurred before entry, but this
        # avoids granting favourable unknown intrabar ordering.
        entry_bar_stop = (
            float(bar.low) <= stop
            if direction > 0
            else float(bar.high) >= stop
        )
        if entry_bar_stop:
            output.append(
                _exit_trade(
                    active=new_active,
                    exit_at=stamp,
                    exit_index=i,
                    exit_price=stop,
                    costs=costs,
                    reason="ENTRY_BAR_2N_STOP_AMBIGUOUS",
                )
            )
            continue

        active = new_active

    if active is not None:
        last_index = len(bars) - 1
        last = bars[last_index]
        output.append(
            _exit_trade(
                active=active,
                exit_at=ensure_utc(last.timestamp),
                exit_index=last_index,
                exit_price=float(last.close),
                costs=costs,
                reason="DATA_END_MARK_TO_MARKET",
            )
        )

    return tuple(output)


def evaluate_v87(
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
        raise ValueError("V87_EMPTY_HISTORY")
    if abs(float(pip_size) - PIP_SIZE) > 1e-12:
        raise ValueError("V87_REQUIRES_XAU_PIP_SIZE_001")

    start = ensure_utc(era_start)
    end = ensure_utc(era_end)
    dates = _trading_dates(rows, start=start, end=end)
    days = len(dates)

    scenarios: dict[str, Any] = {}
    for cost_id, costs in cost_scenarios.items():
        trades = _period(
            simulate_v87(rows, costs=costs),
            start=start,
            end=end,
        )
        scenarios[cost_id] = {
            "all": _stats(trades, days),
            "long": _stats(
                tuple(x for x in trades if str(x.direction).upper() == "LONG"),
                days,
            ),
            "short": _stats(
                tuple(x for x in trades if str(x.direction).upper() == "SHORT"),
                days,
            ),
            "exit_reasons": {
                reason: sum(1 for x in trades if str(x.exit_reason) == reason)
                for reason in (
                    "INITIAL_2N_STOP",
                    "ENTRY_BAR_2N_STOP_AMBIGUOUS",
                    "DONCHIAN_20D_EXIT",
                    "DATA_END_MARK_TO_MARKET",
                )
            },
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
        "era_trading_days": days,
        "preregistered_contract": {
            "family": "Turtle System 2 inspired single-unit control",
            "entry_channel_days": ENTRY_DAYS,
            "exit_channel_days": EXIT_DAYS,
            "n_atr_days": N_DAYS,
            "initial_stop_n": INITIAL_STOP_N,
            "direction": "symmetric long and short",
            "entry": "intraday first cross of channel derived only from completed prior daily bars",
            "gap_fill_rule": "fill at M15 open when already beyond breakout channel, otherwise channel level",
            "exit": "20-day opposite channel or fixed initial 2N stop, whichever is closer/protective",
            "pyramiding": False,
            "volatility_position_sizing": False,
            "one_active_unit_max": True,
            "same_bar_dual_channel_cross": "SKIP_AMBIGUOUS",
            "entry_bar_stop": "CONSERVATIVE_STOP_IF_OHLC_SPANS_STOP",
            "fixed_profit_target": False,
            "parameter_grid_search": False,
            "selection_uses_future_outcomes": False,
            "execution_authority": False,
        },
        "scenario_results": scenarios,
        "note": (
            "V87 is not claimed as an exact reproduction of the original Turtle portfolio. "
            "It is a single-unit XAU control preserving the canonical System-2 55-day breakout, "
            "20-day opposite-channel exit and 2N initial stop, while omitting pyramiding and "
            "portfolio volatility sizing so standalone XAU trade expectancy can be measured."
        ),
    }

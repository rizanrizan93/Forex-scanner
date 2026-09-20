from __future__ import annotations

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
from .research_xau_secular_regime_router_v46 import COST_R_CAP, build_secular_d1

RESEARCH_VERSION = "XAU_H4_PULLBACK_CONTINUATION_V86"
ARTIFACT_CONTRACT = "XAU_H4_PULLBACK_CONTINUATION_V86_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
PROMOTION_ELIGIBLE = False
DIAGNOSTIC_ONLY = True

TARGET_R = 2.0
MAX_HOLD_H4_BARS = 6
H4_EMA_FAST = 20
H4_EMA_MID = 50
H4_EMA_SLOW = 200
PIP_SIZE = 0.01
STRATEGY_ID = "V86_H4_PULLBACK_RECLAIM_R200"


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


def build_h4_context(rows: Sequence[Bar]) -> pd.DataFrame:
    h4 = _resample_completed(rows, "4h").copy()
    h4["ema20"] = h4["close"].ewm(
        span=H4_EMA_FAST, adjust=False, min_periods=H4_EMA_FAST
    ).mean()
    h4["ema50"] = h4["close"].ewm(
        span=H4_EMA_MID, adjust=False, min_periods=H4_EMA_MID
    ).mean()
    h4["ema200"] = h4["close"].ewm(
        span=H4_EMA_SLOW, adjust=False, min_periods=H4_EMA_SLOW
    ).mean()
    h4["atr14"] = _wilder_atr(h4, 14)
    return h4


def _cost_r(
    *,
    risk_pips: float,
    bars_held: int,
    costs: M15ResearchCosts,
) -> float:
    if risk_pips <= 0.0:
        raise ValueError("V86_INVALID_RISK_PIPS")
    elapsed_days = max(0, int(bars_held)) * 4.0 / 24.0
    total_pips = (
        float(costs.spread_pips) * float(costs.spread_multiplier)
        + float(costs.slippage_pips) * float(costs.slippage_multiplier)
        + float(costs.commission_pips_round_trip)
        + float(costs.swap_pips_per_day) * elapsed_days
    )
    return total_pips / risk_pips


def _signal_side(
    *,
    previous: Mapping[str, Any],
    current: Mapping[str, Any],
    d1: Mapping[str, Any],
) -> int:
    needed = (
        previous.get("close"),
        previous.get("ema20"),
        current.get("close"),
        current.get("low"),
        current.get("high"),
        current.get("ema20"),
        current.get("ema50"),
        current.get("ema200"),
    )
    try:
        values = [float(x) for x in needed]
    except (TypeError, ValueError):
        return 0
    if not all(np.isfinite(x) for x in values):
        return 0

    prev_close, prev_ema20, close, low, high, ema20, ema50, ema200 = values
    secular_side = int(d1.get("secular_side") or 0)
    regime_side = int(d1.get("regime_side") or 0)

    long_trend = ema20 > ema50 > ema200
    short_trend = ema20 < ema50 < ema200

    # The pullback must genuinely trade through the fast EMA, then reclaim it
    # at the completed H4 close, while remaining on the correct side of EMA50.
    long_reclaim = (
        previous["close"] <= previous["ema20"]
        and low <= ema20
        and close > ema20
        and close > ema50
    )
    short_reclaim = (
        previous["close"] >= previous["ema20"]
        and high >= ema20
        and close < ema20
        and close < ema50
    )

    if secular_side == 1 and regime_side == 1 and long_trend and long_reclaim:
        return 1
    if secular_side == -1 and regime_side == -1 and short_trend and short_reclaim:
        return -1
    return 0


def _simulate(
    rows: Sequence[Bar],
    *,
    costs: M15ResearchCosts,
) -> tuple[TournamentTrade, ...]:
    h4 = build_h4_context(rows)
    d1 = build_secular_d1(rows)
    d1_lookup = _Asof(d1)
    out: list[TournamentTrade] = []

    for i in range(1, len(h4) - 1):
        current = h4.iloc[i].to_dict()
        previous = h4.iloc[i - 1].to_dict()
        signal_at = ensure_utc(current["time"])
        d1_row = d1_lookup.row(signal_at)
        if d1_row is None:
            continue

        side = _signal_side(
            previous=previous,
            current=current,
            d1=d1_row,
        )
        if side == 0:
            continue

        entry_i = i + 1
        entry = float(h4.iloc[entry_i]["open"])
        stop = (
            float(current["low"])
            if side > 0
            else float(current["high"])
        )
        risk = entry - stop if side > 0 else stop - entry
        if not isfinite(risk) or risk <= 0.0:
            continue
        risk_pips = risk / PIP_SIZE
        if risk_pips <= 0.0:
            continue

        entry_cost_r = _cost_r(
            risk_pips=risk_pips,
            bars_held=0,
            costs=costs,
        )
        if entry_cost_r > COST_R_CAP:
            continue

        atr_signal = float(current.get("atr14", np.nan))
        if not isfinite(atr_signal) or atr_signal <= 0.0:
            continue

        target = entry + side * TARGET_R * risk
        entry_at = signal_at
        last_i = min(len(h4) - 1, entry_i + MAX_HOLD_H4_BARS)
        trade: TournamentTrade | None = None

        for j in range(entry_i, last_i + 1):
            row = h4.iloc[j]
            high = float(row["high"])
            low = float(row["low"])
            if side > 0:
                stop_hit = low <= stop
                target_hit = high >= target
            else:
                stop_hit = high >= stop
                target_hit = low <= target

            # Match conservative V18 semantics: target is not credited on the
            # entry bar, while a stop may be.
            raw_target_hit = bool(target_hit)
            if j == entry_i:
                target_hit = False

            held = j - entry_i
            cost_r = _cost_r(
                risk_pips=risk_pips,
                bars_held=held,
                costs=costs,
            )

            if stop_hit:
                gross_r = -1.0
                trade = TournamentTrade(
                    STRATEGY_ID,
                    str(rows[0].symbol),
                    "LONG" if side > 0 else "SHORT",
                    signal_at,
                    entry_at,
                    ensure_utc(row["time"]),
                    i,
                    j,
                    entry,
                    stop,
                    atr_signal,
                    stop,
                    target,
                    gross_r,
                    cost_r,
                    gross_r - cost_r,
                    held,
                    "STOP_FIRST_AMBIGUOUS" if raw_target_hit else "STOP_HIT",
                )
                break

            if target_hit:
                gross_r = TARGET_R
                trade = TournamentTrade(
                    STRATEGY_ID,
                    str(rows[0].symbol),
                    "LONG" if side > 0 else "SHORT",
                    signal_at,
                    entry_at,
                    ensure_utc(row["time"]),
                    i,
                    j,
                    entry,
                    target,
                    atr_signal,
                    stop,
                    target,
                    gross_r,
                    cost_r,
                    gross_r - cost_r,
                    held,
                    "TARGET_HIT",
                )
                break

        if trade is None:
            if last_i < entry_i + MAX_HOLD_H4_BARS:
                continue
            row = h4.iloc[last_i]
            exit_price = float(row["close"])
            gross_r = (
                (exit_price - entry) / risk
                if side > 0
                else (entry - exit_price) / risk
            )
            cost_r = _cost_r(
                risk_pips=risk_pips,
                bars_held=MAX_HOLD_H4_BARS,
                costs=costs,
            )
            trade = TournamentTrade(
                STRATEGY_ID,
                str(rows[0].symbol),
                "LONG" if side > 0 else "SHORT",
                signal_at,
                entry_at,
                ensure_utc(row["time"]),
                i,
                last_i,
                entry,
                exit_price,
                atr_signal,
                stop,
                target,
                gross_r,
                cost_r,
                gross_r - cost_r,
                MAX_HOLD_H4_BARS,
                "TIME_EXIT",
            )
        out.append(trade)

    return tuple(out)


def evaluate_v86(
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
        raise ValueError("V86_EMPTY_HISTORY")
    if abs(float(pip_size) - PIP_SIZE) > 1e-12:
        raise ValueError("V86_REQUIRES_XAU_PIP_SIZE_001")

    start = ensure_utc(era_start)
    end = ensure_utc(era_end)
    dates = _trading_dates(rows, start=start, end=end)
    days = len(dates)

    scenario_results: dict[str, Any] = {}
    for cost_id, costs in cost_scenarios.items():
        all_trades = _simulate(rows, costs=costs)
        era_trades = _period(all_trades, start=start, end=end)
        scenario_results[cost_id] = {
            "all": _stats(era_trades, days),
            "long": _stats(
                tuple(x for x in era_trades if str(x.direction).upper() == "LONG"),
                days,
            ),
            "short": _stats(
                tuple(x for x in era_trades if str(x.direction).upper() == "SHORT"),
                days,
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
        "era_trading_days": days,
        "preregistered_contract": {
            "direction_authority": "D1 secular side AND D1 regime side",
            "h4_trend_long": "EMA20>EMA50>EMA200",
            "h4_trend_short": "EMA20<EMA50<EMA200",
            "pullback_reclaim_long": "previous H4 close <= previous EMA20; current low <= EMA20; current close > EMA20 and > EMA50",
            "pullback_reclaim_short": "mirror of long",
            "entry": "next completed H4 bucket open",
            "stop": "reclaim H4 bar low for long / high for short",
            "target_r": TARGET_R,
            "max_hold_h4_bars": MAX_HOLD_H4_BARS,
            "max_hold_hours": MAX_HOLD_H4_BARS * 4,
            "entry_cost_r_cap": COST_R_CAP,
            "parameter_grid_search": False,
            "alternate_target_variants": False,
            "alternate_stop_variants": False,
            "selection_uses_future_outcomes": False,
            "execution_authority": False,
        },
        "scenario_results": scenario_results,
        "note": (
            "V86 is an independent higher-horizon trend-pullback family. It does not use "
            "M15 breakout, ICT sweep, FVG, OPR, or V47 family-health gating. D1 supplies "
            "direction and H4 supplies a causal EMA20 pullback/reclaim timing signal."
        ),
    }

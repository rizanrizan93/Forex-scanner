from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import timedelta
from math import isfinite
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from .demo_donchian_adaptive_tournament import TournamentTrade, compute_metrics
from .models import Bar, ensure_utc
from .research_multisymbol_m15_breakout_v18 import _cost_r
from .research_xau_hierarchical_regime_router_v35 import (
    _Asof,
    _direction_metrics,
    _max_losing_streak,
    _period,
    _resample_completed,
    build_d1_context,
)
from .research_xau_multihorizon_100usd_v20 import _trading_dates
from .research_xau_m15_dual_strategy import M15ResearchCosts

RESEARCH_VERSION = "XAU_EXTERNAL_LIQUIDITY_REACTION_V50"
ARTIFACT_CONTRACT = "XAU_EXTERNAL_LIQUIDITY_REACTION_V50_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
PROMOTION_ELIGIBLE = False
DIAGNOSTIC_ONLY = True

ATR_PERIOD = 14
MIN_SWEEP_ATR = 0.05
MIN_REJECTION_ATR = 0.35
MIN_BODY_ATR = 0.10
MIN_CLOSE_LOCATION = 0.55
STOP_BUFFER_ATR = 1.00
MSS_CONFIRM_BARS = 4
TARGET_R = 2.00
MAX_HOLD_BARS = 32
COST_R_CAP = 0.10
RANGE_LOOKBACK_DAYS = 60

VARIANTS = (
    "PD_SWEEP_RECLAIM_2R_CONTROL",
    "PD_SWEEP_MSS_2R",
    "PD_SWEEP_MSS_D1_ALIGNED_2R",
    "PD_SWEEP_MSS_RANGE_CREDIBLE_2R",
    "PD_SWEEP_MSS_D1_ALIGNED_RANGE_CREDIBLE_2R",
)


@dataclass(frozen=True, slots=True)
class V50Signal:
    signal_index: int
    signal_at: Any
    direction: str
    atr: float
    structural_stop: float
    trigger: float
    swept_level: float
    opposite_external_level: float
    median_daily_range60: float
    d1_side: int


def _atr_series(rows: Sequence[Bar], period: int = ATR_PERIOD) -> list[float | None]:
    output: list[float | None] = [None] * len(rows)
    if not rows:
        return output
    tr: list[float] = []
    for i, row in enumerate(rows):
        if i == 0:
            value = float(row.high) - float(row.low)
        else:
            prev = float(rows[i - 1].close)
            value = max(
                float(row.high) - float(row.low),
                abs(float(row.high) - prev),
                abs(float(row.low) - prev),
            )
        tr.append(value)
    alpha = 1.0 / float(period)
    value = tr[0]
    for i in range(1, len(tr)):
        value = alpha * tr[i] + (1.0 - alpha) * value
        if i >= period - 1:
            output[i] = float(value)
    return output


def build_daily_liquidity_context(rows: Sequence[Bar]) -> pd.DataFrame:
    daily = _resample_completed(rows, "1D").copy()
    daily["pdh"] = daily["high"]
    daily["pdl"] = daily["low"]
    daily["daily_range"] = daily["high"] - daily["low"]
    daily["median_daily_range60"] = (
        daily["daily_range"]
        .rolling(RANGE_LOOKBACK_DAYS, min_periods=RANGE_LOOKBACK_DAYS)
        .median()
    )
    return daily


def _sweep_signal(
    row: Bar,
    *,
    atr: float,
    pdh: float,
    pdl: float,
) -> tuple[str, float, float, float] | None:
    rng = max(float(row.high) - float(row.low), 1e-12)
    open_ = float(row.open)
    close = float(row.close)
    high = float(row.high)
    low = float(row.low)

    long_depth = (pdl - low) / atr
    long_rejection = (close - low) / atr
    long_body = (close - open_) / atr
    long_location = (close - low) / rng
    long_ok = (
        low < pdl
        and close > pdl
        and close > open_
        and long_depth >= MIN_SWEEP_ATR
        and long_rejection >= MIN_REJECTION_ATR
        and long_body >= MIN_BODY_ATR
        and long_location >= MIN_CLOSE_LOCATION
    )

    short_depth = (high - pdh) / atr
    short_rejection = (high - close) / atr
    short_body = (open_ - close) / atr
    short_location = (high - close) / rng
    short_ok = (
        high > pdh
        and close < pdh
        and close < open_
        and short_depth >= MIN_SWEEP_ATR
        and short_rejection >= MIN_REJECTION_ATR
        and short_body >= MIN_BODY_ATR
        and short_location >= MIN_CLOSE_LOCATION
    )

    if long_ok and short_ok:
        return None
    if long_ok:
        return "LONG", low - STOP_BUFFER_ATR * atr, high, pdl
    if short_ok:
        return "SHORT", high + STOP_BUFFER_ATR * atr, low, pdh
    return None


def extract_signals(rows: Sequence[Bar]) -> tuple[V50Signal, ...]:
    bars = tuple(sorted(rows, key=lambda x: ensure_utc(x.timestamp)))
    if not bars:
        return ()
    atrs = _atr_series(bars)
    daily = build_daily_liquidity_context(bars)
    d1 = build_d1_context(bars)
    daily_lookup = _Asof(daily)
    d1_lookup = _Asof(d1)

    out: list[V50Signal] = []
    for i in range(ATR_PERIOD + 2, len(bars) - 1):
        atr = atrs[i]
        if atr is None or not isfinite(float(atr)) or float(atr) <= 0.0:
            continue
        signal_at = ensure_utc(bars[i].timestamp) + timedelta(minutes=15)
        context = daily_lookup.row(signal_at)
        d1_row = d1_lookup.row(signal_at)
        if context is None or d1_row is None:
            continue
        pdh = float(context.get("pdh", np.nan))
        pdl = float(context.get("pdl", np.nan))
        median_range = float(context.get("median_daily_range60", np.nan))
        if not all(isfinite(v) and v > 0.0 for v in (pdh, pdl, median_range)):
            continue

        signal = _sweep_signal(
            bars[i],
            atr=float(atr),
            pdh=pdh,
            pdl=pdl,
        )
        if signal is None:
            continue
        direction, stop, trigger, swept = signal
        opposite = pdh if direction == "LONG" else pdl
        out.append(
            V50Signal(
                signal_index=i,
                signal_at=signal_at,
                direction=direction,
                atr=float(atr),
                structural_stop=float(stop),
                trigger=float(trigger),
                swept_level=float(swept),
                opposite_external_level=float(opposite),
                median_daily_range60=float(median_range),
                d1_side=int(d1_row.get("regime_side") or 0),
            )
        )
    return tuple(out)


def _needs_mss(variant: str) -> bool:
    return variant != "PD_SWEEP_RECLAIM_2R_CONTROL"


def _needs_d1(variant: str) -> bool:
    return "D1_ALIGNED" in variant


def _needs_range(variant: str) -> bool:
    return "RANGE_CREDIBLE" in variant


def _entry(
    bars: Sequence[Bar],
    sig: V50Signal,
    *,
    mss: bool,
) -> tuple[int, float] | None:
    if not mss:
        i = sig.signal_index + 1
        if i >= len(bars):
            return None
        return i, float(bars[i].open)

    for i in range(
        sig.signal_index + 1,
        min(len(bars), sig.signal_index + 1 + MSS_CONFIRM_BARS),
    ):
        if sig.direction == "LONG" and float(bars[i].high) >= sig.trigger:
            return i, max(float(bars[i].open), sig.trigger)
        if sig.direction == "SHORT" and float(bars[i].low) <= sig.trigger:
            return i, min(float(bars[i].open), sig.trigger)
    return None


def _range_credible(sig: V50Signal, *, entry: float, target: float) -> bool:
    required_move = abs(target - entry)
    within_typical_range = required_move <= float(sig.median_daily_range60)
    if sig.direction == "LONG":
        external_space = float(sig.opposite_external_level) > entry and target <= float(sig.opposite_external_level)
    else:
        external_space = float(sig.opposite_external_level) < entry and target >= float(sig.opposite_external_level)
    return bool(within_typical_range and external_space)


def simulate(
    rows: Sequence[Bar],
    *,
    signals: Sequence[V50Signal],
    variant: str,
    costs: M15ResearchCosts,
    pip_size: float,
) -> tuple[TournamentTrade, ...]:
    if variant not in VARIANTS:
        raise ValueError(f"V50_VARIANT_INVALID:{variant}")
    bars = tuple(sorted(rows, key=lambda x: ensure_utc(x.timestamp)))
    out: list[TournamentTrade] = []

    for sig in signals:
        if _needs_d1(variant):
            side = 1 if sig.direction == "LONG" else -1
            if sig.d1_side != side:
                continue

        found = _entry(bars, sig, mss=_needs_mss(variant))
        if found is None:
            continue
        entry_i, entry = found
        stop = float(sig.structural_stop)
        risk = entry - stop if sig.direction == "LONG" else stop - entry
        if not isfinite(risk) or risk <= 0.0:
            continue
        risk_pips = risk / float(pip_size)
        if risk_pips <= 0.0:
            continue

        entry_cost_r = _cost_r(risk_pips=risk_pips, bars_held=0, costs=costs)
        if entry_cost_r > COST_R_CAP:
            continue

        target = (
            entry + TARGET_R * risk
            if sig.direction == "LONG"
            else entry - TARGET_R * risk
        )
        if _needs_range(variant) and not _range_credible(sig, entry=entry, target=target):
            continue

        last_i = min(len(bars) - 1, entry_i + MAX_HOLD_BARS)
        trade = None
        for j in range(entry_i, last_i + 1):
            bar = bars[j]
            if sig.direction == "LONG":
                stop_hit = float(bar.low) <= stop
                target_hit = float(bar.high) >= target
            else:
                stop_hit = float(bar.high) >= stop
                target_hit = float(bar.low) <= target
            raw_target = target_hit
            if j == entry_i:
                target_hit = False

            held = j - entry_i
            cost = _cost_r(risk_pips=risk_pips, bars_held=held, costs=costs)
            if stop_hit:
                gross = -1.0
                trade = TournamentTrade(
                    variant,
                    "XAUUSD",
                    sig.direction,
                    ensure_utc(sig.signal_at),
                    ensure_utc(bars[entry_i].timestamp),
                    ensure_utc(bar.timestamp),
                    sig.signal_index,
                    j,
                    entry,
                    stop,
                    sig.atr,
                    stop,
                    target,
                    gross,
                    cost,
                    gross - cost,
                    held,
                    "STOP_FIRST_AMBIGUOUS" if raw_target else "STOP_HIT",
                )
                break
            if target_hit:
                gross = TARGET_R
                trade = TournamentTrade(
                    variant,
                    "XAUUSD",
                    sig.direction,
                    ensure_utc(sig.signal_at),
                    ensure_utc(bars[entry_i].timestamp),
                    ensure_utc(bar.timestamp),
                    sig.signal_index,
                    j,
                    entry,
                    target,
                    sig.atr,
                    stop,
                    target,
                    gross,
                    cost,
                    gross - cost,
                    held,
                    "TARGET_HIT",
                )
                break

        if trade is None:
            if last_i < entry_i + MAX_HOLD_BARS:
                continue
            exit_price = float(bars[last_i].close)
            gross = (
                (exit_price - entry) / risk
                if sig.direction == "LONG"
                else (entry - exit_price) / risk
            )
            cost = _cost_r(
                risk_pips=risk_pips,
                bars_held=MAX_HOLD_BARS,
                costs=costs,
            )
            trade = TournamentTrade(
                variant,
                "XAUUSD",
                sig.direction,
                ensure_utc(sig.signal_at),
                ensure_utc(bars[entry_i].timestamp),
                ensure_utc(bars[last_i].timestamp),
                sig.signal_index,
                last_i,
                entry,
                exit_price,
                sig.atr,
                stop,
                target,
                gross,
                cost,
                gross - cost,
                MAX_HOLD_BARS,
                "TIME_EXIT",
            )
        out.append(trade)
    return tuple(out)


def _stats(trades: Sequence[TournamentTrade], trading_days: int) -> dict[str, Any]:
    values = tuple(trades)
    return {
        "trades": len(values),
        "trades_per_day": 0.0 if trading_days <= 0 else len(values) / float(trading_days),
        "max_losing_streak": _max_losing_streak(values),
        "metrics": compute_metrics(values).payload(),
        "direction_metrics": _direction_metrics(values),
    }


def evaluate_v50(
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
        raise ValueError("V50_EMPTY_HISTORY")
    start = ensure_utc(era_start)
    end = ensure_utc(era_end)
    dates = _trading_dates(rows, start=start, end=end)
    trading_days = len(dates)
    signals = extract_signals(rows)

    scenario_results: dict[str, Any] = {}
    for cost_id, costs in cost_scenarios.items():
        variants = {}
        for variant in VARIANTS:
            trades = _period(
                simulate(
                    rows,
                    signals=signals,
                    variant=variant,
                    costs=costs,
                    pip_size=pip_size,
                ),
                start=start,
                end=end,
            )
            variants[variant] = _stats(trades, trading_days)
        scenario_results[cost_id] = {
            "costs": asdict(costs),
            "variants": variants,
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
        "raw_external_liquidity_sweeps": len(signals),
        "preregistered_contract": {
            "external_liquidity": "PREVIOUS_COMPLETED_UTC_DAY_HIGH_LOW",
            "sweep_reclaim": {
                "min_sweep_atr": MIN_SWEEP_ATR,
                "min_rejection_atr": MIN_REJECTION_ATR,
                "min_body_atr": MIN_BODY_ATR,
                "min_close_location": MIN_CLOSE_LOCATION,
            },
            "mss_confirmation_bars": MSS_CONFIRM_BARS,
            "stop": "sweep_extreme_plus_1x_M15_ATR_buffer",
            "target_r": TARGET_R,
            "target_minimum_source": "public LST process states minimum 1:2 risk/reward",
            "range_credibility_proxy": "2R target must fit inside prior-60 completed-session median range and before opposite PDH/PDL",
            "airv3_replication_claimed": False,
            "max_hold_m15_bars": MAX_HOLD_BARS,
            "entry_cost_r_cap": COST_R_CAP,
            "parameter_grid_search": False,
            "selection_uses_future_outcomes": False,
            "execution_authority": False,
        },
        "variants": list(VARIANTS),
        "scenario_results": scenario_results,
        "note": (
            "V50 tests named external-liquidity reactions at PDH/PDL. It is inspired by "
            "publicly documented LST process principles (zones, confirmation, minimum 2R, "
            "volatility-aware target credibility) but does not claim to reproduce proprietary OPR/AIRV3 rules."
        ),
    }

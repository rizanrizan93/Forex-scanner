from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import timedelta
from math import isfinite
from typing import Any, Mapping, Sequence

import numpy as np

from .demo_donchian_adaptive_tournament import TournamentTrade, compute_metrics
from .models import Bar, ensure_utc
from .research_multisymbol_m15_breakout_v18 import _cost_r
from .research_xau_external_liquidity_reaction_v50 import (
    COST_R_CAP,
    RANGE_LOOKBACK_DAYS,
    _atr_series,
    build_daily_liquidity_context,
)
from .research_xau_hierarchical_regime_router_v35 import (
    _Asof,
    _direction_metrics,
    _max_losing_streak,
    _period,
    build_d1_context,
    build_h1_context,
)
from .research_xau_multihorizon_100usd_v20 import _trading_dates
from .research_xau_m15_dual_strategy import M15ResearchCosts

RESEARCH_VERSION = "XAU_EXTERNAL_LIQUIDITY_CASCADE_V51"
ARTIFACT_CONTRACT = "XAU_EXTERNAL_LIQUIDITY_CASCADE_V51_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
PROMOTION_ELIGIBLE = False
DIAGNOSTIC_ONLY = True

BODY_ATR_MIN = 0.55
CLOSE_LOCATION_MIN = 0.68
STOP_BUFFER_ATR = 0.15
MIN_RISK_ATR = 0.50
COOLDOWN_BARS = 4
TARGET_R = 2.00
MAX_HOLD_BARS = 16

VARIANTS = (
    "PD_CASCADE_2R_CONTROL",
    "PD_CASCADE_H1_NORMAL_2R",
    "PD_CASCADE_D1_MATCH_2R",
    "PD_CASCADE_D1_H1_2R",
    "PD_CASCADE_D1_H1_RANGE_CREDIBLE_2R",
)


@dataclass(frozen=True, slots=True)
class V51Signal:
    signal_index: int
    signal_at: Any
    direction: str
    atr: float
    stop: float
    broken_level: float
    d1_side: int
    h1_normal: bool
    median_daily_range60: float


def _h1_permission(row: Mapping[str, Any], direction: str) -> bool:
    close = float(row.get("close", np.nan))
    ema20 = float(row.get("ema20", np.nan))
    ema50 = float(row.get("ema50", np.nan))
    ema200 = float(row.get("ema200", np.nan))
    if not all(isfinite(v) for v in (close, ema20, ema50, ema200)):
        return False
    if direction == "LONG":
        return close > ema200 and ema20 > ema50
    return close < ema200 and ema20 < ema50


def extract_signals(rows: Sequence[Bar]) -> tuple[V51Signal, ...]:
    bars = tuple(sorted(rows, key=lambda x: ensure_utc(x.timestamp)))
    if not bars:
        return ()
    atrs = _atr_series(bars)
    daily = build_daily_liquidity_context(bars)
    d1 = build_d1_context(bars)
    h1 = build_h1_context(bars)
    daily_lookup = _Asof(daily)
    d1_lookup = _Asof(d1)
    h1_lookup = _Asof(h1)

    out: list[V51Signal] = []
    last_i = -10_000
    for i in range(220, len(bars) - 1):
        if i - last_i < COOLDOWN_BARS:
            continue
        atr = atrs[i]
        if atr is None or not isfinite(float(atr)) or float(atr) <= 0:
            continue
        row = bars[i]
        prev = bars[i - 1]
        rng = float(row.high) - float(row.low)
        body = abs(float(row.close) - float(row.open))
        if rng <= 0 or body < BODY_ATR_MIN * float(atr):
            continue

        signal_at = ensure_utc(row.timestamp) + timedelta(minutes=15)
        daily_row = daily_lookup.row(signal_at)
        d1_row = d1_lookup.row(signal_at)
        h1_row = h1_lookup.row(signal_at)
        if daily_row is None or d1_row is None or h1_row is None:
            continue

        pdh = float(daily_row.get("pdh", np.nan))
        pdl = float(daily_row.get("pdl", np.nan))
        median_range = float(daily_row.get("median_daily_range60", np.nan))
        if not all(isfinite(v) and v > 0 for v in (pdh, pdl, median_range)):
            continue

        direction = None
        level = None
        if (
            float(prev.close) <= pdh
            and float(row.close) > pdh
            and (float(row.close) - float(row.low)) / rng >= CLOSE_LOCATION_MIN
        ):
            direction = "LONG"
            level = pdh
        elif (
            float(prev.close) >= pdl
            and float(row.close) < pdl
            and (float(row.high) - float(row.close)) / rng >= CLOSE_LOCATION_MIN
        ):
            direction = "SHORT"
            level = pdl
        if direction is None or level is None:
            continue

        local = bars[max(0, i - 5): i + 1]
        if direction == "LONG":
            stop = min(float(x.low) for x in local) - STOP_BUFFER_ATR * float(atr)
        else:
            stop = max(float(x.high) for x in local) + STOP_BUFFER_ATR * float(atr)

        out.append(
            V51Signal(
                signal_index=i,
                signal_at=signal_at,
                direction=direction,
                atr=float(atr),
                stop=float(stop),
                broken_level=float(level),
                d1_side=int(d1_row.get("regime_side") or 0),
                h1_normal=_h1_permission(h1_row, direction),
                median_daily_range60=float(median_range),
            )
        )
        last_i = i
    return tuple(out)


def _allowed(sig: V51Signal, variant: str) -> bool:
    if variant not in VARIANTS:
        raise ValueError(f"V51_VARIANT_INVALID:{variant}")
    side = 1 if sig.direction == "LONG" else -1
    if "D1_MATCH" in variant or "D1_H1" in variant:
        if sig.d1_side != side:
            return False
    if "H1_NORMAL" in variant or "D1_H1" in variant:
        if not sig.h1_normal:
            return False
    return True


def _range_credible(sig: V51Signal, *, entry: float, target: float) -> bool:
    return abs(target - entry) <= float(sig.median_daily_range60)


def simulate(
    rows: Sequence[Bar],
    *,
    signals: Sequence[V51Signal],
    variant: str,
    costs: M15ResearchCosts,
    pip_size: float,
) -> tuple[TournamentTrade, ...]:
    bars = tuple(sorted(rows, key=lambda x: ensure_utc(x.timestamp)))
    out: list[TournamentTrade] = []

    for sig in signals:
        if not _allowed(sig, variant):
            continue
        entry_i = sig.signal_index + 1
        if entry_i >= len(bars):
            continue
        entry = float(bars[entry_i].open)
        stop = float(sig.stop)
        risk = entry - stop if sig.direction == "LONG" else stop - entry
        if not isfinite(risk) or risk < MIN_RISK_ATR * float(sig.atr):
            continue

        risk_pips = risk / float(pip_size)
        if risk_pips <= 0:
            continue
        entry_cost_r = _cost_r(risk_pips=risk_pips, bars_held=0, costs=costs)
        if entry_cost_r > COST_R_CAP:
            continue

        target = (
            entry + TARGET_R * risk
            if sig.direction == "LONG"
            else entry - TARGET_R * risk
        )
        if "RANGE_CREDIBLE" in variant and not _range_credible(sig, entry=entry, target=target):
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
                    variant, "XAUUSD", sig.direction, ensure_utc(sig.signal_at),
                    ensure_utc(bars[entry_i].timestamp), ensure_utc(bar.timestamp),
                    sig.signal_index, j, entry, stop, sig.atr, stop, target,
                    gross, cost, gross - cost, held,
                    "STOP_FIRST_AMBIGUOUS" if raw_target else "STOP_HIT",
                )
                break
            if target_hit:
                gross = TARGET_R
                trade = TournamentTrade(
                    variant, "XAUUSD", sig.direction, ensure_utc(sig.signal_at),
                    ensure_utc(bars[entry_i].timestamp), ensure_utc(bar.timestamp),
                    sig.signal_index, j, entry, target, sig.atr, stop, target,
                    gross, cost, gross - cost, held, "TARGET_HIT",
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
                variant, "XAUUSD", sig.direction, ensure_utc(sig.signal_at),
                ensure_utc(bars[entry_i].timestamp), ensure_utc(bars[last_i].timestamp),
                sig.signal_index, last_i, entry, exit_price, sig.atr, stop, target,
                gross, cost, gross - cost, MAX_HOLD_BARS, "TIME_EXIT",
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


def evaluate_v51(
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
        raise ValueError("V51_EMPTY_HISTORY")
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
        "raw_cascade_signals": len(signals),
        "preregistered_contract": {
            "external_liquidity": "PREVIOUS_COMPLETED_UTC_DAY_HIGH_LOW",
            "first_cross_required": True,
            "displacement_body_atr_min": BODY_ATR_MIN,
            "directional_close_location_min": CLOSE_LOCATION_MIN,
            "stop": "V18 local-6-bar extreme plus 0.15 M15 ATR",
            "min_risk_atr": MIN_RISK_ATR,
            "cooldown_m15_bars": COOLDOWN_BARS,
            "target_r": TARGET_R,
            "max_hold_m15_bars": MAX_HOLD_BARS,
            "entry_cost_r_cap": COST_R_CAP,
            "range_credibility": "2R distance <= prior-60 completed-session median daily range",
            "threshold_sources": "frozen V18 strongest L20 geometry plus V50 60-session context",
            "parameter_grid_search": False,
            "selection_uses_future_outcomes": False,
            "execution_authority": False,
        },
        "variants": list(VARIANTS),
        "scenario_results": scenario_results,
        "note": (
            "V51 tests the continuation side of external-liquidity interaction: "
            "displacement through PDH/PDL followed by next-bar continuation. "
            "This is the microstructure comparator to the rejected V50 sweep/reclaim fade."
        ),
    }

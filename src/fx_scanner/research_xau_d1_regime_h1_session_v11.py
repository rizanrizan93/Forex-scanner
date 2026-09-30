from __future__ import annotations

from bisect import bisect_left
from dataclasses import asdict, dataclass
from math import isfinite
from typing import Any, Mapping, Sequence

from .demo_donchian_adaptive_tournament import (
    TournamentMetrics,
    TournamentTrade,
    compute_metrics,
    walk_forward,
)
from .models import Bar, ensure_utc
from .research_xau_d1_tsmom_crossfeed_v1 import _ema, resample_h1_to_daily
from .research_xau_m15_continuation_tournament import (
    DEVELOPMENT_FRACTION,
    FINAL_OOS_EXPECTANCY_R_MIN,
    FINAL_OOS_PROFIT_FACTOR_MIN,
    FINAL_OOS_WIN_RATE_MIN,
    MIN_HOLDOUT_TRADES,
    _indicator_series,
    _metrics_pass,
)
from .research_xau_m15_dual_strategy import M15ResearchCosts

RESEARCH_VERSION = "XAU_D1_REGIME_H1_SESSION_V11"
ARTIFACT_CONTRACT = "XAU_D1_REGIME_H1_SESSION_V11_EVIDENCE_1"
SYMBOL = "XAUUSD"
TIMEFRAME = "H1"
PIP_SIZE = 0.01
H1_SECONDS = 3600
D1_LOOKBACK = 60
D1_EMA = 200
H1_ATR_PERIOD = 14
MIN_DEVELOPMENT_TRADES = 130


@dataclass(frozen=True, slots=True)
class SessionEntryVariant:
    variant_id: str
    session_hour_utc: int
    h1_filter: str
    stop_atr: float
    target_r: float
    max_hold_bars: int
    selection_eligible: bool = True


VARIANTS = (
    SessionEntryVariant("XAU_V11_ASIA00_D1BIAS_R15", 0, "NONE", 1.50, 1.50, 12),
    SessionEntryVariant("XAU_V11_EU07_D1BIAS_R15_CONTROL", 7, "NONE", 1.50, 1.50, 12, False),
    SessionEntryVariant("XAU_V11_US12_D1BIAS_R15", 12, "NONE", 1.50, 1.50, 12),
    SessionEntryVariant("XAU_V11_US12_D1BIAS_R125", 12, "NONE", 1.50, 1.25, 12),
    SessionEntryVariant("XAU_V11_US12_D1BIAS_R20", 12, "NONE", 1.50, 2.00, 12),
    SessionEntryVariant("XAU_V11_ASIA00_D1BIAS_H1ALIGN_R15", 0, "EMA20_50_ALIGN", 1.50, 1.50, 12),
    SessionEntryVariant("XAU_V11_US12_D1BIAS_H1ALIGN_R15", 12, "EMA20_50_ALIGN", 1.50, 1.50, 12),
    SessionEntryVariant("XAU_V11_US12_D1BIAS_H1NO_R15", 12, "EMA20_50_NOT_OPPOSED", 1.50, 1.50, 12),
    SessionEntryVariant("XAU_V11_US12_D1BIAS_H1NO_R20", 12, "EMA20_50_NOT_OPPOSED", 1.50, 2.00, 12),
    SessionEntryVariant("XAU_V11_US12_D1BIAS_H1NO_STOP10_R15", 12, "EMA20_50_NOT_OPPOSED", 1.00, 1.50, 12),
)


def _validate_h1(bars: Sequence[Bar]) -> tuple[Bar, ...]:
    rows = tuple(sorted(bars, key=lambda row: ensure_utc(row.timestamp)))
    if not rows:
        raise ValueError("XAU_V11_H1_EMPTY")
    if any(row.symbol.upper() != SYMBOL or row.timeframe.upper() != TIMEFRAME for row in rows):
        raise ValueError("XAU_V11_REQUIRES_XAUUSD_H1")
    if any(
        ensure_utc(rows[i].timestamp) >= ensure_utc(rows[i + 1].timestamp)
        for i in range(len(rows) - 1)
    ):
        raise ValueError("XAU_V11_H1_NOT_CHRONOLOGICAL")
    return rows


def _daily_bias(daily, ema200, index: int) -> str | None:
    if index < max(D1_LOOKBACK, D1_EMA - 1):
        return None
    ema = ema200[index]
    if ema is None:
        return None
    close = float(daily[index].close)
    prior = float(daily[index - D1_LOOKBACK].close)
    if prior <= 0.0:
        return None
    ret = close / prior - 1.0
    if close > float(ema) and ret > 0.0:
        return "LONG"
    if close < float(ema) and ret < 0.0:
        return "SHORT"
    return None


def _h1_filter_ok(
    rows: Sequence[Bar],
    indicators,
    index: int,
    direction: str,
    filter_name: str,
) -> bool:
    if filter_name == "NONE":
        return True
    if index < 50:
        return False
    ema20 = indicators["ema20"][index]
    ema50 = indicators["ema50"][index]
    if ema20 is None or ema50 is None:
        return False
    close = float(rows[index].close)
    ema20 = float(ema20)
    ema50 = float(ema50)
    if direction == "LONG":
        aligned = close > ema20 > ema50
        opposed = close < ema20 < ema50
    else:
        aligned = close < ema20 < ema50
        opposed = close > ema20 > ema50
    if filter_name == "EMA20_50_ALIGN":
        return aligned
    if filter_name == "EMA20_50_NOT_OPPOSED":
        return not opposed
    raise ValueError(f"XAU_V11_H1_FILTER_INVALID:{filter_name}")


def _cost_r(
    *,
    risk_pips: float,
    bars_held: int,
    costs: M15ResearchCosts,
) -> float:
    elapsed_days = max(0, bars_held) * H1_SECONDS / 86400.0
    total_pips = (
        float(costs.spread_pips) * float(costs.spread_multiplier)
        + float(costs.slippage_pips) * float(costs.slippage_multiplier)
        + float(costs.commission_pips_round_trip)
        + float(costs.swap_pips_per_day) * elapsed_days
    )
    return total_pips / risk_pips


def simulate_variant(
    bars: Sequence[Bar],
    *,
    variant: SessionEntryVariant,
    costs: M15ResearchCosts,
) -> tuple[TournamentTrade, ...]:
    rows = _validate_h1(bars)
    indicators = _indicator_series(rows)
    daily = resample_h1_to_daily(rows, boundary_hour_utc=0)
    daily_days = [row.day for row in daily]
    daily_ema200 = _ema([float(row.close) for row in daily], D1_EMA)
    output: list[TournamentTrade] = []

    for entry_index in range(220, len(rows)):
        entry_bar = rows[entry_index]
        stamp = ensure_utc(entry_bar.timestamp)
        if stamp.minute != 0 or stamp.hour != variant.session_hour_utc:
            continue

        daily_index = bisect_left(daily_days, stamp.date()) - 1
        if daily_index < 0:
            continue
        direction = _daily_bias(daily, daily_ema200, daily_index)
        if direction is None:
            continue

        prior_h1 = entry_index - 1
        if not _h1_filter_ok(
            rows,
            indicators,
            prior_h1,
            direction,
            variant.h1_filter,
        ):
            continue
        atr_raw = indicators["atr"][prior_h1]
        if atr_raw is None:
            continue
        atr = float(atr_raw)
        if not isfinite(atr) or atr <= 0.0:
            continue

        entry = float(entry_bar.open)
        risk = float(variant.stop_atr) * atr
        if not isfinite(risk) or risk <= 0.0:
            continue
        if direction == "LONG":
            stop = entry - risk
            target = entry + float(variant.target_r) * risk
        else:
            stop = entry + risk
            target = entry - float(variant.target_r) * risk
        risk_pips = risk / PIP_SIZE

        last_index = min(len(rows) - 1, entry_index + int(variant.max_hold_bars) - 1)
        trade = None
        for index in range(entry_index, last_index + 1):
            row = rows[index]
            if direction == "LONG":
                stop_hit = float(row.low) <= stop
                target_hit = float(row.high) >= target
            else:
                stop_hit = float(row.high) >= stop
                target_hit = float(row.low) <= target

            bars_held = index - entry_index + 1
            cost_r = _cost_r(
                risk_pips=risk_pips,
                bars_held=bars_held,
                costs=costs,
            )
            if stop_hit:
                gross_r = -1.0
                trade = TournamentTrade(
                    variant.variant_id,
                    SYMBOL,
                    direction,
                    ensure_utc(rows[prior_h1].timestamp),
                    stamp,
                    ensure_utc(row.timestamp),
                    prior_h1,
                    index,
                    entry,
                    stop,
                    atr,
                    stop,
                    target,
                    gross_r,
                    cost_r,
                    gross_r - cost_r,
                    bars_held,
                    "STOP_FIRST_AMBIGUOUS" if target_hit else "STOP_HIT",
                )
                break
            if target_hit:
                gross_r = float(variant.target_r)
                trade = TournamentTrade(
                    variant.variant_id,
                    SYMBOL,
                    direction,
                    ensure_utc(rows[prior_h1].timestamp),
                    stamp,
                    ensure_utc(row.timestamp),
                    prior_h1,
                    index,
                    entry,
                    target,
                    atr,
                    stop,
                    target,
                    gross_r,
                    cost_r,
                    gross_r - cost_r,
                    bars_held,
                    "TARGET_HIT",
                )
                break

        if trade is None:
            row = rows[last_index]
            exit_price = float(row.close)
            gross_r = (
                (exit_price - entry) / risk
                if direction == "LONG"
                else (entry - exit_price) / risk
            )
            bars_held = last_index - entry_index + 1
            cost_r = _cost_r(
                risk_pips=risk_pips,
                bars_held=bars_held,
                costs=costs,
            )
            trade = TournamentTrade(
                variant.variant_id,
                SYMBOL,
                direction,
                ensure_utc(rows[prior_h1].timestamp),
                stamp,
                ensure_utc(row.timestamp),
                prior_h1,
                last_index,
                entry,
                exit_price,
                atr,
                stop,
                target,
                gross_r,
                cost_r,
                gross_r - cost_r,
                bars_held,
                "TIME_EXIT",
            )
        output.append(trade)
    return tuple(output)


def _coverage(rows: Sequence[Bar], trades: Sequence[TournamentTrade]) -> dict[str, Any]:
    days = sorted({ensure_utc(row.timestamp).date() for row in rows})
    signal_days = sorted({ensure_utc(trade.entry_at).date() for trade in trades})
    return {
        "calendar_bar_days": len(days),
        "days_with_trade": len(signal_days),
        "signal_day_coverage": len(signal_days) / len(days) if days else 0.0,
        "trades": len(trades),
    }


def _final_oos_pass(metrics: TournamentMetrics) -> bool:
    return bool(
        metrics.completed_trades >= MIN_HOLDOUT_TRADES
        and metrics.win_rate is not None
        and metrics.win_rate >= FINAL_OOS_WIN_RATE_MIN
        and metrics.profit_factor is not None
        and metrics.profit_factor >= FINAL_OOS_PROFIT_FACTOR_MIN
        and metrics.expectancy_r is not None
        and metrics.expectancy_r >= FINAL_OOS_EXPECTANCY_R_MIN
    )


def evaluate_d1_regime_h1_session_v11(
    bars: Sequence[Bar],
    *,
    costs: M15ResearchCosts,
    stressed_costs: M15ResearchCosts,
    validation_cfg: Mapping[str, Any],
) -> dict[str, Any]:
    rows = _validate_h1(bars)
    split_index = max(5000, min(len(rows) - 1, int(len(rows) * DEVELOPMENT_FRACTION)))
    development_rows = rows[:split_index]
    holdout_rows = rows[split_index:]
    evaluations = []
    base_sets = {}
    stress_sets = {}

    for variant in VARIANTS:
        base = simulate_variant(rows, variant=variant, costs=costs)
        stressed = simulate_variant(rows, variant=variant, costs=stressed_costs)
        base_sets[variant.variant_id] = base
        stress_sets[variant.variant_id] = stressed
        dev = tuple(
            trade for trade in base
            if trade.signal_index < split_index and trade.exit_index < split_index
        )
        dev_stress = tuple(
            trade for trade in stressed
            if trade.signal_index < split_index and trade.exit_index < split_index
        )
        metrics = compute_metrics(dev)
        stress_metrics = compute_metrics(dev_stress)
        folds, pass_fraction, wf_passed = walk_forward(
            dev,
            validation_cfg["walk_forward"],
        )
        stress_passed = _metrics_pass(
            stress_metrics,
            validation_cfg["stress_acceptance"],
        )
        development_passed = bool(
            metrics.completed_trades >= MIN_DEVELOPMENT_TRADES
            and wf_passed
            and stress_passed
        )
        by_direction = {
            direction: compute_metrics(
                tuple(trade for trade in dev if trade.direction == direction)
            ).payload()
            for direction in ("LONG", "SHORT")
        }
        evaluations.append(
            {
                "variant": asdict(variant),
                "development": metrics.payload(),
                "development_by_direction": by_direction,
                "stressed_development": stress_metrics.payload(),
                "walk_forward": {
                    "folds": [
                        {
                            "fold": fold.fold,
                            "train_trades": fold.train_trades,
                            "test_trades": fold.test_trades,
                            "passed": fold.passed,
                            "test_metrics": fold.test_metrics.payload(),
                        }
                        for fold in folds
                    ],
                    "pass_fraction": pass_fraction,
                    "passed": wf_passed,
                },
                "stress_passed": stress_passed,
                "development_passed": development_passed,
                "development_coverage": _coverage(development_rows, dev),
            }
        )

    eligible = [
        row for row in evaluations
        if row["development_passed"] and bool(row["variant"]["selection_eligible"])
    ]
    eligible.sort(
        key=lambda row: (
            float(row["walk_forward"]["pass_fraction"]),
            float(row["stressed_development"].get("expectancy_r") or -999.0),
            float(row["stressed_development"].get("profit_factor") or -999.0),
            float(row["development"].get("expectancy_r") or -999.0),
        ),
        reverse=True,
    )
    selected = eligible[0] if eligible else None
    holdout = None
    promotion_eligible = False

    if selected is not None:
        variant_id = str(selected["variant"]["variant_id"])
        base = tuple(
            trade for trade in base_sets[variant_id]
            if trade.signal_index >= split_index and trade.exit_index < len(rows)
        )
        stress = tuple(
            trade for trade in stress_sets[variant_id]
            if trade.signal_index >= split_index and trade.exit_index < len(rows)
        )
        base_metrics = compute_metrics(base)
        stress_metrics = compute_metrics(stress)
        promotion_eligible = bool(
            _final_oos_pass(base_metrics)
            and _metrics_pass(stress_metrics, validation_cfg["stress_acceptance"])
        )
        holdout = {
            "variant_id": variant_id,
            "base": base_metrics.payload(),
            "stressed": stress_metrics.payload(),
            "coverage": _coverage(holdout_rows, base),
            "passed": promotion_eligible,
        }

    return {
        "research_version": RESEARCH_VERSION,
        "symbol": SYMBOL,
        "input_timeframe": TIMEFRAME,
        "h1_bars": len(rows),
        "variants": evaluations,
        "selected_variant": None if selected is None else selected["variant"]["variant_id"],
        "holdout": holdout,
        "promotion_eligible": promotion_eligible,
        "policy_effect": "SHADOW_ONLY",
        "execution_influence": False,
        "selection_note": (
            "D1 TSMOM 60/200 is frozen as the regime signal from prior independent "
            "cross-feed evidence. V11 only tests H1 session timing and risk geometry."
        ),
    }

from __future__ import annotations

from bisect import bisect_right
from dataclasses import asdict, dataclass
from datetime import timedelta
from typing import Any, Mapping, Sequence

from .demo_donchian_adaptive_tournament import (
    TournamentMetrics,
    compute_metrics,
    walk_forward,
)
from .models import Bar, ensure_utc
from .research_xau_m15_continuation_tournament import (
    DEVELOPMENT_FRACTION,
    FINAL_OOS_EXPECTANCY_R_MIN,
    FINAL_OOS_PROFIT_FACTOR_MIN,
    FINAL_OOS_WIN_RATE_MIN,
    MIN_DEVELOPMENT_TRADES,
    MIN_HOLDOUT_TRADES,
    ContinuationSignal,
    _daily_coverage,
    _indicator_series,
    _metrics_pass,
)
from .research_xau_m15_dual_strategy import M15ResearchCosts
from .research_xau_m5_confirmation_v6 import (
    M5Variant,
    _aggregate_h1,
    _aggregate_m15,
    _confirmed_signals,
    _validate_m5,
    simulate_m5_trades,
)

RESEARCH_VERSION = "XAU_H1_M15_M5_TREND_V9"
ARTIFACT_CONTRACT = "XAU_H1_M15_M5_TREND_V9_EVIDENCE_1"
SYMBOL = "XAUUSD"
M15_STOP_LOOKBACK = 4
M15_STOP_BUFFER_ATR = 0.20
M15_TOUCH_TOLERANCE_ATR = 0.15
SIGNAL_COOLDOWN_M15 = 4


@dataclass(frozen=True, slots=True)
class TrendVariant:
    variant_id: str
    h1_ema200: bool
    h1_adx_min: float
    m15_require_alignment: bool
    pullback_ema: int
    trigger_mode: str
    stop_mode: str
    target_r: float
    selection_eligible: bool = True


VARIANTS = (
    TrendVariant("XAU_V9_H1_2050_ADX15_M15_20_BASIC_R125", False, 15.0, True, 20, "BASIC_BREAK", "M15", 1.25),
    TrendVariant("XAU_V9_H1_2050_ADX15_M15_20_BASIC_R15", False, 15.0, True, 20, "BASIC_BREAK", "M15", 1.50),
    TrendVariant("XAU_V9_H1_2050_ADX20_M15_20_BASIC_R15", False, 20.0, True, 20, "BASIC_BREAK", "M15", 1.50),
    TrendVariant("XAU_V9_H1_2050200_ADX15_M15_20_BASIC_R15", True, 15.0, True, 20, "BASIC_BREAK", "M15", 1.50),
    TrendVariant("XAU_V9_H1_2050_ADX15_M15_20_DISP_R15", False, 15.0, True, 20, "DISPLACEMENT_BREAK", "M15", 1.50),
    TrendVariant("XAU_V9_H1_2050_ADX15_M15_50_BASIC_R15", False, 15.0, True, 50, "BASIC_BREAK", "M15", 1.50),
    TrendVariant("XAU_V9_H1_2050_ADX15_NO_M15_ALIGN_BASIC_R15", False, 15.0, False, 20, "BASIC_BREAK", "M15", 1.50),
    TrendVariant("XAU_V9_H1_2050_ADX15_M15_20_BASIC_M5STOP_R15", False, 15.0, True, 20, "BASIC_BREAK", "M5_LOCAL", 1.50),
)


def _h1_bias(
    *,
    h1: Sequence[Bar],
    indicators,
    index: int,
    variant: TrendVariant,
) -> str | None:
    if index < 200:
        return None
    ema20 = indicators["ema20"][index]
    ema50 = indicators["ema50"][index]
    ema200 = indicators["ema200"][index]
    adx = indicators["adx"][index]
    plus_di = indicators["plus_di"][index]
    minus_di = indicators["minus_di"][index]
    if None in (ema20, ema50, ema200, adx, plus_di, minus_di):
        return None
    if float(adx) < variant.h1_adx_min:
        return None
    close = float(h1[index].close)
    long_ok = close > float(ema20) > float(ema50) and float(plus_di) > float(minus_di)
    short_ok = close < float(ema20) < float(ema50) and float(minus_di) > float(plus_di)
    if variant.h1_ema200:
        long_ok = long_ok and float(ema50) > float(ema200)
        short_ok = short_ok and float(ema50) < float(ema200)
    if long_ok == short_ok:
        return None
    return "LONG" if long_ok else "SHORT"


def _m15_pullback_signals(
    m15: Sequence[Bar],
    *,
    variant: TrendVariant,
    h1: Sequence[Bar],
    h1_closes,
    h1_indicators,
) -> tuple[ContinuationSignal, ...]:
    indicators = _indicator_series(m15)
    output = []
    last_signal_index = -10_000

    for index in range(max(210, M15_STOP_LOOKBACK), len(m15) - 2):
        if index - last_signal_index < SIGNAL_COOLDOWN_M15:
            continue
        row = m15[index]
        signal_close = ensure_utc(row.timestamp) + timedelta(minutes=15)
        h1_count = bisect_right(h1_closes, signal_close)
        if h1_count <= 0:
            continue
        direction = _h1_bias(
            h1=h1,
            indicators=h1_indicators,
            index=h1_count - 1,
            variant=variant,
        )
        if direction is None:
            continue

        atr_raw = indicators["atr"][index]
        ema20_raw = indicators["ema20"][index]
        ema50_raw = indicators["ema50"][index]
        if None in (atr_raw, ema20_raw, ema50_raw):
            continue
        atr = float(atr_raw)
        ema20 = float(ema20_raw)
        ema50 = float(ema50_raw)
        if atr <= 0.0:
            continue

        touch_ema = ema20 if variant.pullback_ema == 20 else ema50
        candle_range = float(row.high) - float(row.low)
        body = abs(float(row.close) - float(row.open))
        if candle_range <= 0.0 or body < 0.15 * atr:
            continue

        if direction == "LONG":
            m15_aligned = ema20 > ema50
            touched = float(row.low) <= touch_ema + M15_TOUCH_TOLERANCE_ATR * atr
            accepted = float(row.close) > touch_ema and float(row.close) > float(row.open)
            close_location = (float(row.close) - float(row.low)) / candle_range
            if not (touched and accepted and close_location >= 0.60):
                continue
            if variant.m15_require_alignment and not m15_aligned:
                continue
            recent = m15[index - M15_STOP_LOOKBACK + 1:index + 1]
            stop = min(float(bar.low) for bar in recent) - M15_STOP_BUFFER_ATR * atr
        else:
            m15_aligned = ema20 < ema50
            touched = float(row.high) >= touch_ema - M15_TOUCH_TOLERANCE_ATR * atr
            accepted = float(row.close) < touch_ema and float(row.close) < float(row.open)
            close_location = (float(row.high) - float(row.close)) / candle_range
            if not (touched and accepted and close_location >= 0.60):
                continue
            if variant.m15_require_alignment and not m15_aligned:
                continue
            recent = m15[index - M15_STOP_LOOKBACK + 1:index + 1]
            stop = max(float(bar.high) for bar in recent) + M15_STOP_BUFFER_ATR * atr

        output.append(
            ContinuationSignal(
                variant_id=variant.variant_id,
                signal_index=index,
                direction=direction,
                signal_at=ensure_utc(row.timestamp),
                atr=atr,
                breakout_level=touch_ema,
                structural_stop=stop,
                reward_r=variant.target_r,
                impulse_index=index,
                retest_index=index,
                fvg_low=None,
                fvg_high=None,
            )
        )
        last_signal_index = index
    return tuple(output)


def _execution_variant(variant: TrendVariant) -> M5Variant:
    return M5Variant(
        variant_id=variant.variant_id,
        long_filter=None,
        long_target_r=variant.target_r,
        short_filter=None,
        short_target_r=variant.target_r,
        trigger_mode=variant.trigger_mode,
        stop_mode=variant.stop_mode,
        selection_eligible=variant.selection_eligible,
    )


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


def evaluate_h1_m15_m5_trend_v9(
    bars: Sequence[Bar],
    *,
    costs: M15ResearchCosts,
    stressed_costs: M15ResearchCosts,
    validation_cfg: Mapping[str, Any],
) -> dict[str, Any]:
    m5 = _validate_m5(bars)
    split_index = max(5000, min(len(m5) - 1, int(len(m5) * DEVELOPMENT_FRACTION)))
    development_rows = m5[:split_index]
    holdout_rows = m5[split_index:]
    m15 = _aggregate_m15(m5)
    h1 = _aggregate_h1(m15)
    h1_closes = tuple(ensure_utc(row.timestamp) + timedelta(hours=1) for row in h1)
    h1_indicators = _indicator_series(h1)

    evaluations = []
    base_sets = {}
    stress_sets = {}
    signal_sets = {}

    for variant in VARIANTS:
        m15_signals = _m15_pullback_signals(
            m15,
            variant=variant,
            h1=h1,
            h1_closes=h1_closes,
            h1_indicators=h1_indicators,
        )
        execution_variant = _execution_variant(variant)
        signals = _confirmed_signals(
            m5,
            variant=execution_variant,
            m15_signals=m15_signals,
        )
        base = simulate_m5_trades(m5, signals=signals, costs=costs)
        stress = simulate_m5_trades(m5, signals=signals, costs=stressed_costs)
        base_sets[variant.variant_id] = base
        stress_sets[variant.variant_id] = stress
        signal_sets[variant.variant_id] = signals

        dev = tuple(
            trade for trade in base
            if trade.signal_index < split_index and trade.exit_index < split_index
        )
        dev_stress = tuple(
            trade for trade in stress
            if trade.signal_index < split_index and trade.exit_index < split_index
        )
        metrics = compute_metrics(dev)
        stress_metrics = compute_metrics(dev_stress)
        folds, pass_fraction, wf_passed = walk_forward(dev, validation_cfg["walk_forward"])
        stress_passed = _metrics_pass(stress_metrics, validation_cfg["stress_acceptance"])
        development_passed = bool(
            metrics.completed_trades >= MIN_DEVELOPMENT_TRADES
            and wf_passed
            and stress_passed
        )
        dev_signals = tuple(signal for signal in signals if signal.signal_index < split_index)
        by_direction = {
            direction: compute_metrics(
                tuple(trade for trade in dev if trade.direction == direction)
            ).payload()
            for direction in ("LONG", "SHORT")
        }
        evaluations.append(
            {
                "variant": asdict(variant),
                "m15_setup_signals": len(m15_signals),
                "m5_confirmed_signals": len(signals),
                "confirmation_rate": len(signals) / len(m15_signals) if m15_signals else 0.0,
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
                "development_coverage": _daily_coverage(development_rows, dev_signals),
            }
        )

    eligible = [row for row in evaluations if row["development_passed"]]
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
            if trade.signal_index >= split_index and trade.exit_index < len(m5)
        )
        stress = tuple(
            trade for trade in stress_sets[variant_id]
            if trade.signal_index >= split_index and trade.exit_index < len(m5)
        )
        base_metrics = compute_metrics(base)
        stress_metrics = compute_metrics(stress)
        holdout_signals = tuple(
            signal for signal in signal_sets[variant_id] if signal.signal_index >= split_index
        )
        promotion_eligible = bool(
            _final_oos_pass(base_metrics)
            and _metrics_pass(stress_metrics, validation_cfg["stress_acceptance"])
        )
        holdout = {
            "variant_id": variant_id,
            "base": base_metrics.payload(),
            "stressed": stress_metrics.payload(),
            "coverage": _daily_coverage(holdout_rows, holdout_signals),
            "passed": promotion_eligible,
        }

    return {
        "research_version": RESEARCH_VERSION,
        "symbol": SYMBOL,
        "input_timeframe": "M5",
        "m5_bars": len(m5),
        "m15_bars": len(m15),
        "h1_bars": len(h1),
        "variants": evaluations,
        "selected_variant": None if selected is None else selected["variant"]["variant_id"],
        "holdout": holdout,
        "promotion_eligible": promotion_eligible,
        "policy_effect": "SHADOW_ONLY",
        "execution_influence": False,
    }

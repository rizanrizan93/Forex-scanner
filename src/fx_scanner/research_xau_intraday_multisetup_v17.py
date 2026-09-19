from __future__ import annotations

from bisect import bisect_right
from dataclasses import asdict, dataclass
from datetime import timedelta
from statistics import median
from typing import Any, Mapping, Sequence

from .demo_donchian_adaptive_tournament import TournamentMetrics, compute_metrics, walk_forward
from .models import Bar, ensure_utc
from .research_xau_m15_continuation_tournament import (
    DEVELOPMENT_FRACTION,
    ContinuationSignal,
    _indicator_series,
    _metrics_pass,
)
from .research_xau_m15_dual_strategy import M15ResearchCosts
from .research_xau_m5_confirmation_v6 import (
    _aggregate_h1,
    _aggregate_m15,
    _validate_m5,
    simulate_m5_trades,
)

RESEARCH_VERSION = "XAU_INTRADAY_MULTISETUP_V17"
ARTIFACT_CONTRACT = "XAU_INTRADAY_MULTISETUP_V17_EVIDENCE_1"
SYMBOL = "XAUUSD"
EXECUTION_INFLUENCE = False
POLICY_EFFECT = "SHADOW_ONLY"

SETUP_SWEEP = "LIQUIDITY_SWEEP"
SETUP_BREAKOUT = "MOMENTUM_BREAKOUT"
SETUP_PULLBACK = "EMA_PULLBACK"
SETUP_FVG = "FVG_CONTINUATION"
SETUPS = (SETUP_SWEEP, SETUP_BREAKOUT, SETUP_PULLBACK, SETUP_FVG)

ROLL_OVER_HOUR_UTC = 21
LOOKBACK = 12
LOCAL_STOP_LOOKBACK = 6
STOP_BUFFER_ATR = 0.15
MIN_RISK_ATR = 0.35
D1_EMA_PERIOD = 200
D1_RETURN_LOOKBACK = 60

# The user wants roughly five executable opportunities per trading day. This is a
# research target, never a quota that forces low-quality broker orders.
DEVELOPMENT_FREQUENCY_FLOOR = {
    "mean_trades_per_day_min": 4.0,
    "days_ge_5_fraction_min": 0.30,
}
FINAL_FREQUENCY_TARGET = {
    "mean_trades_per_day_min": 5.0,
    "days_ge_5_fraction_min": 0.50,
}


@dataclass(frozen=True, slots=True)
class MultiSetupVariant:
    variant_id: str
    h1_adx_min: float
    require_d1_match: bool
    target_r: float
    cooldown_m5: int
    max_daily_trades: int
    selection_eligible: bool = True


VARIANTS = (
    MultiSetupVariant("XAU_V17_FREQ_H1ADX10_R100_C2_D8", 10.0, False, 1.00, 2, 8),
    MultiSetupVariant("XAU_V17_FREQ_H1ADX12_R110_C2_D8", 12.0, False, 1.10, 2, 8),
    MultiSetupVariant("XAU_V17_BAL_H1ADX15_R125_C3_D8", 15.0, False, 1.25, 3, 8),
    MultiSetupVariant("XAU_V17_D1_H1ADX12_R110_C2_D8", 12.0, True, 1.10, 2, 8),
    MultiSetupVariant("XAU_V17_D1_H1ADX15_R125_C3_D8", 15.0, True, 1.25, 3, 8),
    MultiSetupVariant("XAU_V17_D1_H1ADX15_R150_C4_D6", 15.0, True, 1.50, 4, 6),
)


def _daily_ohlc(m5: Sequence[Bar]) -> list[dict[str, Any]]:
    grouped: dict[Any, list[Bar]] = {}
    for row in m5:
        stamp = ensure_utc(row.timestamp)
        grouped.setdefault(stamp.date(), []).append(row)
    out: list[dict[str, Any]] = []
    for day in sorted(grouped):
        rows = sorted(grouped[day], key=lambda x: ensure_utc(x.timestamp))
        out.append({
            "date": day,
            "open": float(rows[0].open),
            "high": max(float(x.high) for x in rows),
            "low": min(float(x.low) for x in rows),
            "close": float(rows[-1].close),
        })
    return out


def _d1_regime_by_signal_date(m5: Sequence[Bar]) -> dict[Any, str | None]:
    daily = _daily_ohlc(m5)
    closes = [row["close"] for row in daily]
    ema: list[float | None] = [None] * len(daily)
    alpha = 2.0 / (D1_EMA_PERIOD + 1.0)
    running = None
    for i, value in enumerate(closes):
        running = value if running is None else alpha * value + (1.0 - alpha) * running
        if i >= D1_EMA_PERIOD - 1:
            ema[i] = float(running)

    completed_regime: dict[Any, str | None] = {}
    for i, row in enumerate(daily):
        direction = None
        if i >= max(D1_EMA_PERIOD - 1, D1_RETURN_LOOKBACK) and ema[i] is not None:
            ret60 = closes[i] / closes[i - D1_RETURN_LOOKBACK] - 1.0
            if closes[i] > float(ema[i]) and ret60 > 0:
                direction = "LONG"
            elif closes[i] < float(ema[i]) and ret60 < 0:
                direction = "SHORT"
        # A signal on the next trading date may use this completed D1 bar.
        if i + 1 < len(daily):
            completed_regime[daily[i + 1]["date"]] = direction
    return completed_regime


def _h1_context(
    *,
    signal_close,
    h1: Sequence[Bar],
    h1_closes,
    h1_indicators,
    adx_min: float,
) -> tuple[str | None, float | None]:
    count = bisect_right(h1_closes, signal_close)
    if count <= 0:
        return None, None
    i = count - 1
    if i < 200:
        return None, None
    ema20 = h1_indicators["ema20"][i]
    ema50 = h1_indicators["ema50"][i]
    adx = h1_indicators["adx"][i]
    plus_di = h1_indicators["plus_di"][i]
    minus_di = h1_indicators["minus_di"][i]
    if None in (ema20, ema50, adx, plus_di, minus_di):
        return None, None
    adx_f = float(adx)
    if adx_f < adx_min:
        return None, adx_f
    close = float(h1[i].close)
    long_ok = close > float(ema20) > float(ema50) and float(plus_di) > float(minus_di)
    short_ok = close < float(ema20) < float(ema50) and float(minus_di) > float(plus_di)
    if long_ok == short_ok:
        return None, adx_f
    return ("LONG" if long_ok else "SHORT"), adx_f


def _signal(
    *,
    variant: MultiSetupVariant,
    setup: str,
    index: int,
    row: Bar,
    direction: str,
    atr: float,
    stop: float,
) -> ContinuationSignal | None:
    risk = float(row.close) - stop if direction == "LONG" else stop - float(row.close)
    if risk < MIN_RISK_ATR * atr:
        return None
    return ContinuationSignal(
        variant_id=f"{variant.variant_id}:{setup}",
        signal_index=index,
        direction=direction,
        signal_at=ensure_utc(row.timestamp),
        atr=atr,
        breakout_level=float(row.close),
        structural_stop=float(stop),
        reward_r=float(variant.target_r),
        impulse_index=index,
        retest_index=index,
        fvg_low=None,
        fvg_high=None,
    )


def extract_multisetup_signals(
    bars: Sequence[Bar],
    *,
    variant: MultiSetupVariant,
) -> tuple[ContinuationSignal, ...]:
    rows = _validate_m5(bars)
    m5_ind = _indicator_series(rows)
    m15 = _aggregate_m15(rows)
    h1 = _aggregate_h1(m15)
    h1_closes = tuple(ensure_utc(row.timestamp) + timedelta(hours=1) for row in h1)
    h1_ind = _indicator_series(h1)
    d1_regime = _d1_regime_by_signal_date(rows)

    output: list[ContinuationSignal] = []
    last_signal_index = -10_000
    day_counts: dict[Any, int] = {}

    for i in range(max(220, LOOKBACK, LOCAL_STOP_LOOKBACK), len(rows) - 2):
        row = rows[i]
        stamp = ensure_utc(row.timestamp)
        if stamp.hour == ROLL_OVER_HOUR_UTC:
            continue
        if i - last_signal_index < variant.cooldown_m5:
            continue
        if day_counts.get(stamp.date(), 0) >= variant.max_daily_trades:
            continue

        atr_raw = m5_ind["atr"][i]
        ema20_raw = m5_ind["ema20"][i]
        ema50_raw = m5_ind["ema50"][i]
        if None in (atr_raw, ema20_raw, ema50_raw):
            continue
        atr = float(atr_raw)
        if atr <= 0:
            continue
        candle_range = float(row.high) - float(row.low)
        body = abs(float(row.close) - float(row.open))
        if candle_range <= 0:
            continue

        signal_close = stamp + timedelta(minutes=5)
        h1_bias, _ = _h1_context(
            signal_close=signal_close,
            h1=h1,
            h1_closes=h1_closes,
            h1_indicators=h1_ind,
            adx_min=variant.h1_adx_min,
        )
        d1_bias = d1_regime.get(stamp.date())

        prior = rows[i - LOOKBACK:i]
        local = rows[i - LOCAL_STOP_LOOKBACK + 1:i + 1]
        prior_high = max(float(x.high) for x in prior)
        prior_low = min(float(x.low) for x in prior)
        ema20 = float(ema20_raw)
        ema50 = float(ema50_raw)

        candidates: list[tuple[int, str, str, float]] = []

        # 1) Liquidity sweep/reclaim. Direction need not equal H1 bias, but a
        # directly opposed strong H1 trend is rejected.
        high_excess = (float(row.high) - prior_high) / atr
        low_excess = (prior_low - float(row.low)) / atr
        short_sweep = (
            0.05 <= high_excess <= 1.25
            and float(row.close) < prior_high
            and float(row.close) < float(row.open)
            and (float(row.high) - float(row.close)) / candle_range >= 0.55
            and h1_bias != "LONG"
        )
        long_sweep = (
            0.05 <= low_excess <= 1.25
            and float(row.close) > prior_low
            and float(row.close) > float(row.open)
            and (float(row.close) - float(row.low)) / candle_range >= 0.55
            and h1_bias != "SHORT"
        )
        if short_sweep:
            candidates.append((4, SETUP_SWEEP, "SHORT", float(row.high) + STOP_BUFFER_ATR * atr))
        if long_sweep:
            candidates.append((4, SETUP_SWEEP, "LONG", float(row.low) - STOP_BUFFER_ATR * atr))

        # 2) Momentum breakout with H1 directional confirmation.
        if body >= 0.50 * atr and h1_bias is not None:
            if (
                h1_bias == "LONG"
                and float(row.close) > prior_high
                and (float(row.close) - float(row.low)) / candle_range >= 0.70
            ):
                stop = min(float(x.low) for x in local) - STOP_BUFFER_ATR * atr
                candidates.append((3, SETUP_BREAKOUT, "LONG", stop))
            elif (
                h1_bias == "SHORT"
                and float(row.close) < prior_low
                and (float(row.high) - float(row.close)) / candle_range >= 0.70
            ):
                stop = max(float(x.high) for x in local) + STOP_BUFFER_ATR * atr
                candidates.append((3, SETUP_BREAKOUT, "SHORT", stop))

        # 3) EMA20 pullback/rejection in an established H1+M5 direction.
        if h1_bias == "LONG" and ema20 > ema50:
            touched = float(row.low) <= ema20 + 0.10 * atr
            accepted = float(row.close) > ema20 and float(row.close) > float(row.open)
            if touched and accepted and (float(row.close) - float(row.low)) / candle_range >= 0.60:
                stop = min(float(x.low) for x in local) - STOP_BUFFER_ATR * atr
                candidates.append((2, SETUP_PULLBACK, "LONG", stop))
        elif h1_bias == "SHORT" and ema20 < ema50:
            touched = float(row.high) >= ema20 - 0.10 * atr
            accepted = float(row.close) < ema20 and float(row.close) < float(row.open)
            if touched and accepted and (float(row.high) - float(row.close)) / candle_range >= 0.60:
                stop = max(float(x.high) for x in local) + STOP_BUFFER_ATR * atr
                candidates.append((2, SETUP_PULLBACK, "SHORT", stop))

        # 4) Three-candle fair-value-gap/displacement continuation.
        if i >= 2 and body >= 0.60 * atr and h1_bias is not None:
            two_back = rows[i - 2]
            if (
                h1_bias == "LONG"
                and float(row.low) > float(two_back.high)
                and float(row.close) > float(row.open)
            ):
                stop = min(float(row.low), float(rows[i - 1].low)) - STOP_BUFFER_ATR * atr
                candidates.append((1, SETUP_FVG, "LONG", stop))
            elif (
                h1_bias == "SHORT"
                and float(row.high) < float(two_back.low)
                and float(row.close) < float(row.open)
            ):
                stop = max(float(row.high), float(rows[i - 1].high)) + STOP_BUFFER_ATR * atr
                candidates.append((1, SETUP_FVG, "SHORT", stop))

        if not candidates:
            continue

        # Prefer the more structurally specific setup if multiple families trigger
        # on the same completed M5 candle.
        candidates.sort(reverse=True)
        _, setup, direction, stop = candidates[0]
        if variant.require_d1_match and d1_bias != direction:
            continue

        signal = _signal(
            variant=variant,
            setup=setup,
            index=i,
            row=row,
            direction=direction,
            atr=atr,
            stop=stop,
        )
        if signal is None:
            continue
        output.append(signal)
        day_counts[stamp.date()] = day_counts.get(stamp.date(), 0) + 1
        last_signal_index = i

    return tuple(output)


def _frequency(
    *,
    rows: Sequence[Bar],
    trades,
    start_index: int,
    end_index: int,
) -> dict[str, Any]:
    eligible_dates = sorted({
        ensure_utc(rows[i].timestamp).date()
        for i in range(max(0, start_index), min(len(rows), end_index))
        if ensure_utc(rows[i].timestamp).hour != ROLL_OVER_HOUR_UTC
    })
    counts = {day: 0 for day in eligible_dates}
    for trade in trades:
        day = ensure_utc(trade.entry_at).date()
        if day in counts:
            counts[day] += 1
    vals = list(counts.values())
    if not vals:
        return {
            "trading_days": 0,
            "total_trades": 0,
            "mean_trades_per_day": 0.0,
            "median_trades_per_day": 0.0,
            "days_ge_5": 0,
            "days_ge_5_fraction": 0.0,
            "zero_trade_days": 0,
            "max_trades_in_day": 0,
        }
    return {
        "trading_days": len(vals),
        "total_trades": int(sum(vals)),
        "mean_trades_per_day": float(sum(vals) / len(vals)),
        "median_trades_per_day": float(median(vals)),
        "days_ge_5": int(sum(v >= 5 for v in vals)),
        "days_ge_5_fraction": float(sum(v >= 5 for v in vals) / len(vals)),
        "zero_trade_days": int(sum(v == 0 for v in vals)),
        "max_trades_in_day": int(max(vals)),
    }


def _frequency_pass(freq: Mapping[str, Any], gate: Mapping[str, float]) -> bool:
    return bool(
        float(freq["mean_trades_per_day"]) >= float(gate["mean_trades_per_day_min"])
        and float(freq["days_ge_5_fraction"]) >= float(gate["days_ge_5_fraction_min"])
    )


def _by_setup(trades) -> dict[str, Any]:
    out = {}
    for setup in SETUPS:
        subset = tuple(t for t in trades if str(t.strategy_id).endswith(f":{setup}"))
        out[setup] = compute_metrics(subset).payload()
    return out


def _final_quality_pass(metrics: TournamentMetrics) -> bool:
    return bool(
        metrics.completed_trades >= 100
        and metrics.win_rate is not None
        and metrics.win_rate >= 0.50
        and metrics.profit_factor is not None
        and metrics.profit_factor >= 1.10
        and metrics.expectancy_r is not None
        and metrics.expectancy_r >= 0.05
    )


def evaluate_intraday_multisetup_v17(
    bars: Sequence[Bar],
    *,
    costs: M15ResearchCosts,
    stressed_costs: M15ResearchCosts,
    validation_cfg: Mapping[str, Any],
) -> dict[str, Any]:
    rows = _validate_m5(bars)
    split_index = max(20_000, min(len(rows) - 1, int(len(rows) * DEVELOPMENT_FRACTION)))
    evaluations = []
    base_sets = {}
    stress_sets = {}
    signal_sets = {}

    for variant in VARIANTS:
        signals = extract_multisetup_signals(rows, variant=variant)
        base = simulate_m5_trades(rows, signals=signals, costs=costs)
        stress = simulate_m5_trades(rows, signals=signals, costs=stressed_costs)
        base_sets[variant.variant_id] = base
        stress_sets[variant.variant_id] = stress
        signal_sets[variant.variant_id] = signals

        dev = tuple(t for t in base if t.signal_index < split_index and t.exit_index < split_index)
        dev_stress = tuple(t for t in stress if t.signal_index < split_index and t.exit_index < split_index)
        metrics = compute_metrics(dev)
        stress_metrics = compute_metrics(dev_stress)
        folds, pass_fraction, wf_passed = walk_forward(dev, validation_cfg["walk_forward"])
        stress_passed = _metrics_pass(stress_metrics, validation_cfg["stress_acceptance"])
        freq = _frequency(rows=rows, trades=dev, start_index=220, end_index=split_index)
        freq_floor_passed = _frequency_pass(freq, DEVELOPMENT_FREQUENCY_FLOOR)
        development_passed = bool(
            metrics.completed_trades >= 300
            and wf_passed
            and stress_passed
            and freq_floor_passed
        )
        evaluations.append({
            "variant": asdict(variant),
            "signals_total": len(signals),
            "development": metrics.payload(),
            "development_stressed": stress_metrics.payload(),
            "development_by_setup": _by_setup(dev),
            "development_frequency": freq,
            "frequency_floor_passed": freq_floor_passed,
            "walk_forward": {
                "folds": [
                    {
                        "fold": f.fold,
                        "train_trades": f.train_trades,
                        "test_trades": f.test_trades,
                        "passed": f.passed,
                        "test_metrics": f.test_metrics.payload(),
                    }
                    for f in folds
                ],
                "pass_fraction": pass_fraction,
                "passed": wf_passed,
            },
            "stress_passed": stress_passed,
            "development_passed": development_passed,
        })

    eligible = [x for x in evaluations if x["development_passed"] and x["variant"]["selection_eligible"]]
    eligible.sort(
        key=lambda x: (
            float(x["walk_forward"]["pass_fraction"]),
            float(x["development_frequency"]["days_ge_5_fraction"]),
            float(x["development_frequency"]["mean_trades_per_day"]),
            float(x["development_stressed"].get("expectancy_r") or -999.0),
            float(x["development_stressed"].get("profit_factor") or -999.0),
        ),
        reverse=True,
    )
    selected = eligible[0] if eligible else None
    holdout = None
    promotion_eligible = False

    if selected is not None:
        variant_id = str(selected["variant"]["variant_id"])
        base = tuple(t for t in base_sets[variant_id] if t.signal_index >= split_index)
        stress = tuple(t for t in stress_sets[variant_id] if t.signal_index >= split_index)
        base_metrics = compute_metrics(base)
        stress_metrics = compute_metrics(stress)
        freq = _frequency(rows=rows, trades=base, start_index=split_index, end_index=len(rows))
        quality_pass = _final_quality_pass(stress_metrics)
        frequency_target_pass = _frequency_pass(freq, FINAL_FREQUENCY_TARGET)
        promotion_eligible = bool(quality_pass and frequency_target_pass)
        holdout = {
            "variant_id": variant_id,
            "base": base_metrics.payload(),
            "stressed": stress_metrics.payload(),
            "by_setup": _by_setup(base),
            "frequency": freq,
            "quality_pass": quality_pass,
            "frequency_target_pass": frequency_target_pass,
            "passed": promotion_eligible,
        }

    return {
        "research_version": RESEARCH_VERSION,
        "symbol": SYMBOL,
        "input_timeframe": "M5",
        "m5_bars": len(rows),
        "development_bars": split_index,
        "holdout_bars": len(rows) - split_index,
        "setup_families": list(SETUPS),
        "development_frequency_floor": DEVELOPMENT_FREQUENCY_FLOOR,
        "final_frequency_target": FINAL_FREQUENCY_TARGET,
        "variants": evaluations,
        "selected_variant": None if selected is None else selected["variant"]["variant_id"],
        "holdout": holdout,
        "promotion_eligible": promotion_eligible,
        "policy_effect": POLICY_EFFECT,
        "execution_influence": EXECUTION_INFLUENCE,
        "live_execution_enabled": False,
        "frequency_note": (
            "Five trades/day is measured as a research coverage target. The engine never fabricates "
            "a signal merely to satisfy the quota."
        ),
    }

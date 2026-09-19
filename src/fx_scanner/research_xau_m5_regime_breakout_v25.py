from __future__ import annotations

from bisect import bisect_right
from dataclasses import asdict, dataclass
from datetime import timedelta
from math import isfinite
from typing import Any, Mapping, Sequence

import numpy as np

from .demo_donchian_adaptive_tournament import compute_metrics, walk_forward
from .models import Bar, ensure_utc
from .research_multisymbol_m15_breakout_v18 import _frequency
from .research_xau_m15_continuation_tournament import ContinuationSignal, _indicator_series
from .research_xau_m15_dual_strategy import M15ResearchCosts
from .research_xau_m5_confirmation_v6 import (
    _aggregate_h1,
    _aggregate_m15,
    _validate_m5,
    simulate_m5_trades,
)

RESEARCH_VERSION = "XAU_M5_REGIME_BREAKOUT_V25"
ARTIFACT_CONTRACT = "XAU_M5_REGIME_BREAKOUT_V25_EVIDENCE_1"
SYMBOL = "XAUUSD"
EXECUTION_INFLUENCE = False
POLICY_EFFECT = "SHADOW_ONLY"
DIAGNOSTIC_ONLY = True

MIN_RISK_ATR = 0.40
STOP_BUFFER_ATR = 0.15
LOCAL_STOP_LOOKBACK = 5
FINAL_TARGET_MEAN_TRADES_PER_DAY = 5.0


@dataclass(frozen=True, slots=True)
class M5RegimeVariant:
    variant_id: str
    breakout_lookback: int
    body_atr_min: float
    target_r: float
    cooldown_bars: int
    h1_adx_min: float
    m15_adx_min: float
    d1_mode: str
    m15_mode: str
    liquid_session_only: bool = False


VARIANTS = (
    M5RegimeVariant("V25_N6_SOFT_SOFT_R100", 6, 0.35, 1.00, 2, 10.0, 8.0, "NOT_OPPOSED", "NOT_OPPOSED"),
    M5RegimeVariant("V25_N8_SOFT_SOFT_R125", 8, 0.40, 1.25, 2, 12.0, 8.0, "NOT_OPPOSED", "NOT_OPPOSED"),
    M5RegimeVariant("V25_N12_SOFT_SOFT_R150", 12, 0.45, 1.50, 3, 12.0, 10.0, "NOT_OPPOSED", "NOT_OPPOSED"),
    M5RegimeVariant("V25_N8_MATCH_SOFT_R125", 8, 0.40, 1.25, 2, 12.0, 8.0, "MATCH", "NOT_OPPOSED"),
    M5RegimeVariant("V25_N12_MATCH_MATCH_R150", 12, 0.45, 1.50, 3, 15.0, 10.0, "MATCH", "MATCH"),
    M5RegimeVariant("V25_N20_MATCH_MATCH_R200", 20, 0.50, 2.00, 4, 15.0, 12.0, "MATCH", "MATCH"),
    M5RegimeVariant("V25_N8_SOFT_MATCH_R125_LIQ", 8, 0.40, 1.25, 2, 12.0, 8.0, "NOT_OPPOSED", "MATCH", True),
    M5RegimeVariant("V25_N12_MATCH_MATCH_R150_LIQ", 12, 0.45, 1.50, 3, 15.0, 10.0, "MATCH", "MATCH", True),
)


def _daily_regime(m5: Sequence[Bar]) -> dict[Any, str | None]:
    grouped: dict[Any, list[Bar]] = {}
    for row in m5:
        grouped.setdefault(ensure_utc(row.timestamp).date(), []).append(row)
    days = sorted(grouped)
    closes = [float(sorted(grouped[d], key=lambda x: ensure_utc(x.timestamp))[-1].close) for d in days]
    ema = [None] * len(days)
    alpha = 2.0 / 201.0
    running = None
    for i, close in enumerate(closes):
        running = close if running is None else alpha * close + (1.0 - alpha) * running
        if i >= 199:
            ema[i] = float(running)

    completed = [None] * len(days)
    for i in range(len(days)):
        if i < 199 or i < 60 or ema[i] is None:
            continue
        ret60 = closes[i] / closes[i - 60] - 1.0
        if closes[i] > float(ema[i]) and ret60 > 0:
            completed[i] = "LONG"
        elif closes[i] < float(ema[i]) and ret60 < 0:
            completed[i] = "SHORT"

    mapping: dict[Any, str | None] = {}
    for i in range(1, len(days)):
        mapping[days[i]] = completed[i - 1]
    return mapping


def _context_direction(
    *,
    close_time,
    bars: Sequence[Bar],
    closes,
    indicators,
    adx_min: float,
) -> tuple[str | None, float | None]:
    count = bisect_right(closes, close_time)
    if count <= 0:
        return None, None
    i = count - 1
    if i < 60:
        return None, None
    vals = (
        indicators["ema20"][i],
        indicators["ema50"][i],
        indicators["adx"][i],
        indicators["plus_di"][i],
        indicators["minus_di"][i],
    )
    if any(v is None for v in vals):
        return None, None
    ema20, ema50, adx, plus_di, minus_di = (float(v) for v in vals)
    close = float(bars[i].close)
    if adx < adx_min:
        return None, adx
    long_ok = close > ema20 > ema50 and plus_di > minus_di
    short_ok = close < ema20 < ema50 and minus_di > plus_di
    if long_ok == short_ok:
        return None, adx
    return ("LONG" if long_ok else "SHORT"), adx


def _mode_accept(mode: str, context: str | None, direction: str) -> bool:
    if mode == "MATCH":
        return context == direction
    if mode == "NOT_OPPOSED":
        opposite = "SHORT" if direction == "LONG" else "LONG"
        return context != opposite
    raise ValueError(f"V25_CONTEXT_MODE_INVALID:{mode}")


def extract_signals(
    bars: Sequence[Bar],
    *,
    variant: M5RegimeVariant,
) -> tuple[ContinuationSignal, ...]:
    m5 = _validate_m5(bars)
    m5_ind = _indicator_series(m5)
    m15 = _aggregate_m15(m5)
    h1 = _aggregate_h1(m15)
    m15_ind = _indicator_series(m15)
    h1_ind = _indicator_series(h1)
    m15_closes = tuple(ensure_utc(x.timestamp) + timedelta(minutes=15) for x in m15)
    h1_closes = tuple(ensure_utc(x.timestamp) + timedelta(hours=1) for x in h1)
    d1 = _daily_regime(m5)

    output: list[ContinuationSignal] = []
    last_i = -10_000
    warmup = max(250, variant.breakout_lookback + 5)

    for i in range(warmup, len(m5) - 2):
        if i - last_i < variant.cooldown_bars:
            continue
        row = m5[i]
        stamp = ensure_utc(row.timestamp)
        if stamp.hour == 21:
            continue
        if variant.liquid_session_only and not (7 <= stamp.hour < 21):
            continue

        atr_raw = m5_ind["atr"][i]
        if atr_raw is None:
            continue
        atr = float(atr_raw)
        if atr <= 0:
            continue

        signal_close = stamp + timedelta(minutes=5)
        h1_direction, _ = _context_direction(
            close_time=signal_close,
            bars=h1,
            closes=h1_closes,
            indicators=h1_ind,
            adx_min=variant.h1_adx_min,
        )
        if h1_direction is None:
            continue

        m15_direction, _ = _context_direction(
            close_time=signal_close,
            bars=m15,
            closes=m15_closes,
            indicators=m15_ind,
            adx_min=variant.m15_adx_min,
        )

        prior = m5[i - variant.breakout_lookback:i]
        upper = max(float(x.high) for x in prior)
        lower = min(float(x.low) for x in prior)
        rng = float(row.high) - float(row.low)
        body = abs(float(row.close) - float(row.open))
        if rng <= 0 or body < variant.body_atr_min * atr:
            continue

        direction = None
        if (
            h1_direction == "LONG"
            and float(row.close) > upper
            and float(row.close) > float(row.open)
            and (float(row.close) - float(row.low)) / rng >= 0.68
        ):
            direction = "LONG"
        elif (
            h1_direction == "SHORT"
            and float(row.close) < lower
            and float(row.close) < float(row.open)
            and (float(row.high) - float(row.close)) / rng >= 0.68
        ):
            direction = "SHORT"
        if direction is None:
            continue

        if not _mode_accept(variant.m15_mode, m15_direction, direction):
            continue
        if not _mode_accept(variant.d1_mode, d1.get(stamp.date()), direction):
            continue

        local = m5[max(0, i - LOCAL_STOP_LOOKBACK + 1):i + 1]
        if direction == "LONG":
            stop = min(float(x.low) for x in local) - STOP_BUFFER_ATR * atr
            risk = float(row.close) - stop
        else:
            stop = max(float(x.high) for x in local) + STOP_BUFFER_ATR * atr
            risk = stop - float(row.close)
        if not isfinite(risk) or risk < MIN_RISK_ATR * atr:
            continue

        output.append(
            ContinuationSignal(
                variant_id=variant.variant_id,
                signal_index=i,
                direction=direction,
                signal_at=stamp,
                atr=atr,
                breakout_level=float(row.close),
                structural_stop=float(stop),
                reward_r=float(variant.target_r),
                impulse_index=i,
                retest_index=i,
                fvg_low=None,
                fvg_high=None,
            )
        )
        last_i = i

    return tuple(output)


def _trading_dates(rows: Sequence[Bar], start: int, end: int) -> list[Any]:
    return sorted({
        ensure_utc(rows[i].timestamp).date()
        for i in range(max(0, start), min(len(rows), end))
        if ensure_utc(rows[i].timestamp).hour != 21
    })


def _dev_gate(metrics, wf: Mapping[str, Any], freq: Mapping[str, Any]) -> bool:
    return bool(
        metrics.completed_trades >= 300
        and metrics.profit_factor is not None
        and metrics.profit_factor >= 1.05
        and metrics.expectancy_r is not None
        and metrics.expectancy_r >= 0.02
        and float(wf["pass_fraction"]) >= 0.50
        and float(freq["mean_trades_per_day"]) >= 2.0
    )


def evaluate_v25(
    bars: Sequence[Bar],
    *,
    costs: M15ResearchCosts,
    stressed_costs: M15ResearchCosts,
    validation_cfg: Mapping[str, Any],
) -> dict[str, Any]:
    m5 = _validate_m5(bars)
    split = max(50_000, min(len(m5) - 1, int(len(m5) * 0.75)))
    dev_dates = _trading_dates(m5, 250, split)
    hold_dates = _trading_dates(m5, split, len(m5))

    evaluations = []
    base_sets = {}
    stress_sets = {}

    for variant in VARIANTS:
        signals = extract_signals(m5, variant=variant)
        base = simulate_m5_trades(m5, signals=signals, costs=costs)
        stress = simulate_m5_trades(m5, signals=signals, costs=stressed_costs)
        base_sets[variant.variant_id] = base
        stress_sets[variant.variant_id] = stress

        dev_base = tuple(t for t in base if t.signal_index < split and t.exit_index < split)
        dev_stress = tuple(t for t in stress if t.signal_index < split and t.exit_index < split)
        dm = compute_metrics(dev_base)
        dms = compute_metrics(dev_stress)
        folds, pass_fraction, wf_passed = walk_forward(
            dev_base,
            validation_cfg["walk_forward"],
        )
        wf = {
            "pass_fraction": pass_fraction,
            "passed": wf_passed,
            "folds": [
                {
                    "fold": f.fold,
                    "test_trades": f.test_trades,
                    "passed": f.passed,
                    "test_metrics": f.test_metrics.payload(),
                }
                for f in folds
            ],
        }
        freq = _frequency(dev_base, dev_dates)
        evaluations.append({
            "variant": asdict(variant),
            "signals_total": len(signals),
            "development_base": dm.payload(),
            "development_stressed": dms.payload(),
            "development_frequency": freq,
            "walk_forward": wf,
            "development_passed": _dev_gate(dms, wf, freq),
        })

    eligible = [x for x in evaluations if x["development_passed"]]
    eligible.sort(
        key=lambda x: (
            float(x["walk_forward"]["pass_fraction"]),
            float(x["development_stressed"]["expectancy_r"]),
            float(x["development_stressed"]["profit_factor"]),
            float(x["development_frequency"]["mean_trades_per_day"]),
        ),
        reverse=True,
    )
    selected = eligible[0] if eligible else None
    holdout = None

    if selected is not None:
        variant_id = selected["variant"]["variant_id"]
        hb = tuple(t for t in base_sets[variant_id] if t.signal_index >= split)
        hs = tuple(t for t in stress_sets[variant_id] if t.signal_index >= split)
        hbm = compute_metrics(hb)
        hsm = compute_metrics(hs)
        freq = _frequency(hb, hold_dates)
        holdout = {
            "variant_id": variant_id,
            "base": hbm.payload(),
            "stressed": hsm.payload(),
            "frequency": freq,
            "quality_positive": bool(
                hsm.completed_trades >= 100
                and hsm.profit_factor is not None
                and hsm.profit_factor > 1.0
                and hsm.expectancy_r is not None
                and hsm.expectancy_r > 0.0
            ),
            "five_per_day_reached": bool(
                freq["mean_trades_per_day"] >= FINAL_TARGET_MEAN_TRADES_PER_DAY
            ),
        }

    return {
        "research_version": RESEARCH_VERSION,
        "policy_effect": POLICY_EFFECT,
        "execution_influence": EXECUTION_INFLUENCE,
        "live_execution_enabled": False,
        "diagnostic_only": DIAGNOSTIC_ONLY,
        "promotion_eligible": False,
        "symbol": SYMBOL,
        "m5_bars": len(m5),
        "development_bars": split,
        "holdout_bars": len(m5) - split,
        "variants": evaluations,
        "selected_variant": None if selected is None else selected["variant"]["variant_id"],
        "holdout": holdout,
        "frequency_target_mean_trades_per_day": FINAL_TARGET_MEAN_TRADES_PER_DAY,
        "selection_note": (
            "V25 reuses only momentum breakout. D1/H1/M15 filters are point-in-time. "
            "Prior M5 holdout knowledge makes this diagnostic-only regardless of metrics."
        ),
    }

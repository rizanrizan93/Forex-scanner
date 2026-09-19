from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import timedelta
from math import isfinite
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from .demo_donchian_adaptive_tournament import TournamentTrade, compute_metrics
from .demo_xau_m15_ema_reversal_recovery import _ema
from .demo_xau_m15_liquidity_sweep_fade import (
    EMA_CONTEXT_PERIOD,
    IMPULSE_LOOKBACK,
    SWEEP_LOOKBACK,
    _long_candidate,
)
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

RESEARCH_VERSION = "XAU_WVF_LIQUIDITY_MSS_V49"
ARTIFACT_CONTRACT = "XAU_WVF_LIQUIDITY_MSS_V49_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
PROMOTION_ELIGIBLE = False
DIAGNOSTIC_ONLY = True

WVF_LOOKBACK_H1 = 22
WVF_PERCENTILE_WINDOW = 50
WVF_PERCENTILE = 0.85
TARGET_R = 1.80
MAX_HOLD_BARS = 32
MSS_CONFIRM_BARS = 4
COST_R_CAP = 0.10

VARIANTS = (
    "SWEEP_RECLAIM_LONG_CONTROL",
    "WVF_SWEEP_RECLAIM_LONG",
    "WVF_SWEEP_MSS_LONG",
    "WVF_SWEEP_MSS_D1_NONBEAR_LONG",
    "WVF_SWEEP_MSS_D1_BULL_LONG",
)


@dataclass(frozen=True, slots=True)
class V49Signal:
    variant_id: str
    signal_index: int
    signal_at: Any
    atr: float
    structural_stop: float
    signal_high: float
    wvf: float | None
    wvf_threshold: float | None
    d1_side: int


def _wilder_atr_series(rows: Sequence[Bar], period: int = 14) -> list[float | None]:
    out: list[float | None] = [None] * len(rows)
    if not rows:
        return out
    trs: list[float] = []
    for i, row in enumerate(rows):
        if i == 0:
            tr = float(row.high) - float(row.low)
        else:
            prev = float(rows[i - 1].close)
            tr = max(
                float(row.high) - float(row.low),
                abs(float(row.high) - prev),
                abs(float(row.low) - prev),
            )
        trs.append(tr)

    value = trs[0]
    alpha = 1.0 / float(period)
    for i in range(1, len(trs)):
        value = alpha * trs[i] + (1.0 - alpha) * value
        if i >= period - 1:
            out[i] = float(value)
    return out


def build_h1_wvf_context(rows: Sequence[Bar]) -> pd.DataFrame:
    h1 = _resample_completed(rows, "1h").copy()
    highest = h1["close"].rolling(WVF_LOOKBACK_H1, min_periods=WVF_LOOKBACK_H1).max()
    h1["wvf"] = (highest - h1["low"]) / highest.replace(0.0, np.nan) * 100.0
    h1["wvf_threshold"] = (
        h1["wvf"]
        .shift(1)
        .rolling(WVF_PERCENTILE_WINDOW, min_periods=WVF_PERCENTILE_WINDOW)
        .quantile(WVF_PERCENTILE)
    )
    h1["wvf_extreme"] = (
        np.isfinite(h1["wvf"])
        & np.isfinite(h1["wvf_threshold"])
        & (h1["wvf"] >= h1["wvf_threshold"])
    )
    return h1


def _variant_requires_wvf(variant: str) -> bool:
    return variant != "SWEEP_RECLAIM_LONG_CONTROL"


def _variant_requires_mss(variant: str) -> bool:
    return "MSS" in variant


def _variant_d1_ok(variant: str, d1_side: int) -> bool:
    if variant == "WVF_SWEEP_MSS_D1_BULL_LONG":
        return d1_side == 1
    if variant == "WVF_SWEEP_MSS_D1_NONBEAR_LONG":
        return d1_side != -1
    return True


def extract_signals(
    rows: Sequence[Bar],
    *,
    variant: str,
) -> tuple[V49Signal, ...]:
    if variant not in VARIANTS:
        raise ValueError(f"V49_VARIANT_INVALID:{variant}")
    bars = tuple(sorted(rows, key=lambda x: ensure_utc(x.timestamp)))
    if not bars:
        return ()

    atrs = _wilder_atr_series(bars, 14)
    emas = _ema([float(x.close) for x in bars], EMA_CONTEXT_PERIOD)
    h1 = build_h1_wvf_context(bars)
    d1 = build_d1_context(bars)
    h1_lookup = _Asof(h1)
    d1_lookup = _Asof(d1)

    minimum = max(EMA_CONTEXT_PERIOD + 5, SWEEP_LOOKBACK + IMPULSE_LOOKBACK + 5)
    out: list[V49Signal] = []
    for i in range(minimum, len(bars) - 1):
        atr = atrs[i]
        ema20 = emas[i]
        if atr is None or ema20 is None or not isfinite(float(atr)) or float(atr) <= 0.0:
            continue

        # The M15 candle is known only at its close.
        signal_at = ensure_utc(bars[i].timestamp) + timedelta(minutes=15)
        h1_row = h1_lookup.row(signal_at)
        d1_row = d1_lookup.row(signal_at)
        if h1_row is None or d1_row is None:
            continue

        d1_side = int(d1_row.get("regime_side") or 0)
        if not _variant_d1_ok(variant, d1_side):
            continue

        wvf = float(h1_row.get("wvf", np.nan))
        threshold = float(h1_row.get("wvf_threshold", np.nan))
        extreme = bool(h1_row.get("wvf_extreme", False))
        if _variant_requires_wvf(variant) and not extreme:
            continue

        local = bars[max(0, i - 32): i + 1]
        passed, metrics, _failed = _long_candidate(
            local,
            row=bars[i],
            atr=float(atr),
            ema20=float(ema20),
        )
        if not passed:
            continue

        out.append(
            V49Signal(
                variant_id=variant,
                signal_index=i,
                signal_at=signal_at,
                atr=float(atr),
                structural_stop=float(metrics["structural_stop"]),
                signal_high=float(bars[i].high),
                wvf=None if not isfinite(wvf) else wvf,
                wvf_threshold=None if not isfinite(threshold) else threshold,
                d1_side=d1_side,
            )
        )
    return tuple(out)


def _entry_for_signal(
    bars: Sequence[Bar],
    sig: V49Signal,
    *,
    require_mss: bool,
) -> tuple[int, float] | None:
    if not require_mss:
        i = sig.signal_index + 1
        if i >= len(bars):
            return None
        return i, float(bars[i].open)

    trigger = float(sig.signal_high)
    for i in range(sig.signal_index + 1, min(len(bars), sig.signal_index + 1 + MSS_CONFIRM_BARS)):
        if float(bars[i].high) >= trigger:
            return i, trigger
    return None


def simulate(
    rows: Sequence[Bar],
    *,
    signals: Sequence[V49Signal],
    costs: M15ResearchCosts,
    pip_size: float,
) -> tuple[TournamentTrade, ...]:
    bars = tuple(sorted(rows, key=lambda x: ensure_utc(x.timestamp)))
    out: list[TournamentTrade] = []

    for sig in signals:
        found = _entry_for_signal(
            bars,
            sig,
            require_mss=_variant_requires_mss(sig.variant_id),
        )
        if found is None:
            continue
        entry_i, entry = found
        stop = float(sig.structural_stop)
        risk = entry - stop
        if not isfinite(risk) or risk <= 0.0:
            continue
        risk_pips = risk / float(pip_size)
        if risk_pips <= 0.0:
            continue

        # Economic viability learned in V43, applied ex-ante.
        entry_cost_r = _cost_r(risk_pips=risk_pips, bars_held=0, costs=costs)
        if entry_cost_r > COST_R_CAP:
            continue

        target = entry + TARGET_R * risk
        last_i = min(len(bars) - 1, entry_i + MAX_HOLD_BARS)
        trade = None

        for j in range(entry_i, last_i + 1):
            bar = bars[j]
            stop_hit = float(bar.low) <= stop
            target_hit = float(bar.high) >= target
            raw_target = target_hit

            # Conservative convention on breakout-entry bar: target cannot be
            # credited immediately, but stop can.
            if j == entry_i:
                target_hit = False

            held = j - entry_i
            cost = _cost_r(risk_pips=risk_pips, bars_held=held, costs=costs)
            if stop_hit:
                gross = -1.0
                trade = TournamentTrade(
                    sig.variant_id,
                    "XAUUSD",
                    "LONG",
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
                    sig.variant_id,
                    "XAUUSD",
                    "LONG",
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
            bar = bars[last_i]
            exit_price = float(bar.close)
            gross = (exit_price - entry) / risk
            cost = _cost_r(risk_pips=risk_pips, bars_held=MAX_HOLD_BARS, costs=costs)
            trade = TournamentTrade(
                sig.variant_id,
                "XAUUSD",
                "LONG",
                ensure_utc(sig.signal_at),
                ensure_utc(bars[entry_i].timestamp),
                ensure_utc(bar.timestamp),
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


def evaluate_v49(
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
        raise ValueError("V49_EMPTY_HISTORY")
    start = ensure_utc(era_start)
    end = ensure_utc(era_end)
    dates = _trading_dates(rows, start=start, end=end)
    trading_days = len(dates)

    signal_map = {
        variant: extract_signals(rows, variant=variant)
        for variant in VARIANTS
    }
    scenarios: dict[str, Any] = {}
    for cost_id, costs in cost_scenarios.items():
        result: dict[str, Any] = {}
        for variant in VARIANTS:
            trades = _period(
                simulate(
                    rows,
                    signals=signal_map[variant],
                    costs=costs,
                    pip_size=pip_size,
                ),
                start=start,
                end=end,
            )
            result[variant] = _stats(trades, trading_days)
        scenarios[cost_id] = {
            "costs": asdict(costs),
            "variants": result,
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
        "preregistered_contract": {
            "long_only": True,
            "reason_long_only": "Williams VIX Fix evidence is materially stronger for bottoms/longs than tops/shorts",
            "wvf_formula": "(highest H1 close 22 - H1 low) / highest H1 close 22 * 100",
            "wvf_threshold": "current WVF >= prior-50-H1 85th percentile",
            "liquidity_sweep_logic": "frozen XAU_M15_LIQUIDITY_SWEEP_FADE_V1 long candidate",
            "mss_confirmation": "signal high must break within next 4 M15 bars for MSS variants",
            "target_r": TARGET_R,
            "max_hold_m15_bars": MAX_HOLD_BARS,
            "entry_cost_r_cap": COST_R_CAP,
            "parameter_grid_search": False,
            "selection_uses_future_outcomes": False,
            "execution_authority": False,
        },
        "variants": list(VARIANTS),
        "scenario_results": scenarios,
        "note": (
            "V49 tests Williams VIX-Fix as a capitulation state, never as a standalone entry. "
            "M15 sell-side liquidity sweep/reclaim provides price-action confirmation; MSS variants "
            "require a subsequent structural break before entry."
        ),
    }

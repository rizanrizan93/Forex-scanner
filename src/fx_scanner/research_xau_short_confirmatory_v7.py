from __future__ import annotations

from dataclasses import asdict
from typing import Any, Mapping, Sequence

from .demo_donchian_adaptive_tournament import compute_metrics
from .models import Bar
from .research_xau_m15_continuation_tournament import (
    DEVELOPMENT_FRACTION,
    FINAL_OOS_EXPECTANCY_R_MIN,
    FINAL_OOS_PROFIT_FACTOR_MIN,
    FINAL_OOS_WIN_RATE_MIN,
    MIN_HOLDOUT_TRADES,
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
    _m15_signal_pool,
    _validate_m5,
    simulate_m5_trades,
)
from .models import ensure_utc
from datetime import timedelta

RESEARCH_VERSION = "XAU_SHORT_CONFIRMATORY_V7"
ARTIFACT_CONTRACT = "XAU_SHORT_CONFIRMATORY_V7_EVIDENCE_1"
SYMBOL = "XAUUSD"

FROZEN_VARIANT = M5Variant(
    variant_id="XAU_V7_US_SHORT_NOHTF_BASIC_M15STOP_R125",
    long_filter=None,
    long_target_r=None,
    short_filter="NONE",
    short_target_r=1.25,
    trigger_mode="BASIC_BREAK",
    stop_mode="M15",
    selection_eligible=False,
)


def evaluate_short_confirmatory_v7(
    bars: Sequence[Bar],
    *,
    costs: M15ResearchCosts,
    stressed_costs: M15ResearchCosts,
    validation_cfg: Mapping[str, Any],
) -> dict[str, Any]:
    m5 = _validate_m5(bars)
    split_index = max(5000, min(len(m5) - 1, int(len(m5) * DEVELOPMENT_FRACTION)))
    holdout_rows = m5[split_index:]
    m15 = _aggregate_m15(m5)
    h1 = _aggregate_h1(m15)
    h1_closes = tuple(ensure_utc(row.timestamp) + timedelta(hours=1) for row in h1)
    h1_indicators = _indicator_series(h1)

    m15_signals, filter_evidence = _m15_signal_pool(
        m15,
        variant=FROZEN_VARIANT,
        h1=h1,
        h1_closes=h1_closes,
        h1_indicators=h1_indicators,
    )
    signals = _confirmed_signals(
        m5,
        variant=FROZEN_VARIANT,
        m15_signals=m15_signals,
    )
    base_trades = simulate_m5_trades(m5, signals=signals, costs=costs)
    stress_trades = simulate_m5_trades(m5, signals=signals, costs=stressed_costs)

    holdout_base = tuple(
        trade
        for trade in base_trades
        if trade.signal_index >= split_index and trade.exit_index < len(m5)
    )
    holdout_stressed = tuple(
        trade
        for trade in stress_trades
        if trade.signal_index >= split_index and trade.exit_index < len(m5)
    )
    holdout_signals = tuple(
        signal for signal in signals if signal.signal_index >= split_index
    )
    metrics = compute_metrics(holdout_base)
    stressed_metrics = compute_metrics(holdout_stressed)

    base_threshold_pass = bool(
        metrics.completed_trades >= MIN_HOLDOUT_TRADES
        and metrics.win_rate is not None
        and metrics.win_rate >= FINAL_OOS_WIN_RATE_MIN
        and metrics.profit_factor is not None
        and metrics.profit_factor >= FINAL_OOS_PROFIT_FACTOR_MIN
        and metrics.expectancy_r is not None
        and metrics.expectancy_r >= FINAL_OOS_EXPECTANCY_R_MIN
    )
    stress_threshold_pass = _metrics_pass(
        stressed_metrics,
        validation_cfg["stress_acceptance"],
    )
    promotion_eligible = bool(base_threshold_pass and stress_threshold_pass)

    return {
        "research_version": RESEARCH_VERSION,
        "symbol": SYMBOL,
        "input_timeframe": "M5",
        "m5_bars": len(m5),
        "m15_bars": len(m15),
        "h1_bars": len(h1),
        "development_bars_locked": split_index,
        "holdout_bars": len(holdout_rows),
        "variant": asdict(FROZEN_VARIANT),
        "m15_setup_signals_full": len(m15_signals),
        "m5_confirmed_signals_full": len(signals),
        "holdout": {
            "base": metrics.payload(),
            "stressed": stressed_metrics.payload(),
            "coverage": _daily_coverage(holdout_rows, holdout_signals),
            "base_threshold_pass": base_threshold_pass,
            "stress_threshold_pass": stress_threshold_pass,
            "minimum_trades": MIN_HOLDOUT_TRADES,
            "win_rate_min": FINAL_OOS_WIN_RATE_MIN,
            "profit_factor_min": FINAL_OOS_PROFIT_FACTOR_MIN,
            "expectancy_r_min": FINAL_OOS_EXPECTANCY_R_MIN,
        },
        "htf_filter_evidence": filter_evidence,
        "promotion_eligible": promotion_eligible,
        "policy_effect": "SHADOW_ONLY",
        "execution_influence": False,
        "selection_note": (
            "V7 is one fixed hypothesis selected from V6 development diagnostics. "
            "It evaluates only the previously locked final 40% of the same 300k M5 history."
        ),
    }

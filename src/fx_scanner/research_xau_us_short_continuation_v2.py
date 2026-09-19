from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

from .demo_donchian_adaptive_tournament import TournamentMetrics, TournamentTrade, compute_metrics, walk_forward
from .models import Bar
from .research_xau_m15_continuation_tournament import (
    DEVELOPMENT_FRACTION,
    FINAL_OOS_EXPECTANCY_R_MIN,
    FINAL_OOS_PROFIT_FACTOR_MIN,
    FINAL_OOS_WIN_RATE_MIN,
    MIN_DEVELOPMENT_TRADES,
    MIN_HOLDOUT_TRADES,
    ContinuationSignal,
    ContinuationVariant,
    _daily_coverage,
    _metrics_pass,
    _validate_bars,
    extract_signals,
    simulate_trades,
)
from .research_xau_m15_dual_strategy import M15ResearchCosts

RESEARCH_VERSION = "XAU_US_SHORT_CONTINUATION_V2"
ARTIFACT_CONTRACT = "XAU_US_SHORT_CONTINUATION_V2_EVIDENCE_1"
SYMBOL = "XAUUSD"
TIMEFRAME = "M15"


@dataclass(frozen=True, slots=True)
class V2Variant:
    variant_id: str
    direction: str
    session: str
    bos_lookback: int
    retest_bars: int
    adx_min: float
    target_r: float
    impulse_range_atr: float
    impulse_body_atr: float
    retest_min_atr: float
    retest_max_atr: float
    require_fvg: bool = False
    selection_eligible: bool = True

    def base_variant(self) -> ContinuationVariant:
        return ContinuationVariant(
            variant_id=self.variant_id,
            bos_lookback=self.bos_lookback,
            retest_bars=self.retest_bars,
            adx_min=self.adx_min,
            target_r=self.target_r,
            require_fvg=self.require_fvg,
            session=self.session,
            impulse_range_atr=self.impulse_range_atr,
            impulse_body_atr=self.impulse_body_atr,
            retest_min_atr=self.retest_min_atr,
            retest_max_atr=self.retest_max_atr,
        )


# Preregistered after V1 development diagnostics and before any V2 holdout is opened.
# The primary hypothesis is that US-session SHORT continuation contains the edge.
# ALL-short and Asia-long are controls to test whether the apparent session/direction
# specificity survives a longer 100k-bar sample.
VARIANTS = (
    V2Variant(
        "XAU_V2_US_SHORT_BASE_R15", "SHORT", "US",
        12, 8, 18.0, 1.50, 1.20, 0.80, 0.05, 1.25,
    ),
    V2Variant(
        "XAU_V2_US_SHORT_L8_ADX15_R15", "SHORT", "US",
        8, 12, 15.0, 1.50, 1.00, 0.65, 0.00, 1.50,
    ),
    V2Variant(
        "XAU_V2_US_SHORT_L10_ADX15_R15", "SHORT", "US",
        10, 12, 15.0, 1.50, 1.00, 0.65, 0.00, 1.50,
    ),
    V2Variant(
        "XAU_V2_US_SHORT_L12_ADX15_R15", "SHORT", "US",
        12, 12, 15.0, 1.50, 1.05, 0.70, 0.00, 1.50,
    ),
    V2Variant(
        "XAU_V2_US_SHORT_L10_ADX22_R15", "SHORT", "US",
        10, 10, 22.0, 1.50, 1.00, 0.65, 0.00, 1.35,
    ),
    V2Variant(
        "XAU_V2_US_SHORT_L10_ADX15_R125", "SHORT", "US",
        10, 12, 15.0, 1.25, 1.00, 0.65, 0.00, 1.50,
    ),
    V2Variant(
        "XAU_V2_US_SHORT_L10_ADX15_R175", "SHORT", "US",
        10, 12, 15.0, 1.75, 1.00, 0.65, 0.00, 1.50,
    ),
    V2Variant(
        "XAU_V2_ALL_SHORT_L10_ADX15_R15_CONTROL", "SHORT", "ALL",
        10, 12, 15.0, 1.50, 1.00, 0.65, 0.00, 1.50,
        selection_eligible=False,
    ),
    V2Variant(
        "XAU_V2_ASIA_LONG_L10_ADX15_R15_CONTROL", "LONG", "ASIA",
        10, 12, 15.0, 1.50, 1.00, 0.65, 0.00, 1.50,
        selection_eligible=False,
    ),
)


def _directional_signals(
    bars: Sequence[Bar],
    *,
    variant: V2Variant,
) -> tuple[ContinuationSignal, ...]:
    return tuple(
        signal
        for signal in extract_signals(bars, variant=variant.base_variant())
        if signal.direction == variant.direction
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


def evaluate_us_short_v2(
    bars: Sequence[Bar],
    *,
    costs: M15ResearchCosts,
    stressed_costs: M15ResearchCosts,
    validation_cfg: Mapping[str, Any],
) -> dict[str, Any]:
    rows = _validate_bars(bars)
    split_index = max(1000, min(len(rows) - 1, int(len(rows) * DEVELOPMENT_FRACTION)))
    development_rows = rows[:split_index]
    holdout_rows = rows[split_index:]

    evaluations: list[dict[str, Any]] = []
    base_trade_sets: dict[str, tuple[TournamentTrade, ...]] = {}
    stress_trade_sets: dict[str, tuple[TournamentTrade, ...]] = {}
    signal_sets: dict[str, tuple[ContinuationSignal, ...]] = {}

    for variant in VARIANTS:
        signals = _directional_signals(rows, variant=variant)
        base_trades = simulate_trades(rows, signals=signals, costs=costs)
        stress_trades = simulate_trades(rows, signals=signals, costs=stressed_costs)
        signal_sets[variant.variant_id] = signals
        base_trade_sets[variant.variant_id] = base_trades
        stress_trade_sets[variant.variant_id] = stress_trades

        development = tuple(
            trade
            for trade in base_trades
            if trade.signal_index < split_index and trade.exit_index < split_index
        )
        development_stressed = tuple(
            trade
            for trade in stress_trades
            if trade.signal_index < split_index and trade.exit_index < split_index
        )
        metrics = compute_metrics(development)
        stressed_metrics = compute_metrics(development_stressed)
        folds, pass_fraction, walk_forward_passed = walk_forward(
            development,
            validation_cfg["walk_forward"],
        )
        stress_passed = _metrics_pass(
            stressed_metrics,
            validation_cfg["stress_acceptance"],
        )
        development_passed = bool(
            metrics.completed_trades >= MIN_DEVELOPMENT_TRADES
            and walk_forward_passed
            and stress_passed
        )
        development_signals = tuple(
            signal for signal in signals if signal.signal_index < split_index
        )
        evaluations.append(
            {
                "variant": asdict(variant),
                "development": metrics.payload(),
                "stressed_development": stressed_metrics.payload(),
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
                    "passed": walk_forward_passed,
                },
                "stress_passed": stress_passed,
                "development_passed": development_passed,
                "development_coverage": _daily_coverage(
                    development_rows,
                    development_signals,
                ),
            }
        )

    eligible = [
        row
        for row in evaluations
        if row["development_passed"] and bool(row["variant"]["selection_eligible"])
    ]
    eligible.sort(
        key=lambda row: (
            float(row["walk_forward"]["pass_fraction"]),
            float(row["stressed_development"].get("expectancy_r") or -999.0),
            float(row["stressed_development"].get("profit_factor") or -999.0),
            float(row["development"].get("expectancy_r") or -999.0),
            -float(row["development"].get("max_drawdown_r") or 999.0),
        ),
        reverse=True,
    )
    selected = eligible[0] if eligible else None

    holdout: dict[str, Any] | None = None
    promotion_eligible = False
    if selected is not None:
        variant_id = str(selected["variant"]["variant_id"])
        holdout_base = tuple(
            trade
            for trade in base_trade_sets[variant_id]
            if trade.signal_index >= split_index and trade.exit_index < len(rows)
        )
        holdout_stressed = tuple(
            trade
            for trade in stress_trade_sets[variant_id]
            if trade.signal_index >= split_index and trade.exit_index < len(rows)
        )
        holdout_metrics = compute_metrics(holdout_base)
        holdout_stress_metrics = compute_metrics(holdout_stressed)
        holdout_signals = tuple(
            signal
            for signal in signal_sets[variant_id]
            if signal.signal_index >= split_index
        )
        promotion_eligible = bool(
            _final_oos_pass(holdout_metrics)
            and _metrics_pass(
                holdout_stress_metrics,
                validation_cfg["stress_acceptance"],
            )
        )
        holdout = {
            "variant_id": variant_id,
            "base": holdout_metrics.payload(),
            "stressed": holdout_stress_metrics.payload(),
            "coverage": _daily_coverage(holdout_rows, holdout_signals),
            "final_oos_thresholds": {
                "minimum_trades": MIN_HOLDOUT_TRADES,
                "win_rate_min": FINAL_OOS_WIN_RATE_MIN,
                "profit_factor_min": FINAL_OOS_PROFIT_FACTOR_MIN,
                "expectancy_r_min": FINAL_OOS_EXPECTANCY_R_MIN,
            },
            "passed": promotion_eligible,
        }

    return {
        "research_version": RESEARCH_VERSION,
        "symbol": SYMBOL,
        "timeframe": TIMEFRAME,
        "history_bars": len(rows),
        "development_bars": len(development_rows),
        "holdout_bars": len(holdout_rows),
        "variants": evaluations,
        "selected_variant": None if selected is None else selected["variant"]["variant_id"],
        "holdout": holdout,
        "promotion_eligible": promotion_eligible,
        "policy_effect": "SHADOW_ONLY",
        "execution_influence": False,
        "selection_note": (
            "V2 variants were frozen after V1 development-only diagnostics. "
            "Selection uses V2 development + walk-forward + stressed costs only; "
            "the V2 locked holdout is opened only if a development candidate passes."
        ),
    }

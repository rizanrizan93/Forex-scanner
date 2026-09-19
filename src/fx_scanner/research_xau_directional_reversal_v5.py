from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

from .demo_donchian_adaptive_tournament import (
    TournamentMetrics,
    TournamentTrade,
    compute_metrics,
    walk_forward,
)
from .models import Bar
from .research_xau_m15_continuation_tournament import (
    DEVELOPMENT_FRACTION,
    FINAL_OOS_EXPECTANCY_R_MIN,
    FINAL_OOS_PROFIT_FACTOR_MIN,
    FINAL_OOS_WIN_RATE_MIN,
    MIN_DEVELOPMENT_TRADES,
    MIN_HOLDOUT_TRADES,
    _daily_coverage,
    _indicator_series,
    _metrics_pass,
    _validate_bars,
    simulate_trades,
)
from .research_xau_m15_dual_strategy import M15ResearchCosts
from .research_xau_us_reversal_htf_v4 import (
    HtfVariant,
    _aggregate_h1,
    _filtered_signals,
)
from .models import ensure_utc
from datetime import timedelta

RESEARCH_VERSION = "XAU_DIRECTIONAL_REVERSAL_V5"
ARTIFACT_CONTRACT = "XAU_DIRECTIONAL_REVERSAL_V5_EVIDENCE_1"
SYMBOL = "XAUUSD"
TIMEFRAME = "M15"


@dataclass(frozen=True, slots=True)
class DirectionalVariant:
    variant_id: str
    long_filter: str | None
    long_target_r: float | None
    short_filter: str | None
    short_target_r: float | None
    selection_eligible: bool = True


VARIANTS = (
    DirectionalVariant(
        "XAU_V5_LONG_EMA2050_NO_R125__SHORT_STRUCTURE_R15",
        "EMA20_50_NOT_OPPOSED",
        1.25,
        "STRUCTURE_MATCH",
        1.50,
    ),
    DirectionalVariant(
        "XAU_V5_LONG_EMA2050_NO_R125__SHORT_EMA2050_NO_R20",
        "EMA20_50_NOT_OPPOSED",
        1.25,
        "EMA20_50_NOT_OPPOSED",
        2.00,
    ),
    DirectionalVariant(
        "XAU_V5_LONG_EMA2050200_R15__SHORT_STRUCTURE_R15",
        "EMA20_50_200",
        1.50,
        "STRUCTURE_MATCH",
        1.50,
    ),
    DirectionalVariant(
        "XAU_V5_LONG_EMA2050200_NO_R15__SHORT_STRUCTURE_R15",
        "EMA20_50_200_NOT_OPPOSED",
        1.50,
        "STRUCTURE_MATCH",
        1.50,
    ),
    DirectionalVariant(
        "XAU_V5_LONG_EMA2050_NO_R125_CONTROL",
        "EMA20_50_NOT_OPPOSED",
        1.25,
        None,
        None,
        selection_eligible=False,
    ),
    DirectionalVariant(
        "XAU_V5_SHORT_STRUCTURE_R15_CONTROL",
        None,
        None,
        "STRUCTURE_MATCH",
        1.50,
        selection_eligible=False,
    ),
    DirectionalVariant(
        "XAU_V5_SHORT_EMA2050_NO_R20_CONTROL",
        None,
        None,
        "EMA20_50_NOT_OPPOSED",
        2.00,
        selection_eligible=False,
    ),
)


def _direction_signals(
    rows: Sequence[Bar],
    *,
    direction: str,
    filter_name: str,
    target_r: float,
    h1: Sequence[Bar],
    h1_closes,
    h1_indicators,
):
    variant = HtfVariant(
        variant_id=f"XAU_V5_POOL_{direction}_{filter_name}_{target_r}",
        htf_filter=filter_name,
        target_r=target_r,
        selection_eligible=False,
    )
    signals, evidence = _filtered_signals(
        rows,
        variant=variant,
        h1=h1,
        h1_closes=h1_closes,
        h1_indicators=h1_indicators,
    )
    return tuple(signal for signal in signals if signal.direction == direction), evidence


def _variant_signals(
    rows: Sequence[Bar],
    *,
    variant: DirectionalVariant,
    h1: Sequence[Bar],
    h1_closes,
    h1_indicators,
):
    output = []
    evidence: dict[str, Any] = {}
    if variant.long_filter is not None and variant.long_target_r is not None:
        long_signals, long_evidence = _direction_signals(
            rows,
            direction="LONG",
            filter_name=variant.long_filter,
            target_r=variant.long_target_r,
            h1=h1,
            h1_closes=h1_closes,
            h1_indicators=h1_indicators,
        )
        output.extend(long_signals)
        evidence["LONG"] = long_evidence
    if variant.short_filter is not None and variant.short_target_r is not None:
        short_signals, short_evidence = _direction_signals(
            rows,
            direction="SHORT",
            filter_name=variant.short_filter,
            target_r=variant.short_target_r,
            h1=h1,
            h1_closes=h1_closes,
            h1_indicators=h1_indicators,
        )
        output.extend(short_signals)
        evidence["SHORT"] = short_evidence
    output.sort(key=lambda signal: (signal.signal_index, signal.direction))
    return tuple(output), evidence


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


def evaluate_directional_reversal_v5(
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
    h1 = _aggregate_h1(rows)
    h1_closes = tuple(ensure_utc(row.timestamp) + timedelta(hours=1) for row in h1)
    h1_indicators = _indicator_series(h1)

    evaluations: list[dict[str, Any]] = []
    base_trade_sets: dict[str, tuple[TournamentTrade, ...]] = {}
    stress_trade_sets: dict[str, tuple[TournamentTrade, ...]] = {}
    signal_sets = {}

    for variant in VARIANTS:
        signals, filter_evidence = _variant_signals(
            rows,
            variant=variant,
            h1=h1,
            h1_closes=h1_closes,
            h1_indicators=h1_indicators,
        )
        base_trades = simulate_trades(rows, signals=signals, costs=costs)
        stressed_trades = simulate_trades(rows, signals=signals, costs=stressed_costs)
        signal_sets[variant.variant_id] = signals
        base_trade_sets[variant.variant_id] = base_trades
        stress_trade_sets[variant.variant_id] = stressed_trades

        development = tuple(
            trade
            for trade in base_trades
            if trade.signal_index < split_index and trade.exit_index < split_index
        )
        development_stressed = tuple(
            trade
            for trade in stressed_trades
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
        direction_metrics = {
            direction: compute_metrics(
                tuple(trade for trade in development if trade.direction == direction)
            ).payload()
            for direction in ("LONG", "SHORT")
        }
        stressed_direction_metrics = {
            direction: compute_metrics(
                tuple(trade for trade in development_stressed if trade.direction == direction)
            ).payload()
            for direction in ("LONG", "SHORT")
        }
        evaluations.append(
            {
                "variant": asdict(variant),
                "development": metrics.payload(),
                "development_by_direction": direction_metrics,
                "stressed_development": stressed_metrics.payload(),
                "stressed_development_by_direction": stressed_direction_metrics,
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
                "htf_filter_evidence": filter_evidence,
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
            signal for signal in signal_sets[variant_id] if signal.signal_index >= split_index
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
        "h1_bars": len(h1),
        "development_bars": len(development_rows),
        "holdout_bars": len(holdout_rows),
        "variants": evaluations,
        "selected_variant": None if selected is None else selected["variant"]["variant_id"],
        "holdout": holdout,
        "promotion_eligible": promotion_eligible,
        "policy_effect": "SHADOW_ONLY",
        "execution_influence": False,
        "selection_note": (
            "V5 direction-specific variants were frozen from V4 development-only diagnostics. "
            "Selection uses expanded-history development + WFO + stressed costs. "
            "Locked holdout opens only after all development gates pass."
        ),
    }

from __future__ import annotations

from bisect import bisect_right
from dataclasses import asdict, dataclass
from datetime import timedelta
from typing import Any, Mapping, Sequence

from .demo_donchian_adaptive_tournament import (
    TournamentMetrics,
    TournamentTrade,
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
    _daily_coverage,
    _indicator_series,
    _metrics_pass,
    _validate_bars,
    simulate_trades,
)
from .research_xau_m15_dual_strategy import M15ResearchCosts
from .research_xau_session_liquidity_adaptive_v3 import (
    SESSION_EUROPE,
    SESSION_US,
    SessionVariant,
    extract_session_signals,
)
from .technical import structure_snapshot

RESEARCH_VERSION = "XAU_US_REVERSAL_HTF_V4"
ARTIFACT_CONTRACT = "XAU_US_REVERSAL_HTF_V4_EVIDENCE_1"
SYMBOL = "XAUUSD"
TIMEFRAME = "M15"
H1_STRUCTURE_WINDOW = 60
H1_MIN_BARS = 220


@dataclass(frozen=True, slots=True)
class HtfVariant:
    variant_id: str
    htf_filter: str
    target_r: float
    selection_eligible: bool = True


VARIANTS = (
    HtfVariant("XAU_V4_US_REV_CONTROL_R15", "NONE", 1.50, selection_eligible=False),
    HtfVariant("XAU_V4_US_REV_H1_EMA2050_R15", "EMA20_50", 1.50),
    HtfVariant("XAU_V4_US_REV_H1_EMA2050200_R15", "EMA20_50_200", 1.50),
    HtfVariant("XAU_V4_US_REV_H1_STRUCTURE_R15", "STRUCTURE_MATCH", 1.50),
    HtfVariant("XAU_V4_US_REV_H1_EMA2050_NOT_OPPOSED_R15", "EMA20_50_NOT_OPPOSED", 1.50),
    HtfVariant("XAU_V4_US_REV_H1_EMA2050200_NOT_OPPOSED_R15", "EMA20_50_200_NOT_OPPOSED", 1.50),
    HtfVariant("XAU_V4_US_REV_H1_EMA2050_DI_R15", "EMA20_50_DI", 1.50),
    HtfVariant("XAU_V4_US_REV_H1_EMA2050_NOT_OPPOSED_R125", "EMA20_50_NOT_OPPOSED", 1.25),
    HtfVariant("XAU_V4_US_REV_H1_EMA2050_NOT_OPPOSED_R20", "EMA20_50_NOT_OPPOSED", 2.00),
)


def _aggregate_h1(rows: Sequence[Bar]) -> tuple[Bar, ...]:
    buckets: dict[Any, list[Bar]] = {}
    for row in rows:
        stamp = ensure_utc(row.timestamp)
        hour = stamp.replace(minute=0, second=0, microsecond=0)
        buckets.setdefault(hour, []).append(row)
    output: list[Bar] = []
    for hour in sorted(buckets):
        group = sorted(buckets[hour], key=lambda item: ensure_utc(item.timestamp))
        if [ensure_utc(item.timestamp).minute for item in group] != [0, 15, 30, 45]:
            continue
        output.append(
            Bar(
                symbol=SYMBOL,
                timeframe="H1",
                timestamp=hour,
                open=float(group[0].open),
                high=max(float(item.high) for item in group),
                low=min(float(item.low) for item in group),
                close=float(group[-1].close),
                tick_count=sum(int(item.tick_count) for item in group),
                spread_avg=sum(float(item.spread_avg) for item in group) / 4.0,
                spread_max=max(float(item.spread_max) for item in group),
            )
        )
    return tuple(output)


def _base_session_variant(target_r: float) -> SessionVariant:
    return SessionVariant(
        variant_id=f"XAU_V4_US_REV_POOL_R{int(round(target_r * 100)):03d}",
        family="REVERSAL",
        target_reference_pairs=((SESSION_US, SESSION_EUROPE),),
        target_r=float(target_r),
        selection_eligible=False,
    )


def _direction_token(direction: str) -> str:
    return "BULLISH" if direction == "LONG" else "BEARISH"


def _htf_pass(
    *,
    h1: Sequence[Bar],
    h1_indicators: Mapping[str, Sequence[float | None]],
    h1_index: int,
    direction: str,
    filter_name: str,
) -> tuple[bool, dict[str, Any]]:
    if filter_name == "NONE":
        return True, {"filter": filter_name}
    if h1_index < H1_MIN_BARS - 1:
        return False, {"filter": filter_name, "reason": "INSUFFICIENT_H1_HISTORY"}

    close = float(h1[h1_index].close)
    ema20 = h1_indicators["ema20"][h1_index]
    ema50 = h1_indicators["ema50"][h1_index]
    ema200 = h1_indicators["ema200"][h1_index]
    adx = h1_indicators["adx"][h1_index]
    plus_di = h1_indicators["plus_di"][h1_index]
    minus_di = h1_indicators["minus_di"][h1_index]
    if None in (ema20, ema50, ema200):
        return False, {"filter": filter_name, "reason": "H1_EMA_UNAVAILABLE"}

    ema20 = float(ema20)
    ema50 = float(ema50)
    ema200 = float(ema200)
    if direction == "LONG":
        ema2050 = close > ema20 > ema50
        ema2050200 = close > ema20 > ema50 > ema200
        di_aligned = (
            adx is not None
            and plus_di is not None
            and minus_di is not None
            and float(adx) >= 15.0
            and float(plus_di) > float(minus_di)
        )
    else:
        ema2050 = close < ema20 < ema50
        ema2050200 = close < ema20 < ema50 < ema200
        di_aligned = (
            adx is not None
            and plus_di is not None
            and minus_di is not None
            and float(adx) >= 15.0
            and float(minus_di) > float(plus_di)
        )

    start = max(0, h1_index - H1_STRUCTURE_WINDOW + 1)
    snapshot = structure_snapshot(list(h1[start : h1_index + 1]))
    wanted = _direction_token(direction)
    opposite = "BEARISH" if wanted == "BULLISH" else "BULLISH"
    structure_match = bool(
        snapshot.trend == wanted or snapshot.bos == wanted or snapshot.mss == wanted
    )
    structure_not_opposed = snapshot.trend != opposite

    checks = {
        "EMA20_50": ema2050,
        "EMA20_50_200": ema2050200,
        "STRUCTURE_MATCH": structure_match,
        "EMA20_50_NOT_OPPOSED": ema2050 and structure_not_opposed,
        "EMA20_50_200_NOT_OPPOSED": ema2050200 and structure_not_opposed,
        "EMA20_50_DI": ema2050 and di_aligned,
    }
    if filter_name not in checks:
        raise ValueError(f"XAU_V4_HTF_FILTER_INVALID:{filter_name}")
    return bool(checks[filter_name]), {
        "filter": filter_name,
        "h1_close": close,
        "ema20": ema20,
        "ema50": ema50,
        "ema200": ema200,
        "adx": None if adx is None else float(adx),
        "plus_di": None if plus_di is None else float(plus_di),
        "minus_di": None if minus_di is None else float(minus_di),
        "h1_trend": snapshot.trend,
        "h1_bos": snapshot.bos,
        "h1_mss": snapshot.mss,
        "ema2050": ema2050,
        "ema2050200": ema2050200,
        "di_aligned": di_aligned,
        "structure_match": structure_match,
        "structure_not_opposed": structure_not_opposed,
    }


def _filtered_signals(
    rows: Sequence[Bar],
    *,
    variant: HtfVariant,
    h1: Sequence[Bar],
    h1_closes: Sequence[Any],
    h1_indicators: Mapping[str, Sequence[float | None]],
):
    base = extract_session_signals(rows, variant=_base_session_variant(variant.target_r))
    output = []
    filter_counts: dict[str, int] = {"considered": 0, "passed": 0, "insufficient": 0}
    by_direction = {"LONG": {"considered": 0, "passed": 0}, "SHORT": {"considered": 0, "passed": 0}}
    for signal in base:
        signal_close = ensure_utc(rows[signal.signal_index].timestamp) + timedelta(minutes=15)
        h1_count = bisect_right(h1_closes, signal_close)
        filter_counts["considered"] += 1
        by_direction[signal.direction]["considered"] += 1
        if h1_count <= 0:
            filter_counts["insufficient"] += 1
            continue
        passed, evidence = _htf_pass(
            h1=h1,
            h1_indicators=h1_indicators,
            h1_index=h1_count - 1,
            direction=signal.direction,
            filter_name=variant.htf_filter,
        )
        if not passed:
            if evidence.get("reason") == "INSUFFICIENT_H1_HISTORY":
                filter_counts["insufficient"] += 1
            continue
        filter_counts["passed"] += 1
        by_direction[signal.direction]["passed"] += 1
        output.append(signal)
    return tuple(output), {"counts": filter_counts, "by_direction": by_direction}


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


def evaluate_us_reversal_htf_v4(
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
        signals, filter_evidence = _filtered_signals(
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
            trade for trade in base_trades
            if trade.signal_index < split_index and trade.exit_index < split_index
        )
        development_stressed = tuple(
            trade for trade in stressed_trades
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
        row for row in evaluations
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
            trade for trade in base_trade_sets[variant_id]
            if trade.signal_index >= split_index and trade.exit_index < len(rows)
        )
        holdout_stressed = tuple(
            trade for trade in stress_trade_sets[variant_id]
            if trade.signal_index >= split_index and trade.exit_index < len(rows)
        )
        holdout_metrics = compute_metrics(holdout_base)
        holdout_stress_metrics = compute_metrics(holdout_stressed)
        holdout_signals = tuple(
            signal for signal in signal_sets[variant_id]
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
            "V4 freezes US-session Europe-range sweep/reversal plus H1 EMA/structure/DI "
            "filters before locked holdout access. The unfiltered control is non-selecting."
        ),
    }

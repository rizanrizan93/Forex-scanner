from __future__ import annotations

from dataclasses import asdict, dataclass
from math import isfinite
from typing import Any, Mapping, Sequence

from .demo_donchian_adaptive_tournament import TournamentMetrics, TournamentTrade, compute_metrics, walk_forward
from .models import Bar, ensure_utc
from .research_xau_m15_dual_strategy import M15ResearchCosts

RESEARCH_VERSION = "XAU_M15_CONTINUATION_TOURNAMENT_V1"
ARTIFACT_CONTRACT = "XAU_M15_CONTINUATION_TOURNAMENT_EVIDENCE_1"
SYMBOL = "XAUUSD"
TIMEFRAME = "M15"
TIMEFRAME_SECONDS = 15 * 60
PIP_SIZE = 0.01
DEVELOPMENT_FRACTION = 0.60
MIN_DEVELOPMENT_TRADES = 130
MIN_HOLDOUT_TRADES = 100
EMA_FAST = 20
EMA_MID = 50
EMA_SLOW = 200
ATR_PERIOD = 14
ADX_PERIOD = 14
STOP_BUFFER_ATR = 0.25
INVALIDATION_ATR = 0.25
MAX_HOLD_BARS = 32

FINAL_OOS_WIN_RATE_MIN = 0.55
FINAL_OOS_PROFIT_FACTOR_MIN = 1.30
FINAL_OOS_EXPECTANCY_R_MIN = 0.15


@dataclass(frozen=True, slots=True)
class ContinuationVariant:
    variant_id: str
    bos_lookback: int
    retest_bars: int
    adx_min: float
    target_r: float
    require_fvg: bool = False
    session: str = "ALL"
    breakout_buffer_atr: float = 0.0
    impulse_body_atr: float = 0.80
    impulse_range_atr: float = 1.20
    retest_min_atr: float = 0.05
    retest_max_atr: float = 1.25


VARIANTS = (
    ContinuationVariant("XAU_CONT_CORE_L12_ADX18_R15", 12, 8, 18.0, 1.50),
    ContinuationVariant("XAU_CONT_CORE_L12_ADX18_R20", 12, 8, 18.0, 2.00),
    ContinuationVariant("XAU_CONT_FVG_L12_ADX18_R20", 12, 8, 18.0, 2.00, require_fvg=True),
    ContinuationVariant("XAU_CONT_ASIA_L12_ADX18_R15", 12, 8, 18.0, 1.50, session="ASIA"),
    ContinuationVariant("XAU_CONT_US_L12_ADX18_R15", 12, 8, 18.0, 1.50, session="US"),
    ContinuationVariant("XAU_CONT_CORE_L20_ADX18_R20", 20, 10, 18.0, 2.00),
)


@dataclass(frozen=True, slots=True)
class ContinuationSignal:
    variant_id: str
    signal_index: int
    direction: str
    signal_at: Any
    atr: float
    breakout_level: float
    structural_stop: float
    reward_r: float
    impulse_index: int
    retest_index: int
    fvg_low: float | None
    fvg_high: float | None


def _validate_bars(bars: Sequence[Bar]) -> tuple[Bar, ...]:
    rows = tuple(sorted(bars, key=lambda row: ensure_utc(row.timestamp)))
    if not rows:
        raise ValueError("XAU_CONTINUATION_RESEARCH_BARS_EMPTY")
    if any(row.symbol.upper() != SYMBOL or row.timeframe.upper() != TIMEFRAME for row in rows):
        raise ValueError("XAU_CONTINUATION_RESEARCH_REQUIRES_XAUUSD_M15")
    if any(
        ensure_utc(rows[index].timestamp) >= ensure_utc(rows[index + 1].timestamp)
        for index in range(len(rows) - 1)
    ):
        raise ValueError("XAU_CONTINUATION_RESEARCH_BARS_NOT_CHRONOLOGICAL")
    return rows


def _ema(values: Sequence[float], period: int) -> tuple[float | None, ...]:
    if period <= 1:
        raise ValueError("EMA_PERIOD_INVALID")
    if len(values) < period:
        return tuple(None for _ in values)
    seed = sum(float(v) for v in values[:period]) / float(period)
    output: list[float | None] = [None] * (period - 1) + [seed]
    alpha = 2.0 / (period + 1.0)
    previous = seed
    for value in values[period:]:
        previous = alpha * float(value) + (1.0 - alpha) * previous
        output.append(previous)
    return tuple(output)


def _rma(values: Sequence[float], period: int) -> tuple[float | None, ...]:
    if period <= 0:
        raise ValueError("RMA_PERIOD_INVALID")
    if len(values) < period:
        return tuple(None for _ in values)
    seed = sum(float(v) for v in values[:period]) / float(period)
    output: list[float | None] = [None] * (period - 1) + [seed]
    previous = seed
    for value in values[period:]:
        previous = ((previous * (period - 1)) + float(value)) / float(period)
        output.append(previous)
    return tuple(output)


def _indicator_series(rows: Sequence[Bar]) -> dict[str, tuple[float | None, ...]]:
    closes = [float(row.close) for row in rows]
    ema20 = _ema(closes, EMA_FAST)
    ema50 = _ema(closes, EMA_MID)
    ema200 = _ema(closes, EMA_SLOW)

    trs: list[float] = []
    plus_dm: list[float] = []
    minus_dm: list[float] = []
    previous = rows[0]
    for current in rows[1:]:
        up_move = float(current.high) - float(previous.high)
        down_move = float(previous.low) - float(current.low)
        plus_dm.append(up_move if up_move > down_move and up_move > 0.0 else 0.0)
        minus_dm.append(down_move if down_move > up_move and down_move > 0.0 else 0.0)
        trs.append(
            max(
                float(current.high) - float(current.low),
                abs(float(current.high) - float(previous.close)),
                abs(float(current.low) - float(previous.close)),
            )
        )
        previous = current

    tr_rma = _rma(trs, ATR_PERIOD)
    plus_rma = _rma(plus_dm, ADX_PERIOD)
    minus_rma = _rma(minus_dm, ADX_PERIOD)

    atr_values: list[float | None] = [None]
    plus_di_values: list[float | None] = [None]
    minus_di_values: list[float | None] = [None]
    dx_values: list[float] = []
    dx_indexes: list[int] = []

    for index, (tr_value, plus_value, minus_value) in enumerate(zip(tr_rma, plus_rma, minus_rma), start=1):
        atr_values.append(None if tr_value is None else float(tr_value))
        if tr_value is None or plus_value is None or minus_value is None or float(tr_value) <= 0.0:
            plus_di_values.append(None)
            minus_di_values.append(None)
            continue
        plus_di = 100.0 * float(plus_value) / float(tr_value)
        minus_di = 100.0 * float(minus_value) / float(tr_value)
        plus_di_values.append(plus_di)
        minus_di_values.append(minus_di)
        denom = plus_di + minus_di
        dx_values.append(0.0 if denom <= 1e-12 else 100.0 * abs(plus_di - minus_di) / denom)
        dx_indexes.append(index)

    adx_values: list[float | None] = [None] * len(rows)
    smoothed_dx = _rma(dx_values, ADX_PERIOD)
    for index, value in zip(dx_indexes, smoothed_dx):
        if value is not None:
            adx_values[index] = float(value)

    while len(atr_values) < len(rows):
        atr_values.append(None)
    while len(plus_di_values) < len(rows):
        plus_di_values.append(None)
    while len(minus_di_values) < len(rows):
        minus_di_values.append(None)

    return {
        "ema20": ema20,
        "ema50": ema50,
        "ema200": ema200,
        "atr": tuple(atr_values[: len(rows)]),
        "plus_di": tuple(plus_di_values[: len(rows)]),
        "minus_di": tuple(minus_di_values[: len(rows)]),
        "adx": tuple(adx_values),
    }


def _session_ok(bar: Bar, session: str) -> bool:
    # 2026 World Gold Council convention in UTC: Asia 22:00-07:00,
    # Europe 07:00-12:00 and US 12:00-21:00. ALL is the default control.
    value = str(session or "ALL").upper()
    hour = ensure_utc(bar.timestamp).hour
    if value == "ALL":
        return True
    if value == "ASIA":
        return hour >= 22 or hour < 7
    if value == "US":
        return 12 <= hour < 21
    raise ValueError(f"XAU_CONTINUATION_SESSION_INVALID:{value}")


def _fvg_on_impulse(rows: Sequence[Bar], index: int, direction: str) -> tuple[float | None, float | None]:
    if index < 2:
        return None, None
    left = rows[index - 2]
    current = rows[index]
    if direction == "LONG" and float(current.low) > float(left.high):
        return float(left.high), float(current.low)
    if direction == "SHORT" and float(current.high) < float(left.low):
        return float(current.high), float(left.low)
    return None, None


def _overlaps(bar: Bar, low: float | None, high: float | None) -> bool:
    if low is None or high is None:
        return False
    lo, hi = sorted((float(low), float(high)))
    return float(bar.low) <= hi and float(bar.high) >= lo


def extract_signals(
    bars: Sequence[Bar],
    *,
    variant: ContinuationVariant,
) -> tuple[ContinuationSignal, ...]:
    rows = _validate_bars(bars)
    indicators = _indicator_series(rows)
    output: list[ContinuationSignal] = []
    next_eligible_impulse = max(EMA_SLOW + 5, variant.bos_lookback + ADX_PERIOD * 2 + 5)

    for impulse_index in range(next_eligible_impulse, len(rows) - variant.retest_bars - 2):
        impulse = rows[impulse_index]
        atr_value = indicators["atr"][impulse_index]
        adx_value = indicators["adx"][impulse_index]
        plus_di = indicators["plus_di"][impulse_index]
        minus_di = indicators["minus_di"][impulse_index]
        ema20 = indicators["ema20"][impulse_index]
        ema50 = indicators["ema50"][impulse_index]
        ema200 = indicators["ema200"][impulse_index]
        if None in (atr_value, adx_value, plus_di, minus_di, ema20, ema50, ema200):
            continue
        atr_value = float(atr_value)
        if atr_value <= 0.0 or float(adx_value) < float(variant.adx_min):
            continue
        if not _session_ok(impulse, variant.session):
            continue

        prior = rows[impulse_index - variant.bos_lookback: impulse_index]
        prior_high = max(float(row.high) for row in prior)
        prior_low = min(float(row.low) for row in prior)
        candle_range = float(impulse.high) - float(impulse.low)
        body = abs(float(impulse.close) - float(impulse.open))
        if candle_range < variant.impulse_range_atr * atr_value or body < variant.impulse_body_atr * atr_value:
            continue

        close_long_location = (float(impulse.close) - float(impulse.low)) / max(candle_range, 1e-12)
        close_short_location = (float(impulse.high) - float(impulse.close)) / max(candle_range, 1e-12)
        long_trend = float(impulse.close) > float(ema20) > float(ema50) > float(ema200)
        short_trend = float(impulse.close) < float(ema20) < float(ema50) < float(ema200)

        direction: str | None = None
        breakout_level: float | None = None
        if (
            long_trend
            and float(plus_di) > float(minus_di)
            and float(impulse.close) > prior_high + variant.breakout_buffer_atr * atr_value
            and float(impulse.close) > float(impulse.open)
            and close_long_location >= 0.70
        ):
            direction = "LONG"
            breakout_level = prior_high
        elif (
            short_trend
            and float(minus_di) > float(plus_di)
            and float(impulse.close) < prior_low - variant.breakout_buffer_atr * atr_value
            and float(impulse.close) < float(impulse.open)
            and close_short_location >= 0.70
        ):
            direction = "SHORT"
            breakout_level = prior_low
        if direction is None or breakout_level is None:
            continue

        fvg_low, fvg_high = _fvg_on_impulse(rows, impulse_index, direction)
        if variant.require_fvg and fvg_low is None:
            continue

        retest_index: int | None = None
        structural_stop: float | None = None
        impulse_close = float(impulse.close)
        for index in range(impulse_index + 1, min(len(rows) - 1, impulse_index + variant.retest_bars + 1)):
            row = rows[index]
            depth = (
                (impulse_close - float(row.low)) / atr_value
                if direction == "LONG"
                else (float(row.high) - impulse_close) / atr_value
            )
            invalid = (
                float(row.close) < breakout_level - INVALIDATION_ATR * atr_value
                if direction == "LONG"
                else float(row.close) > breakout_level + INVALIDATION_ATR * atr_value
            )
            if invalid:
                break

            breakout_retest = (
                float(row.low) <= breakout_level + 0.15 * atr_value
                if direction == "LONG"
                else float(row.high) >= breakout_level - 0.15 * atr_value
            )
            zone_retest = breakout_retest or _overlaps(row, fvg_low, fvg_high)
            accepted = float(row.close) > breakout_level if direction == "LONG" else float(row.close) < breakout_level
            controlled = variant.retest_min_atr <= depth <= variant.retest_max_atr
            if accepted and controlled and zone_retest:
                retest_index = index
                structural_stop = (
                    min(float(row.low), breakout_level) - STOP_BUFFER_ATR * atr_value
                    if direction == "LONG"
                    else max(float(row.high), breakout_level) + STOP_BUFFER_ATR * atr_value
                )
                break

        if retest_index is None or structural_stop is None or retest_index + 1 >= len(rows):
            continue

        output.append(
            ContinuationSignal(
                variant_id=variant.variant_id,
                signal_index=retest_index,
                direction=direction,
                signal_at=ensure_utc(rows[retest_index].timestamp),
                atr=atr_value,
                breakout_level=breakout_level,
                structural_stop=structural_stop,
                reward_r=float(variant.target_r),
                impulse_index=impulse_index,
                retest_index=retest_index,
                fvg_low=fvg_low,
                fvg_high=fvg_high,
            )
        )

    # A retest can be rediscovered from adjacent impulses. One entry per bar/side/variant.
    unique: dict[tuple[int, str], ContinuationSignal] = {}
    for signal in output:
        unique[(signal.signal_index, signal.direction)] = signal
    return tuple(unique[key] for key in sorted(unique))


def _roundtrip_cost_r(*, risk_pips: float, bars_held: int, costs: M15ResearchCosts) -> float:
    if risk_pips <= 0.0:
        raise ValueError("XAU_CONTINUATION_RISK_PIPS_INVALID")
    elapsed_days = max(0, int(bars_held)) * TIMEFRAME_SECONDS / 86400.0
    total_pips = (
        float(costs.spread_pips) * float(costs.spread_multiplier)
        + float(costs.slippage_pips) * float(costs.slippage_multiplier)
        + float(costs.commission_pips_round_trip)
        + float(costs.swap_pips_per_day) * elapsed_days
    )
    return total_pips / risk_pips


def simulate_trades(
    bars: Sequence[Bar],
    *,
    signals: Sequence[ContinuationSignal],
    costs: M15ResearchCosts,
    max_hold_bars: int = MAX_HOLD_BARS,
) -> tuple[TournamentTrade, ...]:
    rows = _validate_bars(bars)
    output: list[TournamentTrade] = []
    for signal in signals:
        entry_index = signal.signal_index + 1
        if entry_index >= len(rows):
            continue
        entry = float(rows[entry_index].open)
        stop = float(signal.structural_stop)
        risk = entry - stop if signal.direction == "LONG" else stop - entry
        if not isfinite(risk) or risk <= 0.0:
            continue
        risk_pips = risk / PIP_SIZE
        target = (
            entry + signal.reward_r * risk
            if signal.direction == "LONG"
            else entry - signal.reward_r * risk
        )
        if target <= 0.0:
            continue

        last_index = min(len(rows) - 1, entry_index + int(max_hold_bars))
        trade: TournamentTrade | None = None
        for index in range(entry_index, last_index + 1):
            bar = rows[index]
            if signal.direction == "LONG":
                stop_hit = float(bar.low) <= stop
                target_hit = float(bar.high) >= target
            else:
                stop_hit = float(bar.high) >= stop
                target_hit = float(bar.low) <= target
            raw_target_hit = target_hit
            if index == entry_index:
                target_hit = False
            bars_held = index - entry_index
            cost_r = _roundtrip_cost_r(risk_pips=risk_pips, bars_held=bars_held, costs=costs)
            if stop_hit:
                gross_r = -1.0
                trade = TournamentTrade(
                    signal.variant_id, SYMBOL, signal.direction,
                    signal.signal_at, ensure_utc(rows[entry_index].timestamp), ensure_utc(bar.timestamp),
                    signal.signal_index, index, entry, stop, signal.atr, stop, target,
                    gross_r, cost_r, gross_r - cost_r, bars_held,
                    "STOP_FIRST_AMBIGUOUS" if raw_target_hit else "STOP_HIT",
                )
                break
            if target_hit:
                gross_r = float(signal.reward_r)
                trade = TournamentTrade(
                    signal.variant_id, SYMBOL, signal.direction,
                    signal.signal_at, ensure_utc(rows[entry_index].timestamp), ensure_utc(bar.timestamp),
                    signal.signal_index, index, entry, target, signal.atr, stop, target,
                    gross_r, cost_r, gross_r - cost_r, bars_held, "TARGET_HIT",
                )
                break

        if trade is None:
            if last_index < entry_index + int(max_hold_bars):
                continue
            exit_bar = rows[last_index]
            exit_price = float(exit_bar.close)
            gross_r = (
                (exit_price - entry) / risk
                if signal.direction == "LONG"
                else (entry - exit_price) / risk
            )
            cost_r = _roundtrip_cost_r(risk_pips=risk_pips, bars_held=max_hold_bars, costs=costs)
            trade = TournamentTrade(
                signal.variant_id, SYMBOL, signal.direction,
                signal.signal_at, ensure_utc(rows[entry_index].timestamp), ensure_utc(exit_bar.timestamp),
                signal.signal_index, last_index, entry, exit_price, signal.atr, stop, target,
                gross_r, cost_r, gross_r - cost_r, max_hold_bars, "TIME_EXIT",
            )
        output.append(trade)
    return tuple(output)


def _metrics_pass(metrics: TournamentMetrics, cfg: Mapping[str, Any]) -> bool:
    return bool(
        metrics.win_rate is not None
        and metrics.win_rate >= float(cfg["win_rate_min"])
        and metrics.profit_factor is not None
        and metrics.profit_factor >= float(cfg["profit_factor_min"])
        and metrics.expectancy_r is not None
        and metrics.expectancy_r >= float(cfg["expectancy_r_min"])
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


def _daily_coverage(rows: Sequence[Bar], signals: Sequence[ContinuationSignal]) -> dict[str, Any]:
    all_days = sorted({ensure_utc(row.timestamp).date() for row in rows if ensure_utc(row.timestamp).weekday() < 5})
    signal_days = sorted({ensure_utc(signal.signal_at).date() for signal in signals})
    coverage = len(signal_days) / len(all_days) if all_days else 0.0
    return {
        "trading_days": len(all_days),
        "days_with_signal": len(signal_days),
        "signal_day_coverage": coverage,
        "signals": len(signals),
        "signals_per_signal_day": (len(signals) / len(signal_days)) if signal_days else 0.0,
    }


def evaluate_continuation_tournament(
    bars: Sequence[Bar],
    *,
    costs: M15ResearchCosts,
    stressed_costs: M15ResearchCosts,
    validation_cfg: Mapping[str, Any],
) -> dict[str, Any]:
    rows = _validate_bars(bars)
    split_index = max(EMA_SLOW + 10, min(len(rows) - 1, int(len(rows) * DEVELOPMENT_FRACTION)))
    development_rows = rows[:split_index]
    holdout_rows = rows[split_index:]

    evaluations: list[dict[str, Any]] = []
    trade_sets: dict[str, tuple[TournamentTrade, ...]] = {}
    stressed_trade_sets: dict[str, tuple[TournamentTrade, ...]] = {}
    signals_by_variant: dict[str, tuple[ContinuationSignal, ...]] = {}

    for variant in VARIANTS:
        signals = extract_signals(rows, variant=variant)
        base_trades = simulate_trades(rows, signals=signals, costs=costs)
        stressed_trades = simulate_trades(rows, signals=signals, costs=stressed_costs)
        signals_by_variant[variant.variant_id] = signals
        trade_sets[variant.variant_id] = base_trades
        stressed_trade_sets[variant.variant_id] = stressed_trades

        dev = tuple(t for t in base_trades if t.signal_index < split_index and t.exit_index < split_index)
        dev_stressed = tuple(t for t in stressed_trades if t.signal_index < split_index and t.exit_index < split_index)
        metrics = compute_metrics(dev)
        stressed_metrics = compute_metrics(dev_stressed)
        direction_metrics = {
            direction: compute_metrics(tuple(t for t in dev if t.direction == direction)).payload()
            for direction in ("LONG", "SHORT")
        }
        stressed_direction_metrics = {
            direction: compute_metrics(tuple(t for t in dev_stressed if t.direction == direction)).payload()
            for direction in ("LONG", "SHORT")
        }
        folds, pass_fraction, wf_passed = walk_forward(dev, validation_cfg["walk_forward"])
        stress_passed = _metrics_pass(stressed_metrics, validation_cfg["stress_acceptance"])
        development_passed = bool(
            metrics.completed_trades >= MIN_DEVELOPMENT_TRADES
            and wf_passed
            and stress_passed
        )
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
                    "passed": wf_passed,
                },
                "stress_passed": stress_passed,
                "development_passed": development_passed,
                "full_history_coverage": _daily_coverage(rows, signals),
            }
        )

    eligible = [row for row in evaluations if row["development_passed"]]
    eligible.sort(
        key=lambda row: (
            float(row["walk_forward"]["pass_fraction"]),
            float(row["stressed_development"].get("expectancy_r") or -999.0),
            float(row["stressed_development"].get("profit_factor") or -999.0),
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
            t for t in trade_sets[variant_id]
            if t.signal_index >= split_index and t.exit_index < len(rows)
        )
        holdout_stressed = tuple(
            t for t in stressed_trade_sets[variant_id]
            if t.signal_index >= split_index and t.exit_index < len(rows)
        )
        holdout_metrics = compute_metrics(holdout_base)
        holdout_stress_metrics = compute_metrics(holdout_stressed)
        promotion_eligible = bool(
            _final_oos_pass(holdout_metrics)
            and _metrics_pass(holdout_stress_metrics, validation_cfg["stress_acceptance"])
        )
        selected_signals = tuple(
            signal for signal in signals_by_variant[variant_id]
            if signal.signal_index >= split_index
        )
        holdout = {
            "variant_id": variant_id,
            "base": holdout_metrics.payload(),
            "stressed": holdout_stress_metrics.payload(),
            "coverage": _daily_coverage(holdout_rows, selected_signals),
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
            "Variant selection uses development + walk-forward + stressed costs only. "
            "Locked holdout is opened only for a development-passing variant."
        ),
    }

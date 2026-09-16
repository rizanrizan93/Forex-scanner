from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from statistics import median
from typing import Any, Mapping, Sequence

from .demo_donchian_adaptive_tournament import (
    TournamentMetrics,
    TournamentTrade,
    compute_metrics,
    walk_forward,
)
from .demo_xau_m15_ema_reversal_recovery import (
    ATR_PERIOD as EMA_ATR_PERIOD,
    EMA_FAST,
    EMA_MID,
    EMA_SLOW,
    EXTREME_LOOKBACK,
    IMPULSE_LOOKBACK as EMA_IMPULSE_LOOKBACK,
    STRATEGY_ID as EMA_STRATEGY_ID,
    TP2_R as EMA_TP2_R,
    _long_candidate as _ema_long_candidate,
    _short_candidate as _ema_short_candidate,
)
from .demo_xau_m15_liquidity_sweep_fade import (
    ATR_PERIOD as SWEEP_ATR_PERIOD,
    EMA_CONTEXT_PERIOD,
    IMPULSE_LOOKBACK as SWEEP_IMPULSE_LOOKBACK,
    STRATEGY_ID as SWEEP_STRATEGY_ID,
    SWEEP_LOOKBACK,
    TP2_R as SWEEP_TP2_R,
    _long_candidate as _sweep_long_candidate,
    _short_candidate as _sweep_short_candidate,
)
from .models import Bar, ensure_utc

RESEARCH_VERSION = "XAU_M15_DUAL_STRATEGY_HOLDOUT_V1"
ARTIFACT_CONTRACT = "XAU_M15_DUAL_STRATEGY_RESEARCH_EVIDENCE_1"
SYMBOL = "XAUUSD"
TIMEFRAME = "M15"
TIMEFRAME_SECONDS = 15 * 60
PIP_SIZE = 0.01
DEVELOPMENT_FRACTION = 0.60
MIN_DEVELOPMENT_TRADES = 130
MIN_HOLDOUT_TRADES = 100
MAX_HOLD_BARS = (16, 32, 64, 96)
COST_MODEL = "FULL_SPREAD_PLUS_SLIPPAGE_PLUS_COMMISSION_DEDUCTED_IN_R_STOP_FIRST"
EXECUTION_MODEL = "NEXT_M15_OPEN_STRUCTURAL_STOP_BROKER_TP2_INDEPENDENT_SIGNAL_OUTCOMES"


@dataclass(frozen=True, slots=True)
class M15ResearchCosts:
    spread_pips: float
    slippage_pips: float
    commission_pips_round_trip: float
    swap_pips_per_day: float
    spread_multiplier: float = 1.0
    slippage_multiplier: float = 1.0

    def __post_init__(self) -> None:
        values = (
            self.spread_pips,
            self.slippage_pips,
            self.commission_pips_round_trip,
            self.swap_pips_per_day,
        )
        if any(not isfinite(float(value)) or float(value) < 0.0 for value in values):
            raise ValueError("XAU_M15_RESEARCH_COSTS_INVALID")
        if self.spread_pips <= 0.0:
            raise ValueError("XAU_M15_RESEARCH_SPREAD_PROXY_REQUIRED")
        if self.spread_multiplier < 1.0 or self.slippage_multiplier < 1.0:
            raise ValueError("XAU_M15_RESEARCH_COST_MULTIPLIER_INVALID")

    def stressed(
        self,
        *,
        spread_multiplier: float,
        slippage_multiplier: float,
    ) -> "M15ResearchCosts":
        return M15ResearchCosts(
            spread_pips=self.spread_pips,
            slippage_pips=self.slippage_pips,
            commission_pips_round_trip=self.commission_pips_round_trip,
            swap_pips_per_day=self.swap_pips_per_day,
            spread_multiplier=self.spread_multiplier * float(spread_multiplier),
            slippage_multiplier=self.slippage_multiplier * float(slippage_multiplier),
        )


@dataclass(frozen=True, slots=True)
class SignalEvent:
    strategy_id: str
    signal_index: int
    direction: str
    signal_at: Any
    atr: float
    structural_stop: float
    reward_r: float


@dataclass(frozen=True, slots=True)
class HoldEvaluation:
    strategy_id: str
    max_hold_bars: int
    reward_r: float
    development_metrics: TournamentMetrics
    stressed_development_metrics: TournamentMetrics
    walk_forward_pass_fraction: float
    walk_forward_passed: bool
    development_stress_passed: bool
    development_passed: bool

    @property
    def variant_id(self) -> str:
        return f"{self.strategy_id}_H{self.max_hold_bars}"

    def payload(self) -> dict[str, Any]:
        return {
            "variant_id": self.variant_id,
            "strategy_id": self.strategy_id,
            "max_hold_bars": self.max_hold_bars,
            "max_hold_hours": self.max_hold_bars / 4.0,
            "reward_r": self.reward_r,
            "development": self.development_metrics.payload(),
            "stressed_development": self.stressed_development_metrics.payload(),
            "walk_forward_pass_fraction": self.walk_forward_pass_fraction,
            "walk_forward_passed": self.walk_forward_passed,
            "development_stress_passed": self.development_stress_passed,
            "development_passed": self.development_passed,
        }


def _validate_bars(bars: Sequence[Bar]) -> tuple[Bar, ...]:
    rows = tuple(sorted(bars, key=lambda row: ensure_utc(row.timestamp)))
    if not rows:
        raise ValueError("XAU_M15_RESEARCH_BARS_EMPTY")
    if any(row.symbol.upper() != SYMBOL or row.timeframe.upper() != TIMEFRAME for row in rows):
        raise ValueError("XAU_M15_RESEARCH_REQUIRES_XAUUSD_M15")
    if any(
        ensure_utc(rows[index].timestamp) >= ensure_utc(rows[index + 1].timestamp)
        for index in range(len(rows) - 1)
    ):
        raise ValueError("XAU_M15_RESEARCH_BARS_NOT_CHRONOLOGICAL")
    return rows


def _ema_series(values: Sequence[float], period: int) -> tuple[float, ...]:
    if period <= 0 or not values:
        return ()
    alpha = 2.0 / (period + 1.0)
    output = [float(values[0])]
    for raw in values[1:]:
        output.append(alpha * float(raw) + (1.0 - alpha) * output[-1])
    return tuple(output)


def _true_ranges(rows: Sequence[Bar]) -> tuple[float, ...]:
    output: list[float] = []
    previous_close: float | None = None
    for row in rows:
        high = float(row.high)
        low = float(row.low)
        value = high - low
        if previous_close is not None:
            value = max(value, abs(high - previous_close), abs(low - previous_close))
        output.append(value)
        previous_close = float(row.close)
    return tuple(output)


def _rolling_atr(rows: Sequence[Bar], period: int) -> tuple[float | None, ...]:
    tr = _true_ranges(rows)
    output: list[float | None] = [None] * len(rows)
    rolling = 0.0
    for index, value in enumerate(tr):
        rolling += float(value)
        if index >= period:
            rolling -= float(tr[index - period])
        if index >= period - 1:
            atr = rolling / float(period)
            output[index] = atr if isfinite(atr) and atr > 0.0 else None
    return tuple(output)


def infer_spread_proxy_pips(
    bars: Sequence[Bar],
    *,
    pip_size: float = PIP_SIZE,
) -> dict[str, Any]:
    rows = tuple(bars)
    if not rows or not isfinite(float(pip_size)) or pip_size <= 0:
        raise ValueError("XAU_M15_SPREAD_PROXY_INPUT_INVALID")
    positive = [
        max(0.0, float(row.spread_avg)) / float(pip_size)
        for row in rows
        if isfinite(float(row.spread_avg)) and float(row.spread_avg) > 0.0
    ]
    coverage = len(positive) / len(rows)
    if not positive:
        return {
            "available": False,
            "coverage": coverage,
            "median_pips": None,
            "minimum_pips": None,
            "maximum_pips": None,
            "provenance": "CTRADER_CURRENT_QUOTE_PROXY_ATTACHED_TO_HISTORICAL_BARS",
        }
    return {
        "available": True,
        "coverage": coverage,
        "median_pips": median(positive),
        "minimum_pips": min(positive),
        "maximum_pips": max(positive),
        "provenance": "CTRADER_CURRENT_QUOTE_PROXY_ATTACHED_TO_HISTORICAL_BARS",
    }


def extract_signal_events(bars: Sequence[Bar]) -> dict[str, tuple[SignalEvent, ...]]:
    rows = _validate_bars(bars)
    closes = [float(row.close) for row in rows]
    ema20 = _ema_series(closes, EMA_FAST)
    ema50 = _ema_series(closes, EMA_MID)
    ema200 = _ema_series(closes, EMA_SLOW)
    atr14 = _rolling_atr(rows, max(EMA_ATR_PERIOD, SWEEP_ATR_PERIOD))

    output: dict[str, list[SignalEvent]] = {
        EMA_STRATEGY_ID: [],
        SWEEP_STRATEGY_ID: [],
    }
    ema_minimum = max(EMA_SLOW + 5, EXTREME_LOOKBACK + EMA_IMPULSE_LOOKBACK + 5)
    sweep_minimum = max(EMA_CONTEXT_PERIOD + 5, SWEEP_LOOKBACK + SWEEP_IMPULSE_LOOKBACK + 5)

    for index in range(1, len(rows) - 1):
        atr = atr14[index]
        if atr is None:
            continue
        recent = rows[max(0, index - 40):index + 1]
        row = rows[index]

        if index + 1 >= ema_minimum:
            passed = False
            metrics: dict[str, float | None] = {}
            direction: str | None = None
            if ema20[index] < ema50[index] < ema200[index]:
                passed, metrics, _ = _ema_long_candidate(
                    recent,
                    row=row,
                    previous=rows[index - 1],
                    atr=float(atr),
                    ema20=ema20[index],
                    ema50=ema50[index],
                    ema200=ema200[index],
                )
                direction = "LONG"
            elif ema20[index] > ema50[index] > ema200[index]:
                passed, metrics, _ = _ema_short_candidate(
                    recent,
                    row=row,
                    previous=rows[index - 1],
                    atr=float(atr),
                    ema20=ema20[index],
                    ema50=ema50[index],
                    ema200=ema200[index],
                )
                direction = "SHORT"
            if passed and direction is not None:
                stop = float(metrics["structural_stop"] or 0.0)
                if stop > 0.0:
                    output[EMA_STRATEGY_ID].append(
                        SignalEvent(
                            strategy_id=EMA_STRATEGY_ID,
                            signal_index=index,
                            direction=direction,
                            signal_at=ensure_utc(row.timestamp),
                            atr=float(atr),
                            structural_stop=stop,
                            reward_r=float(EMA_TP2_R),
                        )
                    )

        if index + 1 >= sweep_minimum:
            short_pass, short_metrics, _ = _sweep_short_candidate(
                recent,
                row=row,
                atr=float(atr),
                ema20=ema20[index],
            )
            long_pass, long_metrics, _ = _sweep_long_candidate(
                recent,
                row=row,
                atr=float(atr),
                ema20=ema20[index],
            )
            if short_pass ^ long_pass:
                direction = "SHORT" if short_pass else "LONG"
                metrics = short_metrics if short_pass else long_metrics
                stop = float(metrics["structural_stop"])
                if stop > 0.0:
                    output[SWEEP_STRATEGY_ID].append(
                        SignalEvent(
                            strategy_id=SWEEP_STRATEGY_ID,
                            signal_index=index,
                            direction=direction,
                            signal_at=ensure_utc(row.timestamp),
                            atr=float(atr),
                            structural_stop=stop,
                            reward_r=float(SWEEP_TP2_R),
                        )
                    )

    return {key: tuple(value) for key, value in output.items()}


def _roundtrip_cost_r(
    *,
    risk_pips: float,
    bars_held: int,
    costs: M15ResearchCosts,
) -> float:
    if risk_pips <= 0:
        raise ValueError("XAU_M15_RESEARCH_RISK_PIPS_INVALID")
    elapsed_days = max(0, int(bars_held)) * TIMEFRAME_SECONDS / 86400.0
    total_pips = (
        costs.spread_pips * costs.spread_multiplier
        + costs.slippage_pips * costs.slippage_multiplier
        + costs.commission_pips_round_trip
        + costs.swap_pips_per_day * elapsed_days
    )
    return total_pips / risk_pips


def _trade_outcome(
    *,
    rows: Sequence[Bar],
    event: SignalEvent,
    max_hold_bars: int,
    costs: M15ResearchCosts,
    pip_size: float,
) -> TournamentTrade | None:
    entry_index = event.signal_index + 1
    if entry_index >= len(rows):
        return None
    entry = float(rows[entry_index].open)
    stop = float(event.structural_stop)
    direction = event.direction
    risk_price = entry - stop if direction == "LONG" else stop - entry
    if not isfinite(risk_price) or risk_price <= 0.0:
        return None
    risk_pips = risk_price / pip_size
    target = (
        entry + event.reward_r * risk_price
        if direction == "LONG"
        else entry - event.reward_r * risk_price
    )
    if target <= 0.0:
        return None

    last_index = min(len(rows) - 1, entry_index + int(max_hold_bars))
    for index in range(entry_index, last_index + 1):
        bar = rows[index]
        if direction == "LONG":
            stop_hit = float(bar.low) <= stop
            target_hit = float(bar.high) >= target
        else:
            stop_hit = float(bar.high) >= stop
            target_hit = float(bar.low) <= target
        raw_target_hit = target_hit
        if index == entry_index:
            target_hit = False
        bars_held = index - entry_index
        cost_r = _roundtrip_cost_r(
            risk_pips=risk_pips,
            bars_held=bars_held,
            costs=costs,
        )
        variant_id = f"{event.strategy_id}_H{max_hold_bars}"
        if stop_hit:
            gross_r = -1.0
            return TournamentTrade(
                variant_id, SYMBOL, direction,
                event.signal_at, ensure_utc(rows[entry_index].timestamp), ensure_utc(bar.timestamp),
                event.signal_index, index, entry, stop, event.atr, stop, target,
                gross_r, cost_r, gross_r - cost_r, bars_held,
                "STOP_FIRST_AMBIGUOUS" if raw_target_hit else "STOP_HIT",
            )
        if target_hit:
            gross_r = float(event.reward_r)
            return TournamentTrade(
                variant_id, SYMBOL, direction,
                event.signal_at, ensure_utc(rows[entry_index].timestamp), ensure_utc(bar.timestamp),
                event.signal_index, index, entry, target, event.atr, stop, target,
                gross_r, cost_r, gross_r - cost_r, bars_held, "TARGET_HIT",
            )

    if last_index < entry_index + int(max_hold_bars):
        return None
    exit_bar = rows[last_index]
    exit_price = float(exit_bar.close)
    gross_r = (
        (exit_price - entry) / risk_price
        if direction == "LONG"
        else (entry - exit_price) / risk_price
    )
    cost_r = _roundtrip_cost_r(
        risk_pips=risk_pips,
        bars_held=max_hold_bars,
        costs=costs,
    )
    return TournamentTrade(
        f"{event.strategy_id}_H{max_hold_bars}", SYMBOL, direction,
        event.signal_at, ensure_utc(rows[entry_index].timestamp), ensure_utc(exit_bar.timestamp),
        event.signal_index, last_index, entry, exit_price, event.atr, stop, target,
        gross_r, cost_r, gross_r - cost_r, max_hold_bars, "TIME_EXIT",
    )


def simulate_hold_variant(
    bars: Sequence[Bar],
    *,
    events: Sequence[SignalEvent],
    max_hold_bars: int,
    costs: M15ResearchCosts,
    pip_size: float = PIP_SIZE,
) -> tuple[TournamentTrade, ...]:
    if max_hold_bars not in MAX_HOLD_BARS:
        raise ValueError("XAU_M15_MAX_HOLD_NOT_PREREGISTERED")
    rows = _validate_bars(bars)
    output = []
    for event in events:
        trade = _trade_outcome(
            rows=rows,
            event=event,
            max_hold_bars=max_hold_bars,
            costs=costs,
            pip_size=float(pip_size),
        )
        if trade is not None:
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


def evaluate_hold_variant(
    *,
    strategy_id: str,
    max_hold_bars: int,
    reward_r: float,
    development_base: Sequence[TournamentTrade],
    development_stressed: Sequence[TournamentTrade],
    validation_cfg: Mapping[str, Any],
) -> HoldEvaluation:
    base = compute_metrics(development_base)
    stressed = compute_metrics(development_stressed)
    _, pass_fraction, wf_passed = walk_forward(
        development_base,
        validation_cfg["walk_forward"],
    )
    stress_passed = _metrics_pass(stressed, validation_cfg["stress_acceptance"])
    development_passed = bool(
        base.completed_trades >= MIN_DEVELOPMENT_TRADES
        and wf_passed
        and stress_passed
    )
    return HoldEvaluation(
        strategy_id=strategy_id,
        max_hold_bars=max_hold_bars,
        reward_r=reward_r,
        development_metrics=base,
        stressed_development_metrics=stressed,
        walk_forward_pass_fraction=pass_fraction,
        walk_forward_passed=wf_passed,
        development_stress_passed=stress_passed,
        development_passed=development_passed,
    )


def select_on_development(evaluations: Sequence[HoldEvaluation]) -> HoldEvaluation | None:
    eligible = [row for row in evaluations if row.development_passed]
    if not eligible:
        return None
    eligible.sort(
        key=lambda row: (
            row.walk_forward_pass_fraction,
            row.stressed_development_metrics.expectancy_r
            if row.stressed_development_metrics.expectancy_r is not None else -999.0,
            row.stressed_development_metrics.profit_factor
            if row.stressed_development_metrics.profit_factor is not None else -999.0,
            row.development_metrics.expectancy_r
            if row.development_metrics.expectancy_r is not None else -999.0,
            -row.development_metrics.max_drawdown_r,
            -row.max_hold_bars,
        ),
        reverse=True,
    )
    return eligible[0]


def evaluate_strategy(
    *,
    bars: Sequence[Bar],
    events: Sequence[SignalEvent],
    strategy_id: str,
    reward_r: float,
    costs: M15ResearchCosts,
    stressed_costs: M15ResearchCosts,
    validation_cfg: Mapping[str, Any],
    split_index: int,
) -> dict[str, Any]:
    rows = _validate_bars(bars)
    evaluations: list[HoldEvaluation] = []
    base_by_hold: dict[int, tuple[TournamentTrade, ...]] = {}
    stressed_by_hold: dict[int, tuple[TournamentTrade, ...]] = {}

    for hold in MAX_HOLD_BARS:
        base_all = simulate_hold_variant(rows, events=events, max_hold_bars=hold, costs=costs)
        stress_all = simulate_hold_variant(
            rows,
            events=events,
            max_hold_bars=hold,
            costs=stressed_costs,
        )
        base_by_hold[hold] = base_all
        stressed_by_hold[hold] = stress_all
        development_base = tuple(
            trade for trade in base_all
            if trade.signal_index < split_index and trade.exit_index < split_index
        )
        development_stressed = tuple(
            trade for trade in stress_all
            if trade.signal_index < split_index and trade.exit_index < split_index
        )
        evaluations.append(
            evaluate_hold_variant(
                strategy_id=strategy_id,
                max_hold_bars=hold,
                reward_r=reward_r,
                development_base=development_base,
                development_stressed=development_stressed,
                validation_cfg=validation_cfg,
            )
        )

    selected = select_on_development(evaluations)
    if selected is None:
        return {
            "strategy_id": strategy_id,
            "stage": "RESEARCH_ONLY",
            "development_pass": False,
            "holdout_opened": False,
            "holdout_pass": False,
            "selected_max_hold_bars": None,
            "reason": "NO_MAX_HOLD_VARIANT_PASSED_DEVELOPMENT_GATES",
            "signal_count": len(events),
            "development_evaluations": [row.payload() for row in evaluations],
            "execution_influence": False,
            "policy_effect": "SHADOW_ONLY",
        }

    hold = selected.max_hold_bars
    holdout_base = tuple(
        trade for trade in base_by_hold[hold]
        if trade.signal_index >= split_index
    )
    holdout_stressed = tuple(
        trade for trade in stressed_by_hold[hold]
        if trade.signal_index >= split_index
    )
    base_metrics = compute_metrics(holdout_base)
    stressed_metrics = compute_metrics(holdout_stressed)
    sample_pass = base_metrics.completed_trades >= MIN_HOLDOUT_TRADES
    base_pass = _metrics_pass(base_metrics, validation_cfg["stress_acceptance"])
    stress_pass = _metrics_pass(stressed_metrics, validation_cfg["stress_acceptance"])
    holdout_pass = bool(sample_pass and base_pass and stress_pass)

    return {
        "strategy_id": strategy_id,
        "stage": "FORWARD_SHADOW_ELIGIBLE" if holdout_pass else "RESEARCH_ONLY",
        "development_pass": True,
        "holdout_opened": True,
        "holdout_pass": holdout_pass,
        "holdout_sample_pass": sample_pass,
        "minimum_holdout_trades": MIN_HOLDOUT_TRADES,
        "selected_max_hold_bars": hold,
        "selected_max_hold_hours": hold / 4.0,
        "reward_r": reward_r,
        "signal_count": len(events),
        "development_evaluations": [row.payload() for row in evaluations],
        "holdout": base_metrics.payload(),
        "stressed_holdout": stressed_metrics.payload(),
        "reason": "UNTOUCHED_HOLDOUT_PASS" if holdout_pass else "UNTOUCHED_HOLDOUT_FAILED",
        "execution_influence": False,
        "policy_effect": "SHADOW_ONLY",
    }


def evaluate_dual_strategy_research(
    bars: Sequence[Bar],
    *,
    costs: M15ResearchCosts,
    stressed_costs: M15ResearchCosts,
    validation_cfg: Mapping[str, Any],
) -> dict[str, Any]:
    rows = _validate_bars(bars)
    split_index = int(len(rows) * DEVELOPMENT_FRACTION)
    split_index = max(EMA_SLOW + 5, min(split_index, len(rows) - 2))
    events = extract_signal_events(rows)
    strategies = (
        evaluate_strategy(
            bars=rows,
            events=events[EMA_STRATEGY_ID],
            strategy_id=EMA_STRATEGY_ID,
            reward_r=float(EMA_TP2_R),
            costs=costs,
            stressed_costs=stressed_costs,
            validation_cfg=validation_cfg,
            split_index=split_index,
        ),
        evaluate_strategy(
            bars=rows,
            events=events[SWEEP_STRATEGY_ID],
            strategy_id=SWEEP_STRATEGY_ID,
            reward_r=float(SWEEP_TP2_R),
            costs=costs,
            stressed_costs=stressed_costs,
            validation_cfg=validation_cfg,
            split_index=split_index,
        ),
    )
    return {
        "research_version": RESEARCH_VERSION,
        "artifact_contract": ARTIFACT_CONTRACT,
        "symbol": SYMBOL,
        "timeframe": TIMEFRAME,
        "bar_count": len(rows),
        "first_bar_at": ensure_utc(rows[0].timestamp).isoformat(),
        "last_bar_at": ensure_utc(rows[-1].timestamp).isoformat(),
        "development_fraction": DEVELOPMENT_FRACTION,
        "split_index": split_index,
        "split_at": ensure_utc(rows[split_index].timestamp).isoformat(),
        "max_hold_candidates_bars": list(MAX_HOLD_BARS),
        "max_hold_candidates_hours": [value / 4.0 for value in MAX_HOLD_BARS],
        "minimum_development_trades": MIN_DEVELOPMENT_TRADES,
        "minimum_holdout_trades": MIN_HOLDOUT_TRADES,
        "execution_model": EXECUTION_MODEL,
        "cost_model": COST_MODEL,
        "selection_uses_holdout": False,
        "development_trade_crosses_split_excluded": True,
        "strategies": list(strategies),
        "execution_influence": False,
        "policy_effect": "SHADOW_ONLY",
    }

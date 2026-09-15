from __future__ import annotations

from dataclasses import asdict, dataclass
from math import isfinite
from typing import Any, Mapping, Sequence

from .models import Bar

TOURNAMENT_VERSION = "DONCHIAN_ATR_H1_TOURNAMENT_V1"
LOOKBACKS = (10, 20, 30, 55)
ATR_PERIODS = (10, 14, 20)
BREAKOUT_BUFFERS_ATR = (0.0, 0.10, 0.20, 0.30)
STOP_ATR = 2.0
REWARD_R = 2.0
MAX_HOLD_H1 = 72
TIMEFRAME_SECONDS = 3600


@dataclass(frozen=True, slots=True)
class DonchianVariant:
    lookback: int
    atr_period: int
    buffer_atr: float

    def __post_init__(self) -> None:
        if self.lookback not in LOOKBACKS:
            raise ValueError("DONCHIAN_LOOKBACK_NOT_PREREGISTERED")
        if self.atr_period not in ATR_PERIODS:
            raise ValueError("DONCHIAN_ATR_PERIOD_NOT_PREREGISTERED")
        if self.buffer_atr not in BREAKOUT_BUFFERS_ATR:
            raise ValueError("DONCHIAN_BUFFER_NOT_PREREGISTERED")

    @property
    def strategy_id(self) -> str:
        buffer_bps = int(round(self.buffer_atr * 100))
        return f"DONCHIAN_H1_L{self.lookback}_ATR{self.atr_period}_B{buffer_bps:02d}_V1"


@dataclass(frozen=True, slots=True)
class TournamentCosts:
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
            raise ValueError("DONCHIAN_COSTS_INVALID")
        if self.spread_multiplier < 1.0 or self.slippage_multiplier < 1.0:
            raise ValueError("DONCHIAN_COST_MULTIPLIER_INVALID")

    def stressed(self, *, spread_multiplier: float, slippage_multiplier: float) -> "TournamentCosts":
        return TournamentCosts(
            spread_pips=self.spread_pips,
            slippage_pips=self.slippage_pips,
            commission_pips_round_trip=self.commission_pips_round_trip,
            swap_pips_per_day=self.swap_pips_per_day,
            spread_multiplier=self.spread_multiplier * float(spread_multiplier),
            slippage_multiplier=self.slippage_multiplier * float(slippage_multiplier),
        )


@dataclass(frozen=True, slots=True)
class TournamentTrade:
    strategy_id: str
    symbol: str
    direction: str
    signal_at: Any
    entry_at: Any
    exit_at: Any
    signal_index: int
    exit_index: int
    entry_price: float
    exit_price: float
    atr_at_signal: float
    stop_loss: float
    take_profit: float
    gross_r: float
    cost_r: float
    net_r: float
    bars_held: int
    exit_reason: str


@dataclass(frozen=True, slots=True)
class TournamentMetrics:
    completed_trades: int
    wins: int
    losses: int
    breakeven: int
    win_rate: float | None
    profit_factor: float | None
    expectancy_r: float | None
    gross_profit_r: float
    gross_loss_r: float
    max_drawdown_r: float
    max_losing_streak: int
    average_cost_r: float | None

    def payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class WalkForwardFold:
    fold: int
    train_trades: int
    test_trades: int
    test_metrics: TournamentMetrics
    passed: bool


@dataclass(frozen=True, slots=True)
class VariantEvaluation:
    variant: DonchianVariant
    base_metrics: TournamentMetrics
    stressed_metrics: TournamentMetrics
    folds: tuple[WalkForwardFold, ...]
    walk_forward_pass_fraction: float
    walk_forward_passed: bool
    stress_passed: bool
    preliminary_eligible: bool

    def payload(self) -> dict[str, Any]:
        return {
            "strategy_id": self.variant.strategy_id,
            "params": asdict(self.variant),
            "base": self.base_metrics.payload(),
            "stressed": self.stressed_metrics.payload(),
            "walk_forward": {
                "folds": [
                    {
                        "fold": fold.fold,
                        "train_trades": fold.train_trades,
                        "test_trades": fold.test_trades,
                        "passed": fold.passed,
                        "test_metrics": fold.test_metrics.payload(),
                    }
                    for fold in self.folds
                ],
                "pass_fraction": self.walk_forward_pass_fraction,
                "passed": self.walk_forward_passed,
            },
            "stress_passed": self.stress_passed,
            "preliminary_eligible": self.preliminary_eligible,
        }


def parameter_grid() -> tuple[DonchianVariant, ...]:
    return tuple(
        DonchianVariant(lookback, atr_period, buffer)
        for lookback in LOOKBACKS
        for atr_period in ATR_PERIODS
        for buffer in BREAKOUT_BUFFERS_ATR
    )


def _validate_bars(bars: Sequence[Bar], symbol: str) -> tuple[Bar, ...]:
    rows = tuple(bars)
    if any(row.symbol != symbol.upper() or row.timeframe != "H1" for row in rows):
        raise ValueError("DONCHIAN_TOURNAMENT_REQUIRES_ONE_H1_SYMBOL")
    if any(rows[index].timestamp >= rows[index + 1].timestamp for index in range(len(rows) - 1)):
        raise ValueError("DONCHIAN_TOURNAMENT_BARS_NOT_CHRONOLOGICAL")
    return rows


def _true_range(current: Bar, previous_close: float) -> float:
    return max(
        float(current.high) - float(current.low),
        abs(float(current.high) - previous_close),
        abs(float(current.low) - previous_close),
    )


def _atr_at(rows: Sequence[Bar], index: int, period: int) -> float | None:
    start = max(0, index - period + 1)
    values: list[float] = []
    for offset in range(start, index + 1):
        previous_close = float(rows[offset - 1].close) if offset > 0 else float(rows[offset].close)
        values.append(_true_range(rows[offset], previous_close))
    if len(values) < period:
        return None
    value = sum(values) / len(values)
    return value if isfinite(value) and value > 0 else None


def _spread_pips(bar: Bar, pip_size: float, costs: TournamentCosts) -> float:
    observed = max(0.0, float(bar.spread_avg) / pip_size)
    return max(float(costs.spread_pips), observed) * float(costs.spread_multiplier)


def _cost_r(
    *,
    risk_pips: float,
    bars_held: int,
    costs: TournamentCosts,
) -> float:
    if risk_pips <= 0:
        raise ValueError("DONCHIAN_RISK_PIPS_INVALID")
    elapsed_days = max(0, bars_held) * TIMEFRAME_SECONDS / 86400.0
    slippage = float(costs.slippage_pips) * float(costs.slippage_multiplier)
    cost_pips = (
        0.5 * slippage
        + float(costs.commission_pips_round_trip)
        + float(costs.swap_pips_per_day) * elapsed_days
    )
    return cost_pips / risk_pips


def _trade_outcome(
    *,
    rows: Sequence[Bar],
    symbol: str,
    signal_index: int,
    direction: str,
    atr_value: float,
    pip_size: float,
    costs: TournamentCosts,
    variant: DonchianVariant,
) -> TournamentTrade | None:
    entry_index = signal_index + 1
    if entry_index >= len(rows):
        return None
    entry_bar = rows[entry_index]
    entry_spread = _spread_pips(entry_bar, pip_size, costs)
    slippage = float(costs.slippage_pips) * float(costs.slippage_multiplier)
    entry_adverse = 0.5 * (entry_spread + slippage) * pip_size
    raw_open = float(entry_bar.open)
    entry = raw_open + entry_adverse if direction == "LONG" else raw_open - entry_adverse
    risk_price = STOP_ATR * atr_value
    if risk_price <= 0:
        return None
    stop = entry - risk_price if direction == "LONG" else entry + risk_price
    target_distance = REWARD_R * risk_price
    target = entry + target_distance if direction == "LONG" else entry - target_distance
    risk_pips = risk_price / pip_size

    last_index = min(len(rows) - 1, entry_index + MAX_HOLD_H1)
    for index in range(entry_index, last_index + 1):
        bar = rows[index]
        exit_spread = _spread_pips(bar, pip_size, costs)
        half_exit_spread = 0.5 * exit_spread * pip_size
        if direction == "LONG":
            stop_hit = float(bar.low) - half_exit_spread <= stop
            target_hit = float(bar.high) - half_exit_spread >= target
        else:
            stop_hit = float(bar.high) + half_exit_spread >= stop
            target_hit = float(bar.low) + half_exit_spread <= target

        # The exact intrabar sequence on the entry candle is unknowable. Preserve
        # the repository's conservative convention: stop may count immediately,
        # but a target is not eligible until the next completed H1 candle.
        raw_target_hit = target_hit
        if index == entry_index:
            target_hit = False

        bars_held = index - entry_index
        cost_r = _cost_r(risk_pips=risk_pips, bars_held=bars_held, costs=costs)
        if stop_hit:
            gross_r = -1.0
            return TournamentTrade(
                variant.strategy_id, symbol, direction,
                rows[signal_index].timestamp, entry_bar.timestamp, bar.timestamp,
                signal_index, index, entry, stop, atr_value, stop, target,
                gross_r, cost_r, gross_r - cost_r, bars_held,
                "STOP_FIRST_AMBIGUOUS" if raw_target_hit else "STOP_HIT",
            )
        if target_hit:
            gross_r = REWARD_R
            return TournamentTrade(
                variant.strategy_id, symbol, direction,
                rows[signal_index].timestamp, entry_bar.timestamp, bar.timestamp,
                signal_index, index, entry, target, atr_value, stop, target,
                gross_r, cost_r, gross_r - cost_r, bars_held, "TARGET_HIT",
            )

    # A fully observable time exit is included; history-ending open trades are not.
    if last_index < entry_index + MAX_HOLD_H1:
        return None
    bar = rows[last_index]
    exit_spread = _spread_pips(bar, pip_size, costs)
    exit_adverse = 0.5 * exit_spread * pip_size
    exit_price = float(bar.close) - exit_adverse if direction == "LONG" else float(bar.close) + exit_adverse
    gross_r = (
        (exit_price - entry) / risk_price
        if direction == "LONG"
        else (entry - exit_price) / risk_price
    )
    cost_r = _cost_r(risk_pips=risk_pips, bars_held=MAX_HOLD_H1, costs=costs)
    return TournamentTrade(
        variant.strategy_id, symbol, direction,
        rows[signal_index].timestamp, entry_bar.timestamp, bar.timestamp,
        signal_index, last_index, entry, exit_price, atr_value, stop, target,
        gross_r, cost_r, gross_r - cost_r, MAX_HOLD_H1, "TIME_EXIT",
    )


def simulate_variant(
    bars: Sequence[Bar],
    *,
    symbol: str,
    pip_size: float,
    variant: DonchianVariant,
    costs: TournamentCosts,
) -> tuple[TournamentTrade, ...]:
    if not isfinite(float(pip_size)) or pip_size <= 0:
        raise ValueError("DONCHIAN_PIP_SIZE_INVALID")
    rows = _validate_bars(bars, symbol)
    warmup = max(variant.lookback, variant.atr_period)
    trades: list[TournamentTrade] = []
    index = warmup
    while index < len(rows) - 1:
        atr_value = _atr_at(rows, index, variant.atr_period)
        if atr_value is None:
            index += 1
            continue
        channel = rows[index - variant.lookback:index]
        upper = max(float(row.high) for row in channel)
        lower = min(float(row.low) for row in channel)
        close = float(rows[index].close)
        buffer_abs = variant.buffer_atr * atr_value
        direction = None
        if close >= upper + buffer_abs:
            direction = "LONG"
        elif close <= lower - buffer_abs:
            direction = "SHORT"
        if direction is None:
            index += 1
            continue
        trade = _trade_outcome(
            rows=rows,
            symbol=symbol.upper(),
            signal_index=index,
            direction=direction,
            atr_value=atr_value,
            pip_size=float(pip_size),
            costs=costs,
            variant=variant,
        )
        if trade is None:
            index += 1
            continue
        trades.append(trade)
        # One position per symbol/variant. No overlapping backtest trades.
        index = max(index + 1, trade.exit_index + 1)
    return tuple(trades)


def compute_metrics(trades: Sequence[TournamentTrade]) -> TournamentMetrics:
    values = tuple(sorted(trades, key=lambda row: (row.exit_at, row.symbol, row.strategy_id)))
    if not values:
        return TournamentMetrics(0, 0, 0, 0, None, None, None, 0.0, 0.0, 0.0, 0, None)
    returns = [float(row.net_r) for row in values]
    wins = sum(value > 0 for value in returns)
    losses = sum(value < 0 for value in returns)
    breakeven = len(returns) - wins - losses
    gross_profit = sum(value for value in returns if value > 0)
    gross_loss = abs(sum(value for value in returns if value < 0))
    profit_factor = None if gross_loss <= 1e-12 else gross_profit / gross_loss
    equity = peak = max_drawdown = 0.0
    loss_streak = max_loss_streak = 0
    for value in returns:
        equity += value
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
        if value < 0:
            loss_streak += 1
            max_loss_streak = max(max_loss_streak, loss_streak)
        else:
            loss_streak = 0
    return TournamentMetrics(
        completed_trades=len(values),
        wins=wins,
        losses=losses,
        breakeven=breakeven,
        win_rate=wins / len(values),
        profit_factor=profit_factor,
        expectancy_r=sum(returns) / len(returns),
        gross_profit_r=gross_profit,
        gross_loss_r=gross_loss,
        max_drawdown_r=max_drawdown,
        max_losing_streak=max_loss_streak,
        average_cost_r=sum(float(row.cost_r) for row in values) / len(values),
    )


def _metric_pass(metrics: TournamentMetrics, cfg: Mapping[str, Any]) -> bool:
    return bool(
        metrics.win_rate is not None
        and metrics.win_rate >= float(cfg["win_rate_min"])
        and metrics.profit_factor is not None
        and metrics.profit_factor >= float(cfg["profit_factor_min"])
        and metrics.expectancy_r is not None
        and metrics.expectancy_r >= float(cfg["expectancy_r_min"])
    )


def walk_forward(
    trades: Sequence[TournamentTrade],
    cfg: Mapping[str, Any],
) -> tuple[tuple[WalkForwardFold, ...], float, bool]:
    values = tuple(sorted(trades, key=lambda row: (row.exit_at, row.symbol, row.strategy_id)))
    n = len(values)
    train_size = max(int(cfg["minimum_train_trades"]), int(n * float(cfg["train_fraction"])))
    test_size = max(int(cfg["minimum_test_trades"]), int(n * float(cfg["test_fraction"])))
    step = max(1, int(n * float(cfg["step_fraction"])))
    folds: list[WalkForwardFold] = []
    start = 0
    fold_number = 1
    while start + train_size + test_size <= n:
        train_end = start + train_size
        test_end = train_end + test_size
        test_metrics = compute_metrics(values[train_end:test_end])
        passed = bool(
            test_metrics.completed_trades >= int(cfg["minimum_test_trades"])
            and test_metrics.win_rate is not None
            and test_metrics.win_rate >= float(cfg["fold_win_rate_min"])
            and test_metrics.profit_factor is not None
            and test_metrics.profit_factor >= float(cfg["fold_profit_factor_min"])
            and test_metrics.expectancy_r is not None
            and test_metrics.expectancy_r >= float(cfg["fold_expectancy_r_min"])
        )
        folds.append(WalkForwardFold(fold_number, train_size, test_size, test_metrics, passed))
        fold_number += 1
        start += step
    if not folds:
        return (), 0.0, False
    fraction = sum(int(fold.passed) for fold in folds) / len(folds)
    return tuple(folds), fraction, fraction >= float(cfg["minimum_pass_fraction"])


def evaluate_variant(
    *,
    variant: DonchianVariant,
    base_trades: Sequence[TournamentTrade],
    stressed_trades: Sequence[TournamentTrade],
    validation_cfg: Mapping[str, Any],
) -> VariantEvaluation:
    base_metrics = compute_metrics(base_trades)
    stressed_metrics = compute_metrics(stressed_trades)
    folds, pass_fraction, wf_passed = walk_forward(base_trades, validation_cfg["walk_forward"])
    stress_passed = _metric_pass(stressed_metrics, validation_cfg["stress_acceptance"])
    minimum_sample = int(validation_cfg["walk_forward"]["minimum_train_trades"]) + int(
        validation_cfg["walk_forward"]["minimum_test_trades"]
    )
    preliminary = bool(
        base_metrics.completed_trades >= minimum_sample
        and wf_passed
        and stress_passed
    )
    return VariantEvaluation(
        variant=variant,
        base_metrics=base_metrics,
        stressed_metrics=stressed_metrics,
        folds=folds,
        walk_forward_pass_fraction=pass_fraction,
        walk_forward_passed=wf_passed,
        stress_passed=stress_passed,
        preliminary_eligible=preliminary,
    )


def _axis_neighbors(candidate: DonchianVariant) -> tuple[DonchianVariant, ...]:
    output: list[DonchianVariant] = []
    dimensions = (
        (LOOKBACKS, "lookback"),
        (ATR_PERIODS, "atr_period"),
        (BREAKOUT_BUFFERS_ATR, "buffer_atr"),
    )
    for values, field in dimensions:
        current = getattr(candidate, field)
        position = values.index(current)
        for neighbor_position in (position - 1, position + 1):
            if not 0 <= neighbor_position < len(values):
                continue
            kwargs = asdict(candidate)
            kwargs[field] = values[neighbor_position]
            output.append(DonchianVariant(**kwargs))
    return tuple(output)


def choose_candidate(
    evaluations: Sequence[VariantEvaluation],
    validation_cfg: Mapping[str, Any],
) -> dict[str, Any]:
    rows = tuple(evaluations)
    eligible = [row for row in rows if row.preliminary_eligible]
    if not eligible:
        return {
            "stage": "RESEARCH_ONLY",
            "selected_strategy_id": None,
            "historical_pass": False,
            "parameter_stability_pass": False,
            "reason": "NO_VARIANT_PASSED_WALK_FORWARD_AND_STRESS",
        }
    # Lexicographic ranking avoids inventing an opaque weighted score.
    eligible.sort(
        key=lambda row: (
            row.walk_forward_pass_fraction,
            row.stressed_metrics.expectancy_r if row.stressed_metrics.expectancy_r is not None else -999.0,
            row.stressed_metrics.profit_factor if row.stressed_metrics.profit_factor is not None else -999.0,
            row.base_metrics.expectancy_r if row.base_metrics.expectancy_r is not None else -999.0,
            -row.base_metrics.max_drawdown_r,
        ),
        reverse=True,
    )
    selected = eligible[0]
    by_id = {row.variant.strategy_id: row for row in rows}
    neighbors = _axis_neighbors(selected.variant)
    neighbor_rows = [by_id[item.strategy_id] for item in neighbors if item.strategy_id in by_id]
    perturbation_cfg = validation_cfg["parameter_perturbation"]
    minimum_variants = int(perturbation_cfg["minimum_variants"])
    passing_neighbors = sum(row.preliminary_eligible for row in neighbor_rows)
    stability_fraction = None if not neighbor_rows else passing_neighbors / len(neighbor_rows)
    stable = bool(
        len(neighbor_rows) >= minimum_variants
        and stability_fraction is not None
        and stability_fraction >= float(perturbation_cfg["minimum_pass_fraction"])
    )
    return {
        "stage": "FORWARD_SHADOW_ELIGIBLE" if stable else "HISTORICAL_CANDIDATE_UNSTABLE",
        "selected_strategy_id": selected.variant.strategy_id,
        "selected_params": asdict(selected.variant),
        "historical_pass": True,
        "parameter_stability_pass": stable,
        "neighbor_count": len(neighbor_rows),
        "passing_neighbors": passing_neighbors,
        "neighbor_pass_fraction": stability_fraction,
        "minimum_neighbor_variants": minimum_variants,
        "minimum_neighbor_pass_fraction": float(perturbation_cfg["minimum_pass_fraction"]),
        "selected_evaluation": selected.payload(),
        "reason": "HISTORICAL_AND_STABILITY_PASS" if stable else "PARAMETER_NEIGHBORHOOD_NOT_ROBUST",
        "execution_influence": False,
        "policy_effect": "SHADOW_ONLY",
    }

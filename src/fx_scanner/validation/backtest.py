from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from math import isfinite
from typing import Mapping, Sequence

from ..exceptions import DataContractError
from ..models import Bar, ensure_utc


class TradeOutcome(StrEnum):
    WIN = "WIN"
    LOSS = "LOSS"
    BREAKEVEN = "BREAKEVEN"
    MISSED = "MISSED"
    EXPIRED = "EXPIRED"
    OPEN = "OPEN"


@dataclass(frozen=True, slots=True)
class CostModel:
    spread_pips: float
    slippage_pips: float
    commission_pips_round_trip: float
    swap_pips_per_day: float = 0.0

    def __post_init__(self) -> None:
        for name in (
            "spread_pips",
            "slippage_pips",
            "commission_pips_round_trip",
            "swap_pips_per_day",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isfinite(float(value)) or value < 0:
                raise DataContractError(f"{name} must be non-negative finite")

    def stressed(self, *, spread_multiplier: float, slippage_multiplier: float) -> "CostModel":
        if spread_multiplier < 1 or slippage_multiplier < 1:
            raise DataContractError("stress multipliers cannot reduce costs")
        return CostModel(
            spread_pips=self.spread_pips * spread_multiplier,
            slippage_pips=self.slippage_pips * slippage_multiplier,
            commission_pips_round_trip=self.commission_pips_round_trip,
            swap_pips_per_day=self.swap_pips_per_day,
        )


@dataclass(frozen=True, slots=True)
class TradeIntent:
    trade_id: str
    symbol: str
    direction: str
    signal_at: datetime
    entry_low: float
    entry_high: float
    stop_loss: float
    take_profit: float
    pip_size: float
    setup: str
    regime: str
    entry_expiry_bars: int = 12
    maximum_hold_bars: int = 72

    def __post_init__(self) -> None:
        if not self.trade_id.strip():
            raise DataContractError("trade_id is required")
        symbol = self.symbol.upper().strip()
        if len(symbol) != 6:
            raise DataContractError("trade symbol must be a six-character FX pair")
        object.__setattr__(self, "symbol", symbol)
        direction = self.direction.upper().strip()
        if direction not in {"LONG", "SHORT"}:
            raise DataContractError("trade direction must be LONG or SHORT")
        object.__setattr__(self, "direction", direction)
        object.__setattr__(self, "signal_at", ensure_utc(self.signal_at))
        for name in ("entry_low", "entry_high", "stop_loss", "take_profit", "pip_size"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isfinite(float(value)) or value <= 0:
                raise DataContractError(f"{name} must be positive finite")
        if self.entry_low >= self.entry_high:
            raise DataContractError("entry zone is invalid")
        if direction == "LONG":
            if not self.stop_loss < self.entry_low < self.entry_high < self.take_profit:
                raise DataContractError("LONG trade geometry is invalid")
        else:
            if not self.take_profit < self.entry_low < self.entry_high < self.stop_loss:
                raise DataContractError("SHORT trade geometry is invalid")
        if isinstance(self.entry_expiry_bars, bool) or self.entry_expiry_bars <= 0:
            raise DataContractError("entry_expiry_bars must be positive integer")
        if isinstance(self.maximum_hold_bars, bool) or self.maximum_hold_bars <= 0:
            raise DataContractError("maximum_hold_bars must be positive integer")
        if not isinstance(self.entry_expiry_bars, int) or not isinstance(self.maximum_hold_bars, int):
            raise DataContractError("bar limits must be integers")
        if not self.setup.strip() or not self.regime.strip():
            raise DataContractError("setup and regime are required")


@dataclass(frozen=True, slots=True)
class BacktestTrade:
    intent: TradeIntent
    outcome: TradeOutcome
    entry_at: datetime | None
    exit_at: datetime | None
    entry_price: float | None
    exit_price: float | None
    gross_r: float | None
    net_r: float | None
    cost_r: float | None
    bars_held: int
    ambiguous_bar: bool
    reason: str


@dataclass(frozen=True, slots=True)
class BacktestResult:
    trades: tuple[BacktestTrade, ...]

    @property
    def completed(self) -> tuple[BacktestTrade, ...]:
        return tuple(
            x for x in self.trades
            if x.outcome in {TradeOutcome.WIN, TradeOutcome.LOSS, TradeOutcome.BREAKEVEN}
        )


class BacktestEngine:
    """Point-in-time deterministic evaluator.

    Signal bars are never inspected for fills/outcomes. Evaluation starts on the
    first strictly later bar. If stop and target are touched on the same bar,
    STOP_FIRST is used to avoid optimistic intrabar ordering assumptions.
    """

    def __init__(
        self,
        *,
        cost_model: CostModel,
        ambiguous_bar_policy: str = "STOP_FIRST",
        minimum_stop_distance_pips: float = 2.0,
    ):
        if ambiguous_bar_policy != "STOP_FIRST":
            raise DataContractError("v0.9 requires conservative STOP_FIRST ambiguity policy")
        if minimum_stop_distance_pips <= 0:
            raise DataContractError("minimum_stop_distance_pips must be positive")
        self.cost_model = cost_model
        self.ambiguous_bar_policy = ambiguous_bar_policy
        self.minimum_stop_distance_pips = float(minimum_stop_distance_pips)

    @staticmethod
    def _validate_bars(intent: TradeIntent, bars: Sequence[Bar]) -> tuple[Bar, ...]:
        ordered = tuple(bars)
        if any(b.symbol != intent.symbol for b in ordered):
            raise DataContractError("backtest bars contain another symbol")
        if any(ordered[i].timestamp >= ordered[i + 1].timestamp for i in range(len(ordered) - 1)):
            raise DataContractError("backtest bars must be strictly chronological")
        return ordered

    @staticmethod
    def _entry_touch(intent: TradeIntent, bar: Bar) -> bool:
        return bar.low <= intent.entry_high and bar.high >= intent.entry_low

    def _fill_price(self, intent: TradeIntent, bar: Bar) -> float:
        # Conservative zone-edge fill: the edge further from the target.
        planned = intent.entry_high if intent.direction == "LONG" else intent.entry_low
        adverse = self.cost_model.slippage_pips * intent.pip_size
        return planned + adverse if intent.direction == "LONG" else planned - adverse

    def _cost_r(self, intent: TradeIntent, entry_price: float, bars_held: int, timeframe_seconds: int) -> float:
        risk_price = (
            entry_price - intent.stop_loss
            if intent.direction == "LONG"
            else intent.stop_loss - entry_price
        )
        risk_pips = risk_price / intent.pip_size
        if risk_pips < self.minimum_stop_distance_pips:
            raise DataContractError("stop distance below configured minimum")
        elapsed_days = bars_held * timeframe_seconds / 86400.0
        cost_pips = (
            self.cost_model.spread_pips
            + self.cost_model.slippage_pips
            + self.cost_model.commission_pips_round_trip
            + self.cost_model.swap_pips_per_day * elapsed_days
        )
        return cost_pips / risk_pips

    def evaluate(
        self,
        intent: TradeIntent,
        bars: Sequence[Bar],
        *,
        timeframe_seconds: int,
    ) -> BacktestTrade:
        if timeframe_seconds <= 0:
            raise DataContractError("timeframe_seconds must be positive")
        ordered = self._validate_bars(intent, bars)
        future = [b for b in ordered if b.timestamp > intent.signal_at]
        if not future:
            return BacktestTrade(
                intent, TradeOutcome.OPEN, None, None, None, None, None, None, None, 0, False,
                "NO_FUTURE_BARS",
            )

        entry_bar_index: int | None = None
        entry_price: float | None = None
        for i, bar in enumerate(future[: intent.entry_expiry_bars]):
            if self._entry_touch(intent, bar):
                entry_bar_index = i
                entry_price = self._fill_price(intent, bar)
                break
        if entry_bar_index is None or entry_price is None:
            return BacktestTrade(
                intent, TradeOutcome.MISSED, None, None, None, None, None, None, None, 0, False,
                "ENTRY_NOT_TOUCHED_BEFORE_EXPIRY",
            )

        entry_bar = future[entry_bar_index]
        risk_price = (
            entry_price - intent.stop_loss
            if intent.direction == "LONG"
            else intent.stop_loss - entry_price
        )
        if risk_price <= 0:
            raise DataContractError("adverse slippage invalidated stop geometry")

        evaluation = future[entry_bar_index:]
        held_limit = min(len(evaluation), intent.maximum_hold_bars + 1)
        for held_index, bar in enumerate(evaluation[:held_limit]):
            if intent.direction == "LONG":
                stop_hit = bar.low <= intent.stop_loss
                target_hit = bar.high >= intent.take_profit
            else:
                stop_hit = bar.high >= intent.stop_loss
                target_hit = bar.low <= intent.take_profit

            ambiguous = stop_hit and target_hit
            if stop_hit:
                exit_price = intent.stop_loss
                gross_r = -1.0
                bars_held = held_index
                cost_r = self._cost_r(intent, entry_price, bars_held, timeframe_seconds)
                return BacktestTrade(
                    intent,
                    TradeOutcome.LOSS,
                    entry_bar.timestamp,
                    bar.timestamp,
                    entry_price,
                    exit_price,
                    gross_r,
                    gross_r - cost_r,
                    cost_r,
                    bars_held,
                    ambiguous,
                    "STOP_FIRST_AMBIGUOUS" if ambiguous else "STOP_HIT",
                )
            if target_hit:
                exit_price = intent.take_profit
                reward_price = (
                    exit_price - entry_price
                    if intent.direction == "LONG"
                    else entry_price - exit_price
                )
                gross_r = reward_price / risk_price
                bars_held = held_index
                cost_r = self._cost_r(intent, entry_price, bars_held, timeframe_seconds)
                net_r = gross_r - cost_r
                outcome = TradeOutcome.WIN if net_r > 0 else TradeOutcome.BREAKEVEN
                return BacktestTrade(
                    intent,
                    outcome,
                    entry_bar.timestamp,
                    bar.timestamp,
                    entry_price,
                    exit_price,
                    gross_r,
                    net_r,
                    cost_r,
                    bars_held,
                    False,
                    "TARGET_HIT",
                )

        last = evaluation[held_limit - 1]
        if intent.direction == "LONG":
            exit_price = last.close
            gross_r = (exit_price - entry_price) / risk_price
        else:
            exit_price = last.close
            gross_r = (entry_price - exit_price) / risk_price
        bars_held = max(0, held_limit - 1)
        cost_r = self._cost_r(intent, entry_price, bars_held, timeframe_seconds)
        net_r = gross_r - cost_r
        outcome = (
            TradeOutcome.WIN if net_r > 0
            else TradeOutcome.LOSS if net_r < 0
            else TradeOutcome.BREAKEVEN
        )
        return BacktestTrade(
            intent,
            outcome,
            entry_bar.timestamp,
            last.timestamp,
            entry_price,
            exit_price,
            gross_r,
            net_r,
            cost_r,
            bars_held,
            False,
            "MAX_HOLD_EXIT",
        )

    def run(
        self,
        intents: Sequence[TradeIntent],
        bars_by_symbol: Mapping[str, Sequence[Bar]],
        *,
        timeframe_seconds: int,
    ) -> BacktestResult:
        seen: set[str] = set()
        trades: list[BacktestTrade] = []
        for intent in sorted(intents, key=lambda x: (x.signal_at, x.symbol, x.trade_id)):
            if intent.trade_id in seen:
                raise DataContractError(f"duplicate trade_id: {intent.trade_id}")
            seen.add(intent.trade_id)
            bars = bars_by_symbol.get(intent.symbol)
            if bars is None:
                trades.append(
                    BacktestTrade(
                        intent,
                        TradeOutcome.MISSED,
                        None,
                        None,
                        None,
                        None,
                        None,
                        None,
                        None,
                        0,
                        False,
                        "MISSING_SYMBOL_HISTORY",
                    )
                )
                continue
            trades.append(self.evaluate(intent, bars, timeframe_seconds=timeframe_seconds))
        return BacktestResult(tuple(trades))

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, Mapping, Sequence

from ..exceptions import DataContractError
from ..models import Bar, ensure_utc
from .backtest import TradeIntent


@dataclass(frozen=True, slots=True)
class PointInTimeBarView:
    as_of: datetime
    bars_by_symbol: Mapping[str, Mapping[str, tuple[Bar, ...]]]

    def __post_init__(self) -> None:
        object.__setattr__(self, "as_of", ensure_utc(self.as_of))

    def bars(self, symbol: str, timeframe: str) -> tuple[Bar, ...]:
        return tuple(
            self.bars_by_symbol.get(symbol.upper(), {}).get(timeframe.upper(), ())
        )


@dataclass(frozen=True, slots=True)
class ReplayResult:
    intents: tuple[TradeIntent, ...]
    timestamps_processed: int


class PointInTimeReplay:
    """Expose only bars that were closed at each replay timestamp.

    The callback receives a truncated immutable view, not the full historical
    store. Signals emitted by the callback must use the replay timestamp and a
    feature cutoff no later than that timestamp.
    """

    def __init__(
        self,
        bars_by_symbol: Mapping[str, Mapping[str, Sequence[Bar]]],
        *,
        timeframe_seconds: Mapping[str, int],
    ):
        self._bars_by_symbol = {
            str(symbol).upper(): {
                str(tf).upper(): tuple(bars)
                for tf, bars in tf_map.items()
            }
            for symbol, tf_map in bars_by_symbol.items()
        }
        self._timeframe_seconds = {
            str(tf).upper(): int(seconds)
            for tf, seconds in timeframe_seconds.items()
        }
        if not self._timeframe_seconds or any(x <= 0 for x in self._timeframe_seconds.values()):
            raise DataContractError("replay timeframe_seconds must be positive")

        for symbol, tf_map in self._bars_by_symbol.items():
            for tf, bars in tf_map.items():
                if tf not in self._timeframe_seconds:
                    raise DataContractError(f"replay timeframe missing seconds contract: {tf}")
                if any(bar.symbol != symbol or bar.timeframe != tf for bar in bars):
                    raise DataContractError("replay bars violate symbol/timeframe contract")
                if any(bars[i].timestamp >= bars[i + 1].timestamp for i in range(len(bars) - 1)):
                    raise DataContractError("replay bars must be strictly chronological")

    def view(self, as_of: datetime) -> PointInTimeBarView:
        cutoff = ensure_utc(as_of)
        output: dict[str, dict[str, tuple[Bar, ...]]] = {}
        for symbol, tf_map in self._bars_by_symbol.items():
            output[symbol] = {}
            for tf, bars in tf_map.items():
                seconds = self._timeframe_seconds[tf]
                closed = tuple(
                    bar
                    for bar in bars
                    if bar.timestamp + timedelta(seconds=seconds) <= cutoff
                )
                output[symbol][tf] = closed
        return PointInTimeBarView(cutoff, output)

    def run(
        self,
        timestamps: Sequence[datetime],
        signal_factory: Callable[[PointInTimeBarView], Sequence[TradeIntent]],
    ) -> ReplayResult:
        ordered = [ensure_utc(x) for x in timestamps]
        if any(ordered[i] >= ordered[i + 1] for i in range(len(ordered) - 1)):
            raise DataContractError("replay timestamps must be strictly chronological")

        emitted: list[TradeIntent] = []
        seen: set[str] = set()
        for as_of in ordered:
            view = self.view(as_of)
            intents = tuple(signal_factory(view))
            for intent in intents:
                if intent.signal_at != as_of:
                    raise DataContractError("replay intent signal_at must equal replay timestamp")
                if intent.feature_cutoff_at is None or intent.feature_cutoff_at > as_of:
                    raise DataContractError("replay intent feature cutoff violates point-in-time contract")
                if intent.trade_id in seen:
                    raise DataContractError(f"duplicate replay trade_id: {intent.trade_id}")
                seen.add(intent.trade_id)
                emitted.append(intent)
        return ReplayResult(tuple(emitted), len(ordered))

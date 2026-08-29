from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from math import isfinite

from .exceptions import DataContractError


UTC = timezone.utc


class SignalState(StrEnum):
    NO_TRADE = "NO_TRADE"
    WATCH = "WATCH"
    SETUP_FORMING = "SETUP_FORMING"
    ARMED = "ARMED"
    EXECUTION_READY = "EXECUTION_READY"
    MISSED = "MISSED"
    INVALIDATED = "INVALIDATED"
    COOLDOWN = "COOLDOWN"


class Readiness(StrEnum):
    RESEARCH_ONLY = "RESEARCH_ONLY"
    PAPER_ONLY = "PAPER_ONLY"
    DEMO_ONLY = "DEMO_ONLY"
    REAL_MONEY_CANDIDATE = "REAL_MONEY_CANDIDATE"


def ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise DataContractError("timestamp must be timezone-aware")
    return dt.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class Tick:
    symbol: str
    timestamp: datetime
    bid: float
    ask: float
    flags: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", self.symbol.upper())
        object.__setattr__(self, "timestamp", ensure_utc(self.timestamp))
        if not (isfinite(self.bid) and isfinite(self.ask)):
            raise DataContractError("bid/ask must be finite")
        if self.bid <= 0 or self.ask <= 0:
            raise DataContractError("bid/ask must be positive")
        if self.ask < self.bid:
            raise DataContractError("ask must be >= bid")

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2.0

    @property
    def spread(self) -> float:
        return self.ask - self.bid


@dataclass(frozen=True, slots=True)
class Bar:
    symbol: str
    timeframe: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    tick_count: int
    spread_avg: float
    spread_max: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", self.symbol.upper())
        object.__setattr__(self, "timeframe", self.timeframe.upper())
        object.__setattr__(self, "timestamp", ensure_utc(self.timestamp))
        values = (self.open, self.high, self.low, self.close, self.spread_avg, self.spread_max)
        if not all(isfinite(v) for v in values):
            raise DataContractError("bar values must be finite")
        if self.low > min(self.open, self.close) or self.high < max(self.open, self.close):
            raise DataContractError("OHLC is internally inconsistent")
        if self.high < self.low:
            raise DataContractError("high must be >= low")
        if self.tick_count <= 0:
            raise DataContractError("tick_count must be positive")
        if self.spread_avg < 0 or self.spread_max < 0 or self.spread_max < self.spread_avg:
            raise DataContractError("spread statistics are invalid")

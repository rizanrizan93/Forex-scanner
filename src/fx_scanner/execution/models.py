from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from math import isfinite

from ..exceptions import DataContractError
from ..models import ensure_utc


class ExecutionMode(StrEnum):
    DISABLED = "DISABLED"
    SIMULATION = "SIMULATION"
    CONFIRM_TO_TRADE = "CONFIRM_TO_TRADE"
    AUTO = "AUTO"


class OrderSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(StrEnum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"


@dataclass(frozen=True, slots=True)
class OrderIntent:
    signal_id: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    created_at: datetime
    volume: float
    entry_price: float | None
    stop_loss: float
    take_profit: float
    risk_pct: float
    comment: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", self.symbol.upper())
        object.__setattr__(self, "created_at", ensure_utc(self.created_at))
        if not self.signal_id.strip():
            raise DataContractError("signal_id is required")
        if self.volume <= 0 or not isfinite(self.volume):
            raise DataContractError("volume must be positive and finite")
        if self.stop_loss <= 0 or self.take_profit <= 0:
            raise DataContractError("SL/TP must be positive")
        if self.entry_price is not None and self.entry_price <= 0:
            raise DataContractError("entry_price must be positive when supplied")
        if not 0 < self.risk_pct <= 1:
            raise DataContractError("risk_pct must be in (0, 1]")
        ref = self.entry_price
        if ref is not None:
            if self.side == OrderSide.BUY and not (self.stop_loss < ref < self.take_profit):
                raise DataContractError("BUY requires stop_loss < entry_price < take_profit")
            if self.side == OrderSide.SELL and not (self.take_profit < ref < self.stop_loss):
                raise DataContractError("SELL requires take_profit < entry_price < stop_loss")


@dataclass(frozen=True, slots=True)
class OrderReceipt:
    signal_id: str
    symbol: str
    mode: ExecutionMode
    accepted: bool
    broker_order_id: str | None
    message: str
    executed_volume: float | None = None
    executed_price: float | None = None

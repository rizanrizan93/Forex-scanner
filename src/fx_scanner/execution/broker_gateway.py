from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

from .models import OrderIntent


class BrokerBackend(StrEnum):
    CTRADER = "CTRADER"
    MT5 = "MT5"


@dataclass(frozen=True, slots=True)
class BrokerAccountSnapshot:
    backend: BrokerBackend
    account_id: str
    balance: float
    equity: float
    margin_free: float | None
    trade_allowed: bool
    currency: str | None = None


@dataclass(frozen=True, slots=True)
class BrokerPreflight:
    backend: BrokerBackend
    accepted: bool
    code: str
    message: str
    request: Any


@dataclass(frozen=True, slots=True)
class BrokerOrderResult:
    backend: BrokerBackend
    accepted: bool
    code: str
    message: str
    broker_order_id: str | None = None
    executed_volume: float | None = None
    executed_price: float | None = None


class BrokerExecutionGateway(Protocol):
    backend: BrokerBackend

    def account_snapshot(self) -> BrokerAccountSnapshot: ...

    def preflight(self, intent: OrderIntent, order_config: dict[str, Any]) -> BrokerPreflight: ...

    def submit(self, preflight: BrokerPreflight) -> BrokerOrderResult: ...

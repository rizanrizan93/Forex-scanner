from __future__ import annotations

from datetime import datetime

from .base import MarketDataCollector
from ..models import Tick, ensure_utc


class MockCollector(MarketDataCollector):
    def __init__(self, ticks: list[Tick]):
        self._ticks = list(ticks)

    def fetch_ticks(self, symbol: str, start: datetime, end: datetime) -> list[Tick]:
        start_utc, end_utc = ensure_utc(start), ensure_utc(end)
        symbol = symbol.upper()
        return [
            t for t in self._ticks
            if t.symbol == symbol and start_utc <= t.timestamp <= end_utc
        ]

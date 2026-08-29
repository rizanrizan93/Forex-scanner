from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from ..models import Tick


class MarketDataCollector(ABC):
    @abstractmethod
    def fetch_ticks(self, symbol: str, start: datetime, end: datetime) -> list[Tick]:
        raise NotImplementedError

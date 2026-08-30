from __future__ import annotations

from threading import RLock
from typing import Any, Iterable


class CTraderResearchFeed:
    """Read-only facade over a connected cTrader Open API session.

    This object deliberately exposes no order-construction or order-submission
    methods. On reconnect it restores the symbol catalogue and spot
    subscriptions before serving quotes.
    """

    __slots__ = ("_session", "_symbols", "_lock")

    def __init__(self, session, symbols: Iterable[str]):
        self._session = session
        self._symbols = tuple(str(x).upper() for x in symbols)
        self._lock = RLock()

    def ensure_connected(self) -> None:
        with self._lock:
            was_healthy = bool(self._session.health())
            self._session.ensure_connected()
            if not was_healthy:
                self._session.load_symbols(list(self._symbols))
                self._session.subscribe_spots(list(self._symbols))

    def health(self) -> bool:
        return bool(self._session.health())

    def quote(self, symbol: str):
        self.ensure_connected()
        return self._session.quote(symbol)

    def symbol_info(self, symbol: str) -> Any:
        self.ensure_connected()
        return self._session.symbol_info(symbol)

    def close(self) -> None:
        self._session.close()

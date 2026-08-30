from __future__ import annotations

from typing import Any


class CTraderResearchFeed:
    """Read-only facade over a connected cTrader Open API session.

    This object deliberately exposes no order-construction or order-submission
    methods. Strategy/reconciliation code receives this facade rather than an
    execution gateway.
    """

    __slots__ = ("_session",)

    def __init__(self, session):
        self._session = session

    def ensure_connected(self) -> None:
        self._session.ensure_connected()

    def health(self) -> bool:
        return bool(self._session.health())

    def quote(self, symbol: str):
        return self._session.quote(symbol)

    def symbol_info(self, symbol: str) -> Any:
        return self._session.symbol_info(symbol)

    def close(self) -> None:
        self._session.close()

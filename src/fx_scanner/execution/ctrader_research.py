from __future__ import annotations

from datetime import datetime
from threading import RLock
from typing import Any, Iterable

from ..exceptions import CollectorUnavailable
from .ctrader_market_hours import CTraderMarketStatus, evaluate_ctrader_market_status


class CTraderResearchFeed:
    """Read-only facade over a connected cTrader Open API session.

    This object deliberately exposes no order-construction or order-submission
    methods. On reconnect it restores the symbol catalogue and spot
    subscriptions before serving quotes. Broker symbol trading hours are checked
    before quote/history use so a closed market cannot masquerade as stale data.
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

    def market_status(self, symbol: str, *, at: datetime | None = None) -> CTraderMarketStatus:
        self.ensure_connected()
        return evaluate_ctrader_market_status(self._session.symbol_info(symbol), at=at)

    def _require_open_market(self, symbol: str, *, at: datetime | None = None) -> CTraderMarketStatus:
        status = self.market_status(symbol, at=at)
        if not status.open_for_new_positions:
            raise CollectorUnavailable(
                f"CTRADER_MARKET_CLOSED:{str(symbol).upper()}:{status.reason}"
            )
        return status

    def quote(self, symbol: str):
        self._require_open_market(symbol)
        return self._session.quote(symbol)

    def refresh_quote_snapshot(self, symbol: str) -> None:
        with self._lock:
            self._require_open_market(symbol)
            self._session.refresh_spot_snapshot(symbol)

    def symbol_info(self, symbol: str) -> Any:
        self.ensure_connected()
        return self._session.symbol_info(symbol)

    def heartbeat(self) -> None:
        with self._lock:
            self._session.heartbeat()

    def historical_bars(
        self, symbol: str, timeframe: str, *, from_time: datetime,
        to_time: datetime, count: int,
    ):
        with self._lock:
            self._require_open_market(symbol, at=to_time)
            quote = self._session.quote(symbol)
            spread = max(0.0, float(quote.ask) - float(quote.bid))
            return self._session.historical_bars(
                symbol, timeframe, from_time=from_time, to_time=to_time,
                count=count, spread_proxy=spread,
            )

    def close(self) -> None:
        self._session.close()

from __future__ import annotations

from datetime import datetime, timezone
from importlib import import_module
from typing import Any

from .base import MarketDataCollector
from ..exceptions import CollectorUnavailable, MissingOptionalDependency
from ..models import Tick, ensure_utc


UTC = timezone.utc


class MT5Collector(MarketDataCollector):
    """Read-only MetaTrader 5 market-data adapter.

    Intentionally contains no order placement API.
    """

    def __init__(self, terminal_path: str | None = None):
        try:
            self.mt5: Any = import_module("MetaTrader5")
        except ModuleNotFoundError as exc:
            raise MissingOptionalDependency(
                "MetaTrader5 package is unavailable. Install it on the Windows collector host."
            ) from exc
        self.terminal_path = terminal_path
        self._initialized = False

    def connect(self) -> None:
        ok = self.mt5.initialize(path=self.terminal_path) if self.terminal_path else self.mt5.initialize()
        if not ok:
            raise CollectorUnavailable(f"MT5 initialize failed: {self.mt5.last_error()}")
        self._initialized = True

    def close(self) -> None:
        if self._initialized:
            self.mt5.shutdown()
            self._initialized = False

    def __enter__(self) -> "MT5Collector":
        self.connect()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def fetch_ticks(self, symbol: str, start: datetime, end: datetime) -> list[Tick]:
        if not self._initialized:
            raise CollectorUnavailable("MT5Collector must be connected before fetch_ticks")
        symbol = symbol.upper()
        if not self.mt5.symbol_select(symbol, True):
            raise CollectorUnavailable(f"MT5 symbol_select failed for {symbol}: {self.mt5.last_error()}")

        start_utc, end_utc = ensure_utc(start), ensure_utc(end)
        rows = self.mt5.copy_ticks_range(symbol, start_utc, end_utc, self.mt5.COPY_TICKS_ALL)
        if rows is None:
            raise CollectorUnavailable(f"MT5 copy_ticks_range failed: {self.mt5.last_error()}")

        result: list[Tick] = []
        names = set(rows.dtype.names or ())
        for row in rows:
            if "time_msc" in names:
                ts = datetime.fromtimestamp(float(row["time_msc"]) / 1000.0, tz=UTC)
            else:
                ts = datetime.fromtimestamp(float(row["time"]), tz=UTC)
            bid, ask = float(row["bid"]), float(row["ask"])
            # Some non-FX instruments can emit zero sides; FX v0.1 fails closed.
            if bid <= 0 or ask <= 0:
                continue
            result.append(
                Tick(
                    symbol=symbol,
                    timestamp=ts,
                    bid=bid,
                    ask=ask,
                    flags=int(row["flags"]) if "flags" in names else 0,
                )
            )
        return result

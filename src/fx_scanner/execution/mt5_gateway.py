from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from importlib import import_module
from threading import RLock
from typing import Any

from ..exceptions import CollectorUnavailable, MissingOptionalDependency
from .broker_gateway import (
    BrokerAccountSnapshot,
    BrokerBackend,
    BrokerOrderResult,
    BrokerPreflight,
)
from .models import OrderIntent, OrderSide, OrderType
from .position_sizer import SymbolTradeSpec

UTC = timezone.utc


@dataclass(frozen=True, slots=True)
class MT5Quote:
    symbol: str
    bid: float
    ask: float
    timestamp: datetime


class MT5ExecutionGateway:
    """Serialized MT5 execution adapter for the explicitly selected venue."""

    backend = BrokerBackend.MT5

    def __init__(
        self,
        terminal_path: str | None = None,
        initialize_timeout_ms: int = 10_000,
        *,
        login: int | None = None,
        server: str | None = None,
        password: str | None = None,
        max_quote_age_seconds: float = 1.0,
    ):
        try:
            self.mt5: Any = import_module("MetaTrader5")
        except ModuleNotFoundError as exc:
            raise MissingOptionalDependency("MetaTrader5 package is unavailable on this host") from exc
        self.terminal_path = terminal_path
        self.initialize_timeout_ms = int(initialize_timeout_ms)
        self.login = int(login) if login is not None else None
        self.server = server
        self.password = password
        self.max_quote_age_seconds = float(max_quote_age_seconds)
        if self.initialize_timeout_ms <= 0:
            raise ValueError("initialize_timeout_ms must be positive")
        if self.max_quote_age_seconds <= 0:
            raise ValueError("max_quote_age_seconds must be positive")
        self.connected = False
        self._io_lock = RLock()

    def connect(self) -> None:
        with self._io_lock:
            if self.connected and self.terminal_health():
                return
            if self.connected:
                try:
                    self.mt5.shutdown()
                finally:
                    self.connected = False

            kwargs: dict[str, Any] = {"timeout": self.initialize_timeout_ms}
            if self.terminal_path:
                kwargs["path"] = self.terminal_path
            if self.login is not None:
                kwargs["login"] = self.login
            if self.server:
                kwargs["server"] = self.server
            if self.password:
                kwargs["password"] = self.password
            ok = self.mt5.initialize(**kwargs)
            if not ok:
                raise CollectorUnavailable(f"MT5 initialize failed: {self.mt5.last_error()}")
            self.connected = True

    def close(self) -> None:
        with self._io_lock:
            if self.connected:
                self.mt5.shutdown()
            self.connected = False

    def terminal_health(self) -> bool:
        with self._io_lock:
            if not self.connected:
                return False
            info = self.mt5.terminal_info()
            return bool(info is not None and getattr(info, "connected", True))

    def account_snapshot(self) -> BrokerAccountSnapshot:
        with self._io_lock:
            if not self.connected:
                raise CollectorUnavailable("MT5 gateway is not connected")
            info = self.mt5.account_info()
            if info is None:
                raise CollectorUnavailable(f"MT5 account_info failed: {self.mt5.last_error()}")
            return BrokerAccountSnapshot(
                backend=self.backend,
                account_id=str(int(info.login)),
                balance=float(info.balance),
                equity=float(info.equity),
                margin_free=float(info.margin_free),
                trade_allowed=bool(info.trade_allowed),
                currency=str(getattr(info, "currency", "") or "") or None,
            )

    def symbol_available(self, symbol: str) -> bool:
        with self._io_lock:
            if not self.connected:
                raise CollectorUnavailable("MT5 gateway is not connected")
            return self.mt5.symbol_info(symbol) is not None

    def ensure_symbol(self, symbol: str) -> None:
        with self._io_lock:
            if not self.connected:
                raise CollectorUnavailable("MT5 gateway is not connected")
            info = self.mt5.symbol_info(symbol)
            if info is None:
                raise CollectorUnavailable(f"symbol_info unavailable for {symbol}")
            if not bool(getattr(info, "visible", True)):
                if not self.mt5.symbol_select(symbol, True):
                    raise CollectorUnavailable(f"symbol_select failed for {symbol}: {self.mt5.last_error()}")

    def symbol_contract_size(self, symbol: str) -> float:
        with self._io_lock:
            info = self.mt5.symbol_info(symbol)
            if info is None:
                raise CollectorUnavailable(f"symbol_info unavailable for {symbol}")
            size = float(getattr(info, "trade_contract_size", 0.0) or 0.0)
            if size <= 0:
                raise CollectorUnavailable(f"contract size unavailable for {symbol}")
            return size

    def symbol_trade_spec(self, symbol: str) -> SymbolTradeSpec:
        with self._io_lock:
            if not self.connected:
                raise CollectorUnavailable("MT5 gateway is not connected")
            info = self.mt5.symbol_info(symbol)
            if info is None:
                raise CollectorUnavailable(f"symbol_info unavailable for {symbol}")
            return SymbolTradeSpec(
                tick_size=float(info.trade_tick_size),
                tick_value_loss=float(info.trade_tick_value_loss or info.trade_tick_value),
                volume_min=float(info.volume_min),
                volume_max=float(info.volume_max),
                volume_step=float(info.volume_step),
                contract_size=float(getattr(info, "trade_contract_size", 0.0) or 0.0) or None,
            )

    @staticmethod
    def _tick_timestamp(tick) -> datetime:
        raw_ms = int(getattr(tick, "time_msc", 0) or 0)
        if raw_ms > 0:
            return datetime.fromtimestamp(raw_ms / 1000.0, tz=UTC)
        raw_s = int(getattr(tick, "time", 0) or 0)
        if raw_s > 0:
            return datetime.fromtimestamp(raw_s, tz=UTC)
        raise CollectorUnavailable("MT5 tick timestamp unavailable")

    def quote(self, symbol: str) -> MT5Quote:
        with self._io_lock:
            if not self.connected:
                raise CollectorUnavailable("MT5 gateway is not connected")
            self.ensure_symbol(symbol)
            tick = self.mt5.symbol_info_tick(symbol)
            if tick is None:
                raise CollectorUnavailable(f"symbol_info_tick unavailable for {symbol}")
            bid = float(tick.bid)
            ask = float(tick.ask)
            if bid <= 0 or ask <= 0 or ask < bid:
                raise CollectorUnavailable(f"invalid MT5 quote for {symbol}")
            return MT5Quote(symbol, bid, ask, self._tick_timestamp(tick))

    def current_price(self, symbol: str, side: OrderSide) -> float:
        quote = self.quote(symbol)
        age = (datetime.now(tz=UTC) - quote.timestamp).total_seconds()
        if age < -1.0 or age > self.max_quote_age_seconds:
            raise CollectorUnavailable(f"MT5 stale quote for {symbol}: {age:.3f}s")
        return float(quote.ask if side == OrderSide.BUY else quote.bid)

    def _request(self, intent: OrderIntent, *, deviation: int, magic: int, comment: str) -> dict[str, Any]:
        with self._io_lock:
            if not self.connected:
                raise CollectorUnavailable("MT5 gateway is not connected")
            mt5 = self.mt5
            symbol = intent.broker_symbol or intent.symbol
            if intent.side == OrderSide.BUY:
                side_type, limit_type, stop_type = mt5.ORDER_TYPE_BUY, mt5.ORDER_TYPE_BUY_LIMIT, mt5.ORDER_TYPE_BUY_STOP
            else:
                side_type, limit_type, stop_type = mt5.ORDER_TYPE_SELL, mt5.ORDER_TYPE_SELL_LIMIT, mt5.ORDER_TYPE_SELL_STOP
            order_type = {OrderType.MARKET: side_type, OrderType.LIMIT: limit_type, OrderType.STOP: stop_type}[intent.order_type]
            price = self.current_price(symbol, intent.side) if intent.order_type == OrderType.MARKET else intent.entry_price
            if price is None:
                raise ValueError("pending order requires entry_price")
            action = mt5.TRADE_ACTION_DEAL if intent.order_type == OrderType.MARKET else mt5.TRADE_ACTION_PENDING
            symbol_info = self.mt5.symbol_info(symbol)
            if symbol_info is None:
                raise CollectorUnavailable(f"symbol_info unavailable for {symbol}")
            return {
                "action": action,
                "symbol": symbol,
                "volume": float(intent.volume),
                "type": order_type,
                "price": float(price),
                "sl": float(intent.stop_loss),
                "tp": float(intent.take_profit),
                "deviation": int(deviation),
                "magic": int(magic),
                "comment": comment[:31],
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": int(getattr(symbol_info, "filling_mode", mt5.ORDER_FILLING_IOC)),
            }

    def order_check(self, request: dict[str, Any]):
        with self._io_lock:
            result = self.mt5.order_check(request)
            if result is None:
                raise CollectorUnavailable(f"MT5 order_check failed: {self.mt5.last_error()}")
            return result

    def order_send(self, request: dict[str, Any]):
        with self._io_lock:
            result = self.mt5.order_send(request)
            if result is None:
                raise CollectorUnavailable(f"MT5 order_send failed: {self.mt5.last_error()}")
            return result

    def preflight(self, intent: OrderIntent, order_config: dict[str, Any]) -> BrokerPreflight:
        prefix = str(order_config.get("comment_prefix", "FXIS"))
        comment = f"{prefix}:{intent.signal_id}"[:31]
        try:
            request = self._request(
                intent,
                deviation=int(order_config.get("default_deviation_points", 20)),
                magic=int(order_config.get("magic_number", 26083001)),
                comment=comment,
            )
            check = self.order_check(request)
            retcode = int(getattr(check, "retcode", -1))
            return BrokerPreflight(self.backend, retcode == 0, str(retcode), "order_check", request)
        except Exception as exc:
            return BrokerPreflight(self.backend, False, "MT5_PREFLIGHT_ERROR", str(exc), None)

    def submit(self, preflight: BrokerPreflight) -> BrokerOrderResult:
        if not preflight.accepted or preflight.request is None:
            return BrokerOrderResult(self.backend, False, preflight.code, preflight.message)
        result = self.order_send(preflight.request)
        done_codes = {
            int(getattr(self.mt5, "TRADE_RETCODE_DONE", -99999)),
            int(getattr(self.mt5, "TRADE_RETCODE_PLACED", -99998)),
            int(getattr(self.mt5, "TRADE_RETCODE_DONE_PARTIAL", -99997)),
        }
        retcode = int(getattr(result, "retcode", -1))
        return BrokerOrderResult(
            backend=self.backend,
            accepted=retcode in done_codes,
            code=str(retcode),
            message="order_send",
            broker_order_id=str(getattr(result, "order", "")) or None,
            executed_volume=float(getattr(result, "volume", 0.0)) or None,
            executed_price=float(getattr(result, "price", 0.0)) or None,
        )

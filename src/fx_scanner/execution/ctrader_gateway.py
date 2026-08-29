from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from ..exceptions import CollectorUnavailable
from .broker_gateway import (
    BrokerAccountSnapshot,
    BrokerBackend,
    BrokerOrderResult,
    BrokerPreflight,
)
from .models import OrderIntent, OrderSide, OrderType

UTC = timezone.utc


@dataclass(frozen=True, slots=True)
class CTraderPreparedOrder:
    request: Any
    lot_size_cents: int
    executable_price: float
    expected_margin: float | None


def _money(value: int | float, digits: int | None) -> float:
    exponent = int(digits or 0)
    return float(value) / (10 ** exponent)


class CTraderExecutionGateway:
    """cTrader Open API execution backend."""

    backend = BrokerBackend.CTRADER

    def __init__(self, session, *, max_quote_age_seconds: float = 5.0):
        self.session = session
        self.max_quote_age_seconds = float(max_quote_age_seconds)
        if self.max_quote_age_seconds <= 0:
            raise ValueError("max_quote_age_seconds must be positive")

    def account_snapshot(self) -> BrokerAccountSnapshot:
        self.session.ensure_connected()
        trader = self.session.trader()
        balance = _money(trader.balance, getattr(trader, "moneyDigits", 0))
        pnl_res = self.session.unrealized_pnl()
        pnl_digits = int(getattr(pnl_res, "moneyDigits", 0))
        net_pnl = sum(_money(x.netUnrealizedPnL, pnl_digits) for x in pnl_res.positionUnrealizedPnL)
        equity = balance + net_pnl
        reconcile = self.session.reconcile()
        used_margin = 0.0
        for position in reconcile.position:
            raw = getattr(position, "usedMargin", 0)
            digits = getattr(position, "moneyDigits", 0)
            if raw:
                used_margin += _money(raw, digits)
        return BrokerAccountSnapshot(
            backend=self.backend,
            account_id=str(self.session.account_id),
            balance=balance,
            equity=equity,
            margin_free=equity - used_margin,
            trade_allowed=int(getattr(trader, "accessRights", 0)) == 0,
        )

    @staticmethod
    def _volume_cents(lots: float, symbol_info) -> int:
        lot_size_cents = int(getattr(symbol_info, "lotSize", 0))
        if lot_size_cents <= 0:
            raise CollectorUnavailable("cTrader symbol lotSize unavailable")
        volume = int(round(float(lots) * lot_size_cents))
        minimum = int(getattr(symbol_info, "minVolume", 0) or 0)
        maximum = int(getattr(symbol_info, "maxVolume", 0) or 0)
        step = int(getattr(symbol_info, "stepVolume", 0) or 0)
        if minimum and volume < minimum:
            raise CollectorUnavailable(f"cTrader volume below minimum: {volume} < {minimum}")
        if maximum and volume > maximum:
            raise CollectorUnavailable(f"cTrader volume above maximum: {volume} > {maximum}")
        if step and minimum and (volume - minimum) % step != 0:
            raise CollectorUnavailable("cTrader volume does not match broker stepVolume")
        if step and not minimum and volume % step != 0:
            raise CollectorUnavailable("cTrader volume does not match broker stepVolume")
        return volume

    def _quote(self, intent: OrderIntent):
        quote = self.session.quote(intent.symbol)
        age = (datetime.now(tz=UTC) - quote.timestamp).total_seconds()
        if age > self.max_quote_age_seconds:
            raise CollectorUnavailable(f"cTrader stale quote: {age:.3f}s")
        return quote, quote.ask if intent.side == OrderSide.BUY else quote.bid

    def _build_request(self, intent: OrderIntent, order_config: dict[str, Any]) -> CTraderPreparedOrder:
        symbol = self.session.symbol_info(intent.symbol)
        symbol_id = int(symbol.symbolId)
        volume_cents = self._volume_cents(intent.volume, symbol)
        _, executable_price = self._quote(intent)
        request = self.session.new_order_message()
        request.ctidTraderAccountId = int(self.session.account_id)
        request.symbolId = symbol_id
        request.volume = volume_cents
        request.tradeSide = 1 if intent.side == OrderSide.BUY else 2
        request.clientOrderId = intent.signal_id[:50]
        prefix = str(order_config.get("comment_prefix", "FXIS"))
        request.label = prefix[:100]
        request.comment = f"{prefix}:{intent.signal_id}"[:512]

        if intent.order_type == OrderType.MARKET:
            request.orderType = 1
            sl_distance = executable_price - intent.stop_loss if intent.side == OrderSide.BUY else intent.stop_loss - executable_price
            tp_distance = intent.take_profit - executable_price if intent.side == OrderSide.BUY else executable_price - intent.take_profit
            if sl_distance <= 0 or tp_distance <= 0:
                raise CollectorUnavailable("cTrader market SL/TP invalid relative to executable quote")
            request.relativeStopLoss = int(round(sl_distance * 100000.0))
            request.relativeTakeProfit = int(round(tp_distance * 100000.0))
        elif intent.order_type == OrderType.LIMIT:
            if intent.entry_price is None:
                raise CollectorUnavailable("cTrader LIMIT requires entry_price")
            request.orderType = 2
            request.limitPrice = float(intent.entry_price)
            request.stopLoss = float(intent.stop_loss)
            request.takeProfit = float(intent.take_profit)
        elif intent.order_type == OrderType.STOP:
            if intent.entry_price is None:
                raise CollectorUnavailable("cTrader STOP requires entry_price")
            request.orderType = 3
            request.stopPrice = float(intent.entry_price)
            request.stopLoss = float(intent.stop_loss)
            request.takeProfit = float(intent.take_profit)
        else:
            raise CollectorUnavailable(f"unsupported cTrader order type: {intent.order_type}")

        margin_res = self.session.expected_margin(symbol_id, volume_cents)
        if not getattr(margin_res, "margin", None):
            raise CollectorUnavailable("cTrader expected-margin preflight returned no margin")
        first = margin_res.margin[0]
        raw = first.buyMargin if intent.side == OrderSide.BUY else first.sellMargin
        return CTraderPreparedOrder(request, int(symbol.lotSize), executable_price, float(raw))

    def preflight(self, intent: OrderIntent, order_config: dict[str, Any]) -> BrokerPreflight:
        try:
            prepared = self._build_request(intent, order_config)
        except Exception as exc:
            return BrokerPreflight(self.backend, False, "LOCAL_VALIDATION", str(exc), None)
        return BrokerPreflight(self.backend, True, "EXPECTED_MARGIN_OK", "cTrader preflight passed", prepared)

    def submit(self, preflight: BrokerPreflight) -> BrokerOrderResult:
        if not preflight.accepted or not isinstance(preflight.request, CTraderPreparedOrder):
            return BrokerOrderResult(self.backend, False, "INVALID_PREFLIGHT", "invalid prepared order")
        prepared = preflight.request
        response = self.session.send_new_order(prepared.request, client_msg_id=f"ord-{prepared.request.clientOrderId}")
        execution_type = int(getattr(response, "executionType", -1))
        accepted = execution_type in {2, 3, 11}
        order = getattr(response, "order", None)
        order_id = str(getattr(order, "orderId", "")) or None if order is not None else None
        executed_cents = int(getattr(order, "executedVolume", 0) or 0) if order is not None else 0
        executed_lots = executed_cents / prepared.lot_size_cents if executed_cents else None
        price = float(getattr(order, "executionPrice", 0.0) or 0.0) if order is not None else 0.0
        return BrokerOrderResult(
            backend=self.backend,
            accepted=accepted,
            code=str(execution_type),
            message=str(getattr(response, "errorCode", "")) or "execution_event",
            broker_order_id=order_id,
            executed_volume=executed_lots,
            executed_price=price or None,
        )

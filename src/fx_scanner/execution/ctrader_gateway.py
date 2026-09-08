from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any
from time import monotonic, sleep

from ..exceptions import CollectorUnavailable
from .broker_gateway import (
    BrokerAccountSnapshot,
    BrokerBackend,
    BrokerOrderResult,
    BrokerPreflight,
)
from .ctrader_protection import CTraderPostFillProtectionManager, PostFillProtectionOutcome
from .models import OrderIntent, OrderSide, OrderType

UTC = timezone.utc


@dataclass(frozen=True, slots=True)
class CTraderPreparedOrder:
    request: Any
    lot_size_cents: int
    executable_price: float
    expected_margin: float | None
    account_id: int
    symbol_name: str
    symbol_info: Any
    symbol_id: int
    trade_side: int
    volume_cents: int
    planned_stop_loss: float
    planned_take_profit: float
    is_market: bool


def _money(value: int | float, digits: int | None) -> float:
    exponent = int(digits or 0)
    return float(value) / (10 ** exponent)


def _relative_protection_distance(distance: float, symbol_info) -> int:
    """Normalize a scanner price distance to cTrader's 1e-5 relative units.

    cTrader transmits relative SL/TP as integer 1/100000 price units, but the
    server still validates that the implied protection price respects the
    symbol's displayed price precision. Normalize the price distance to the
    broker-reported symbol digits before conversion. This changes only broker
    representation (at most half one symbol tick), not scanner trade geometry.
    """
    digits = int(getattr(symbol_info, "digits", -1))
    if digits < 0:
        raise CollectorUnavailable("cTrader symbol digits unavailable")
    protocol_digits = min(digits, 5)
    quantum = Decimal("1").scaleb(-protocol_digits)
    normalized = Decimal(str(float(distance))).quantize(quantum, rounding=ROUND_HALF_UP)
    relative = int(
        (normalized * Decimal("100000")).to_integral_value(rounding=ROUND_HALF_UP)
    )
    if relative <= 0:
        raise CollectorUnavailable("cTrader normalized relative SL/TP distance is zero")
    return relative


class CTraderExecutionGateway:
    """cTrader Open API execution backend."""

    backend = BrokerBackend.CTRADER

    def __init__(
        self,
        session,
        *,
        max_quote_age_seconds: float = 5.0,
        quote_wait_timeout_seconds: float = 5.0,
        quote_poll_seconds: float = 0.10,
        protection_reconcile_attempts: int = 3,
        protection_amend_attempts: int = 2,
        protection_poll_seconds: float = 0.15,
        protection_amend_timeout_seconds: float = 5.0,
    ):
        self.session = session
        self.max_quote_age_seconds = float(max_quote_age_seconds)
        self.quote_wait_timeout_seconds = float(quote_wait_timeout_seconds)
        self.quote_poll_seconds = float(quote_poll_seconds)
        if self.max_quote_age_seconds <= 0:
            raise ValueError("max_quote_age_seconds must be positive")
        if self.quote_wait_timeout_seconds < 0:
            raise ValueError("quote_wait_timeout_seconds cannot be negative")
        if not 0 < self.quote_poll_seconds <= 1.0:
            raise ValueError("quote_poll_seconds must be in (0,1]")
        self.protection_manager = CTraderPostFillProtectionManager(
            session,
            quote_provider=self.market_quote,
            reconcile_attempts=protection_reconcile_attempts,
            amend_attempts=protection_amend_attempts,
            poll_seconds=protection_poll_seconds,
            amend_timeout_seconds=protection_amend_timeout_seconds,
        )

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

    def market_quote(self, symbol: str):
        symbol = str(symbol).upper()
        deadline = monotonic() + self.quote_wait_timeout_seconds
        last_age = None
        while True:
            quote = self.session.quote(symbol)
            age = (datetime.now(tz=UTC) - quote.timestamp).total_seconds()
            last_age = age
            if -1.0 <= age <= self.max_quote_age_seconds:
                return quote
            if age < -1.0:
                raise CollectorUnavailable(f"cTrader quote timestamp is in the future: {age:.3f}s")
            if monotonic() >= deadline:
                raise CollectorUnavailable(
                    f"cTrader stale quote after bounded wait: {last_age:.3f}s"
                )
            sleep(self.quote_poll_seconds)

    def _quote(self, intent: OrderIntent):
        quote = self.market_quote(intent.symbol)
        return quote, quote.ask if intent.side == OrderSide.BUY else quote.bid

    def _build_request(self, intent: OrderIntent, order_config: dict[str, Any]) -> CTraderPreparedOrder:
        symbol = self.session.symbol_info(intent.symbol)
        symbol_id = int(symbol.symbolId)
        volume_cents = self._volume_cents(intent.volume, symbol)
        _, executable_price = self._quote(intent)
        request = self.session.new_order_message()
        account_id = int(self.session.account_id)
        trade_side = 1 if intent.side == OrderSide.BUY else 2
        request.ctidTraderAccountId = account_id
        request.symbolId = symbol_id
        request.volume = volume_cents
        request.tradeSide = trade_side
        request.clientOrderId = intent.signal_id[:50]
        prefix = str(order_config.get("comment_prefix", "FXIS"))
        request.label = prefix[:100]
        request.comment = f"{prefix}:{intent.signal_id}"[:512]

        is_market = intent.order_type == OrderType.MARKET
        if is_market:
            request.orderType = 1
            sl_distance = executable_price - intent.stop_loss if intent.side == OrderSide.BUY else intent.stop_loss - executable_price
            tp_distance = intent.take_profit - executable_price if intent.side == OrderSide.BUY else executable_price - intent.take_profit
            if sl_distance <= 0 or tp_distance <= 0:
                raise CollectorUnavailable("cTrader market SL/TP invalid relative to executable quote")
            request.relativeStopLoss = _relative_protection_distance(sl_distance, symbol)
            request.relativeTakeProfit = _relative_protection_distance(tp_distance, symbol)
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
        return CTraderPreparedOrder(
            request=request,
            lot_size_cents=int(symbol.lotSize),
            executable_price=executable_price,
            expected_margin=float(raw),
            account_id=account_id,
            symbol_name=str(intent.symbol).upper(),
            symbol_info=symbol,
            symbol_id=symbol_id,
            trade_side=trade_side,
            volume_cents=volume_cents,
            planned_stop_loss=float(intent.stop_loss),
            planned_take_profit=float(intent.take_profit),
            is_market=is_market,
        )

    def position_count(self) -> int:
        """Return broker-reported open position count for demo exposure guards."""
        self.session.ensure_connected()
        reconcile = self.session.reconcile()
        return len(tuple(getattr(reconcile, "position", ())))

    def executable_quote(self, intent: OrderIntent) -> tuple[float, float, float]:
        """Return bid, ask, and side-specific executable price after freshness validation."""
        quote, executable = self._quote(intent)
        return float(quote.bid), float(quote.ask), float(executable)

    def preflight(self, intent: OrderIntent, order_config: dict[str, Any]) -> BrokerPreflight:
        try:
            prepared = self._build_request(intent, order_config)
        except Exception as exc:
            return BrokerPreflight(self.backend, False, "LOCAL_VALIDATION", str(exc), None)
        return BrokerPreflight(self.backend, True, "EXPECTED_MARGIN_OK", "cTrader preflight passed", prepared)

    @staticmethod
    def _position_id_from_execution(response: Any, order: Any) -> tuple[int, str | None]:
        position = getattr(response, "position", None)
        try:
            response_position_id = int(getattr(position, "positionId", 0) or 0)
        except (TypeError, ValueError):
            response_position_id = 0
        try:
            order_position_id = int(getattr(order, "positionId", 0) or 0) if order is not None else 0
        except (TypeError, ValueError):
            order_position_id = 0
        if response_position_id and order_position_id and response_position_id != order_position_id:
            return 0, "execution positionId and order positionId disagree"
        return response_position_id or order_position_id, None

    def _verify_market_protection(
        self,
        *,
        response: Any,
        order: Any,
        prepared: CTraderPreparedOrder,
    ) -> PostFillProtectionOutcome:
        response_account = int(getattr(response, "ctidTraderAccountId", 0) or prepared.account_id)
        if response_account != prepared.account_id:
            return PostFillProtectionOutcome(
                False,
                "ACCOUNT_MISMATCH",
                f"execution account {response_account} != submitted account {prepared.account_id}",
                "0",
            )
        position_id, identity_error = self._position_id_from_execution(response, order)
        if identity_error:
            return PostFillProtectionOutcome(False, "POSITION_ID_MISMATCH", identity_error, "0")
        if position_id <= 0:
            return PostFillProtectionOutcome(
                False,
                "POSITION_ID_UNAVAILABLE",
                "accepted market order did not expose a broker position id; no amend attempted",
                "0",
            )
        return self.protection_manager.ensure(
            account_id=prepared.account_id,
            position_id=position_id,
            symbol_name=prepared.symbol_name,
            symbol_info=prepared.symbol_info,
            expected_symbol_id=prepared.symbol_id,
            expected_trade_side=prepared.trade_side,
            expected_volume_cents=prepared.volume_cents,
            planned_stop_loss=prepared.planned_stop_loss,
            planned_take_profit=prepared.planned_take_profit,
        )

    def submit(self, preflight: BrokerPreflight) -> BrokerOrderResult:
        if not preflight.accepted or not isinstance(preflight.request, CTraderPreparedOrder):
            return BrokerOrderResult(self.backend, False, "INVALID_PREFLIGHT", "invalid prepared order")
        prepared = preflight.request
        try:
            response = self.session.send_new_order(
                prepared.request,
                client_msg_id=f"ord-{prepared.request.clientOrderId}",
            )
        except CollectorUnavailable as exc:
            text = str(exc)
            # ProtoErrorRes / ProtoOAOrderErrorEvent are explicit server-side
            # rejections, so the submission outcome is known (no fill). Only
            # transport/decode ambiguity remains eligible for uncertain-outcome
            # quarantine in the execution router.
            if text.startswith("cTrader API error "):
                code = text.removeprefix("cTrader API error ").split(":", 1)[0]
                return BrokerOrderResult(
                    backend=self.backend,
                    accepted=False,
                    code=code or "API_REJECTED",
                    message=text,
                )
            raise
        execution_type = int(getattr(response, "executionType", -1))
        accepted = execution_type in {2, 3, 11}
        order = getattr(response, "order", None)
        order_id = str(getattr(order, "orderId", "")) or None if order is not None else None
        executed_cents = int(getattr(order, "executedVolume", 0) or 0) if order is not None else 0
        executed_lots = executed_cents / prepared.lot_size_cents if executed_cents else None
        price = float(getattr(order, "executionPrice", 0.0) or 0.0) if order is not None else 0.0

        if not accepted or not prepared.is_market:
            return BrokerOrderResult(
                backend=self.backend,
                accepted=accepted,
                code=str(execution_type),
                message=str(getattr(response, "errorCode", "")) or "execution_event",
                broker_order_id=order_id,
                executed_volume=executed_lots,
                executed_price=price or None,
            )

        protection = self._verify_market_protection(
            response=response,
            order=order,
            prepared=prepared,
        )
        reconciled_lots = (
            protection.executed_volume_cents / prepared.lot_size_cents
            if protection.executed_volume_cents
            else None
        )
        return BrokerOrderResult(
            backend=self.backend,
            accepted=True,
            code=str(execution_type),
            message=str(getattr(response, "errorCode", "")) or "execution_event",
            broker_order_id=order_id,
            executed_volume=reconciled_lots or executed_lots,
            executed_price=protection.executed_entry or price or None,
            broker_position_id=protection.position_id if protection.position_id != "0" else None,
            protection_verified=protection.verified,
            attached_stop_loss=protection.stop_loss,
            attached_take_profit=protection.take_profit,
            protection_code=protection.code,
            protection_message=protection.message,
        )

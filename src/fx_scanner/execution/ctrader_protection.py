from __future__ import annotations

from dataclasses import dataclass
from time import sleep
from typing import Any, Callable
from uuid import uuid4


@dataclass(frozen=True, slots=True)
class PostFillProtectionOutcome:
    verified: bool
    code: str
    message: str
    position_id: str
    executed_entry: float | None = None
    executed_volume_cents: int | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    amended: bool = False


class CTraderPostFillProtectionManager:
    """Verify and, when necessary, repair SL/TP on one newly-filled cTrader position.

    The manager is deliberately keyed by an exact broker position ID obtained
    from the order execution event. It never discovers a repair target by
    symbol alone, so an existing/manual position cannot be amended accidentally.
    All reconcile and amend loops are bounded and the same absolute SL/TP values
    are used for every retry, making retries idempotent.
    """

    def __init__(
        self,
        session,
        *,
        quote_provider: Callable[[str], Any],
        reconcile_attempts: int = 3,
        amend_attempts: int = 2,
        poll_seconds: float = 0.15,
        amend_timeout_seconds: float = 5.0,
    ):
        self.session = session
        self.quote_provider = quote_provider
        self.reconcile_attempts = int(reconcile_attempts)
        self.amend_attempts = int(amend_attempts)
        self.poll_seconds = float(poll_seconds)
        self.amend_timeout_seconds = float(amend_timeout_seconds)
        if self.reconcile_attempts <= 0:
            raise ValueError("reconcile_attempts must be positive")
        if self.amend_attempts <= 0:
            raise ValueError("amend_attempts must be positive")
        if not 0 <= self.poll_seconds <= 1.0:
            raise ValueError("poll_seconds must be in [0,1]")
        if self.amend_timeout_seconds <= 0:
            raise ValueError("amend_timeout_seconds must be positive")

    @staticmethod
    def _positive_float(value: Any) -> float | None:
        try:
            parsed = float(value or 0.0)
        except (TypeError, ValueError):
            return None
        return parsed if parsed > 0 else None

    @staticmethod
    def _position_id(position: Any) -> int:
        try:
            return int(getattr(position, "positionId", 0) or 0)
        except (TypeError, ValueError):
            return 0

    def _reconcile_exact(self, position_id: int) -> Any | None:
        response = self.session.reconcile()
        matches = [
            position
            for position in tuple(getattr(response, "position", ()))
            if self._position_id(position) == int(position_id)
        ]
        if len(matches) > 1:
            raise RuntimeError(f"duplicate broker position id in reconcile: {position_id}")
        return matches[0] if matches else None

    def _wait_for_position(self, position_id: int) -> tuple[Any | None, str | None]:
        last_error: str | None = None
        for attempt in range(self.reconcile_attempts):
            try:
                position = self._reconcile_exact(position_id)
            except Exception as exc:
                last_error = f"{type(exc).__name__}:{exc}"
                position = None
            if position is not None:
                return position, None
            if attempt + 1 < self.reconcile_attempts and self.poll_seconds:
                sleep(self.poll_seconds)
        return None, last_error

    @staticmethod
    def _trade_identity(position: Any) -> tuple[int, int, int]:
        trade_data = getattr(position, "tradeData", None)
        if trade_data is None:
            return 0, 0, 0
        try:
            symbol_id = int(getattr(trade_data, "symbolId", 0) or 0)
        except (TypeError, ValueError):
            symbol_id = 0
        try:
            trade_side = int(getattr(trade_data, "tradeSide", 0) or 0)
        except (TypeError, ValueError):
            trade_side = 0
        try:
            volume = int(getattr(trade_data, "volume", 0) or 0)
        except (TypeError, ValueError):
            volume = 0
        return symbol_id, trade_side, volume

    def _validate_position_identity(
        self,
        position: Any,
        *,
        position_id: int,
        expected_symbol_id: int,
        expected_trade_side: int,
        expected_volume_cents: int,
    ) -> str | None:
        if self._position_id(position) != int(position_id):
            return "POSITION_ID_MISMATCH"
        symbol_id, trade_side, volume = self._trade_identity(position)
        if symbol_id and symbol_id != int(expected_symbol_id):
            return "POSITION_SYMBOL_MISMATCH"
        if trade_side and trade_side != int(expected_trade_side):
            return "POSITION_SIDE_MISMATCH"
        if volume and volume != int(expected_volume_cents):
            return "POSITION_VOLUME_MISMATCH"
        if self._positive_float(getattr(position, "price", None)) is None:
            return "POSITION_ENTRY_UNAVAILABLE"
        return None

    @staticmethod
    def _minimum_distance_price(symbol_info: Any, raw_distance: int, market_price: float) -> float:
        if raw_distance <= 0:
            return 0.0
        digits = int(getattr(symbol_info, "digits", -1))
        if digits < 0:
            raise ValueError("symbol digits unavailable")
        distance_type = int(getattr(symbol_info, "distanceSetIn", 1) or 1)
        if distance_type == 1:  # SYMBOL_DISTANCE_IN_POINTS
            return float(raw_distance) / (10 ** digits)
        if distance_type == 2:  # SYMBOL_DISTANCE_IN_PERCENTAGE; protocol uses 0.01% units.
            return float(market_price) * (float(raw_distance) / 10_000.0)
        raise ValueError(f"unsupported symbol distance type: {distance_type}")

    def _validate_planned_protection(
        self,
        *,
        symbol_name: str,
        symbol_info: Any,
        trade_side: int,
        stop_loss: float,
        take_profit: float,
    ) -> tuple[float, float]:
        digits = int(getattr(symbol_info, "digits", -1))
        if digits < 0:
            raise ValueError("symbol digits unavailable")
        stop_loss = round(float(stop_loss), digits)
        take_profit = round(float(take_profit), digits)
        quote = self.quote_provider(symbol_name)
        bid = float(getattr(quote, "bid"))
        ask = float(getattr(quote, "ask"))
        if not (bid > 0 and ask >= bid):
            raise ValueError("broker quote invalid")

        if int(trade_side) == 1:  # BUY
            if not (stop_loss < bid and take_profit > ask):
                raise ValueError("BUY planned SL/TP no longer brackets live market")
            actual_sl_distance = bid - stop_loss
            actual_tp_distance = take_profit - ask
            sl_reference = bid
            tp_reference = ask
        elif int(trade_side) == 2:  # SELL
            if not (stop_loss > ask and take_profit < bid):
                raise ValueError("SELL planned SL/TP no longer brackets live market")
            actual_sl_distance = stop_loss - ask
            actual_tp_distance = bid - take_profit
            sl_reference = ask
            tp_reference = bid
        else:
            raise ValueError("trade side invalid")

        min_sl = self._minimum_distance_price(
            symbol_info,
            int(getattr(symbol_info, "slDistance", 0) or 0),
            sl_reference,
        )
        min_tp = self._minimum_distance_price(
            symbol_info,
            int(getattr(symbol_info, "tpDistance", 0) or 0),
            tp_reference,
        )
        epsilon = 10 ** (-(digits + 2))
        if actual_sl_distance + epsilon < min_sl:
            raise ValueError(
                f"planned SL violates broker minimum distance: {actual_sl_distance:.10g} < {min_sl:.10g}"
            )
        if actual_tp_distance + epsilon < min_tp:
            raise ValueError(
                f"planned TP violates broker minimum distance: {actual_tp_distance:.10g} < {min_tp:.10g}"
            )
        return stop_loss, take_profit

    def _send_amend(
        self,
        *,
        account_id: int,
        position_id: int,
        stop_loss: float,
        take_profit: float,
    ) -> Any:
        helper = getattr(self.session, "send_amend_position_sltp", None)
        if callable(helper):
            return helper(
                position_id=int(position_id),
                stop_loss=float(stop_loss),
                take_profit=float(take_profit),
                client_msg_id=f"protect-{position_id}-{uuid4().hex[:10]}",
                timeout=self.amend_timeout_seconds,
            )

        # Keep the transport facade unchanged while using the official cTrader
        # protobuf request. Import is intentionally runtime-only because the
        # dependency is optional outside the broker execution environment.
        try:
            from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOAAmendPositionSLTPReq
        except ModuleNotFoundError as exc:
            raise RuntimeError("ctrader-open-api amend message unavailable") from exc
        sender = getattr(self.session, "_send_sync", None)
        if not callable(sender):
            raise RuntimeError("cTrader amend transport unavailable")
        request = ProtoOAAmendPositionSLTPReq()
        request.ctidTraderAccountId = int(account_id)
        request.positionId = int(position_id)
        request.stopLoss = float(stop_loss)
        request.takeProfit = float(take_profit)
        return sender(
            request,
            client_msg_id=f"protect-{position_id}-{uuid4().hex[:10]}",
            timeout=self.amend_timeout_seconds,
        )

    def _outcome_from_position(
        self,
        *,
        verified: bool,
        code: str,
        message: str,
        position: Any,
        amended: bool,
    ) -> PostFillProtectionOutcome:
        _, _, volume = self._trade_identity(position)
        return PostFillProtectionOutcome(
            verified=verified,
            code=code,
            message=message,
            position_id=str(self._position_id(position)),
            executed_entry=self._positive_float(getattr(position, "price", None)),
            executed_volume_cents=volume or None,
            stop_loss=self._positive_float(getattr(position, "stopLoss", None)),
            take_profit=self._positive_float(getattr(position, "takeProfit", None)),
            amended=amended,
        )

    def ensure(
        self,
        *,
        account_id: int,
        position_id: int,
        symbol_name: str,
        symbol_info: Any,
        expected_symbol_id: int,
        expected_trade_side: int,
        expected_volume_cents: int,
        planned_stop_loss: float,
        planned_take_profit: float,
    ) -> PostFillProtectionOutcome:
        if int(position_id) <= 0:
            return PostFillProtectionOutcome(False, "POSITION_ID_INVALID", "broker position id unavailable", str(position_id))
        session_account_id = int(getattr(self.session, "account_id", 0) or 0)
        if session_account_id <= 0 or session_account_id != int(account_id):
            return PostFillProtectionOutcome(
                False,
                "ACCOUNT_MISMATCH",
                f"session account {session_account_id} != execution account {account_id}",
                str(position_id),
            )

        position, reconcile_error = self._wait_for_position(position_id)
        if position is None:
            detail = f":{reconcile_error}" if reconcile_error else ""
            return PostFillProtectionOutcome(
                False,
                "POSITION_RECONCILE_TIMEOUT",
                f"new broker position not reconciled within bounded attempts{detail}",
                str(position_id),
            )

        identity_error = self._validate_position_identity(
            position,
            position_id=position_id,
            expected_symbol_id=expected_symbol_id,
            expected_trade_side=expected_trade_side,
            expected_volume_cents=expected_volume_cents,
        )
        if identity_error:
            return self._outcome_from_position(
                verified=False,
                code=identity_error,
                message="reconciled position identity does not match submitted order",
                position=position,
                amended=False,
            )

        if self._positive_float(getattr(position, "stopLoss", None)) and self._positive_float(
            getattr(position, "takeProfit", None)
        ):
            return self._outcome_from_position(
                verified=True,
                code="PROTECTION_VERIFIED",
                message="broker position already has SL and TP",
                position=position,
                amended=False,
            )

        try:
            stop_loss, take_profit = self._validate_planned_protection(
                symbol_name=symbol_name,
                symbol_info=symbol_info,
                trade_side=expected_trade_side,
                stop_loss=planned_stop_loss,
                take_profit=planned_take_profit,
            )
        except Exception as exc:
            return self._outcome_from_position(
                verified=False,
                code="BROKER_MIN_DISTANCE_REJECTED",
                message=f"{type(exc).__name__}:{exc}",
                position=position,
                amended=False,
            )

        last_error: str | None = None
        for amend_attempt in range(self.amend_attempts):
            # Reconcile immediately before every amend. This both makes retries
            # idempotent and prevents modifying a position that closed after the
            # initial post-fill snapshot.
            try:
                current = self._reconcile_exact(position_id)
            except Exception as exc:
                last_error = f"{type(exc).__name__}:{exc}"
                current = None
            if current is None:
                return PostFillProtectionOutcome(
                    False,
                    "POSITION_CLOSED_BEFORE_AMEND",
                    "position disappeared before SL/TP amend",
                    str(position_id),
                )
            identity_error = self._validate_position_identity(
                current,
                position_id=position_id,
                expected_symbol_id=expected_symbol_id,
                expected_trade_side=expected_trade_side,
                expected_volume_cents=expected_volume_cents,
            )
            if identity_error:
                return self._outcome_from_position(
                    verified=False,
                    code=identity_error,
                    message="position identity changed before amend",
                    position=current,
                    amended=False,
                )
            if self._positive_float(getattr(current, "stopLoss", None)) and self._positive_float(
                getattr(current, "takeProfit", None)
            ):
                return self._outcome_from_position(
                    verified=True,
                    code="PROTECTION_VERIFIED",
                    message="broker protection became complete before amend",
                    position=current,
                    amended=False,
                )

            try:
                self._send_amend(
                    account_id=account_id,
                    position_id=position_id,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                )
            except Exception as exc:
                last_error = f"{type(exc).__name__}:{exc}"

            for poll_attempt in range(self.reconcile_attempts):
                try:
                    reconciled = self._reconcile_exact(position_id)
                except Exception as exc:
                    last_error = f"{type(exc).__name__}:{exc}"
                    reconciled = None
                if reconciled is None:
                    # Once the position has been seen, disappearance means it is
                    # closed or no longer safely addressable; never amend again.
                    return PostFillProtectionOutcome(
                        False,
                        "POSITION_CLOSED_DURING_PROTECTION",
                        "position disappeared while verifying SL/TP amend",
                        str(position_id),
                    )
                identity_error = self._validate_position_identity(
                    reconciled,
                    position_id=position_id,
                    expected_symbol_id=expected_symbol_id,
                    expected_trade_side=expected_trade_side,
                    expected_volume_cents=expected_volume_cents,
                )
                if identity_error:
                    return self._outcome_from_position(
                        verified=False,
                        code=identity_error,
                        message="position identity mismatch during amend reconcile",
                        position=reconciled,
                        amended=True,
                    )
                if self._positive_float(getattr(reconciled, "stopLoss", None)) and self._positive_float(
                    getattr(reconciled, "takeProfit", None)
                ):
                    return self._outcome_from_position(
                        verified=True,
                        code="PROTECTION_AMENDED_AND_VERIFIED",
                        message="missing broker protection repaired and reconciled",
                        position=reconciled,
                        amended=True,
                    )
                if poll_attempt + 1 < self.reconcile_attempts and self.poll_seconds:
                    sleep(self.poll_seconds)

            if amend_attempt + 1 < self.amend_attempts and self.poll_seconds:
                sleep(self.poll_seconds)

        return self._outcome_from_position(
            verified=False,
            code="PROTECTION_AMEND_FAILED",
            message=f"bounded amend/reconcile attempts exhausted:{last_error or 'SL/TP still missing'}",
            position=current,
            amended=True,
        )

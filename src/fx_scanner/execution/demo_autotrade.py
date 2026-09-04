from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from time import sleep
from typing import Any

from .models import OrderIntent, OrderSide, OrderType

UTC = timezone.utc


@dataclass(frozen=True, slots=True)
class DemoAutoReport:
    scanned: int
    eligible: int
    claimed: int
    executed: int
    skipped: tuple[str, ...]


class SupabaseOrderAuditSink:
    """Best-effort audit adapter consumed by ExecutionRouter."""

    def __init__(self, store):
        self.store = store

    def emit(self, event: dict[str, Any]) -> None:
        payload = dict(event.get("payload") or {})
        self.store.record_order_event(
            backend=str(event.get("backend", "CTRADER")),
            account_id=str(event.get("account_id", "UNKNOWN")),
            signal_key=str(event.get("signal_key", "UNKNOWN")),
            event_type=str(event.get("event_type", "UNKNOWN")),
            broker_order_id=payload.get("broker_order_id"),
            accepted=event.get("accepted"),
            code=None if event.get("code") is None else str(event.get("code")),
            message=None if event.get("message") is None else str(event.get("message")),
            payload=payload,
        )


class CTraderDemoAutoExecutor:
    """Consume durable EXECUTION_READY signals and submit demo-only cTrader orders.

    Broker exposure is reconciled before the durable Supabase claim. This keeps
    capacity/same-symbol blocks from consuming a signal into COOLDOWN before any
    broker attempt, while the canonical EXECUTION_READY -> COOLDOWN transition
    remains the atomic claim immediately before execution.

    Transient cTrader transport failures are retried only while the router's
    duplicate guard proves the broker side-effect boundary has not been crossed.
    If all bounded retries fail safely, the durable COOLDOWN claim is atomically
    returned to EXECUTION_READY so a valid signal is not lost to transport noise.
    An indeterminate post-submit outcome is never retried or requeued blindly.
    """

    SAFE_RETRY_DELAYS_SECONDS = (0.5, 1.5)
    TRANSIENT_ERROR_MARKERS = (
        "COLLECTORUNAVAILABLE",
        "TIMEOUT",
        "CONNECTION",
        "UNAVAILABLE",
        "BROKER_SESSION_UNHEALTHY",
        "REQUEST FAILED",
        "REQUEST TIMEOUT",
        "CONNECTION RESET",
        "CONNECTION ABORTED",
        "BROKEN PIPE",
        "NETWORK",
    )

    def __init__(self, *, cfg, policy, gateway, router, store):
        self.cfg = cfg
        self.policy = policy
        self.gateway = gateway
        self.router = router
        self.store = store
        self.demo = policy.demo_safety
        self.control_gate = getattr(router, "control_gate", None)

    @staticmethod
    def _dt(value: Any) -> datetime | None:
        if value in (None, ""):
            return None
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(UTC)

    @classmethod
    def _is_transient_error(cls, exc_or_text: Any) -> bool:
        if isinstance(exc_or_text, BaseException):
            text = f"{type(exc_or_text).__name__}:{exc_or_text}".upper()
        else:
            text = str(exc_or_text).upper()
        return any(marker in text for marker in cls.TRANSIENT_ERROR_MARKERS)

    def _submission_uncertain(self, signal_id: str) -> bool:
        """Fail closed unless router idempotency proves no submit is uncertain."""
        duplicates = getattr(self.router, "duplicates", None)
        checker = getattr(duplicates, "is_uncertain", None)
        if checker is None:
            return True
        try:
            return bool(checker(signal_id))
        except Exception:
            return True

    def _recover_transport(self, *, symbol: str | None = None) -> None:
        """Best-effort forced cTrader reconnect used only before safe retries."""
        session = getattr(self.gateway, "session", None)
        if session is None:
            return
        try:
            session.close()
        except Exception:
            pass
        sleep(0.25)
        try:
            session.ensure_connected()
            if symbol:
                subscribe = getattr(session, "subscribe_spots", None)
                if callable(subscribe):
                    subscribe([symbol])
        except Exception:
            # The next bounded retry remains authoritative. Recovery itself must
            # never turn a transport incident into an unsafe execution attempt.
            pass

    def _requeue_safe_transport_claim(self, signal_id: str) -> bool:
        """Return COOLDOWN -> EXECUTION_READY only after proven pre-submit failure."""
        helper = getattr(self.store, "release_signal_execution_claim", None)
        if callable(helper):
            try:
                return bool(helper(signal_id))
            except Exception:
                return False

        client = getattr(self.store, "client", None)
        if client is None:
            return False
        try:
            response = (
                client.table("signals")
                .update({"state": "EXECUTION_READY"})
                .eq("id", str(signal_id))
                .eq("state", "COOLDOWN")
                .execute()
            )
            rows = list(response.data or [])
        except Exception:
            return False
        return len(rows) == 1

    def _intent(self, row: dict[str, Any], *, now: datetime) -> OrderIntent | None:
        signal_id = str(row.get("id", "")).strip()
        symbol = str(row.get("symbol", "")).upper().strip()
        direction = str(row.get("direction", "")).upper().strip()
        if not signal_id or symbol not in self.cfg.pair_map or direction not in {"LONG", "SHORT"}:
            return None
        if str(row.get("state", "")).upper() != "EXECUTION_READY":
            return None

        guards = row.get("active_guards")
        if guards not in (None, [], ()):
            return None
        coverage = float(row.get("data_coverage") or 0.0)
        if coverage < float(self.demo["min_signal_coverage"]):
            return None
        final_score = row.get("final_score")
        if final_score is not None and float(final_score) < float(
            self.cfg.scoring["states"]["execution_candidate_min"]
        ):
            return None

        observed_at = self._dt(row.get("observed_at"))
        if observed_at is None:
            return None
        age = (now - observed_at).total_seconds()
        if age < -1.0 or age > float(self.policy.order["max_signal_age_seconds"]):
            return None
        expires_at = self._dt(row.get("expires_at"))
        if expires_at is not None and now > expires_at:
            return None

        try:
            entry_low = float(row["entry_low"])
            entry_high = float(row["entry_high"])
            stop_loss = float(row["sl"])
            take_profit = float(row["tp2"])
            rr2 = float(row["rr2"])
        except (TypeError, ValueError, KeyError):
            return None
        if not (
            0 < entry_low < entry_high
            and rr2 >= float(self.cfg.strategy["trade_plan"]["minimum_tp2_rr"])
        ):
            return None

        side = OrderSide.BUY if direction == "LONG" else OrderSide.SELL
        quote = self.gateway.market_quote(symbol)
        executable = float(quote.ask if side == OrderSide.BUY else quote.bid)
        if not entry_low <= executable <= entry_high:
            return None
        if side == OrderSide.BUY and not (stop_loss < executable < take_profit):
            return None
        if side == OrderSide.SELL and not (take_profit < executable < stop_loss):
            return None

        volume = min(0.01, float(self.demo["max_order_lots"]))
        return OrderIntent(
            signal_id=signal_id,
            symbol=symbol,
            side=side,
            order_type=OrderType.MARKET,
            created_at=observed_at,
            volume=volume,
            entry_price=executable,
            stop_loss=stop_loss,
            take_profit=take_profit,
            risk_pct=min(
                float(self.cfg.risk["risk_per_trade_pct"]),
                float(self.demo["max_risk_pct"]),
            ),
            comment=f"DEMO_AUTO:{row.get('setup_type') or 'UNKNOWN'}",
        )

    def _intent_with_transport_retry(
        self, row: dict[str, Any], *, now: datetime
    ) -> OrderIntent | None:
        symbol = str(row.get("symbol", "")).upper().strip() or None
        for attempt in range(len(self.SAFE_RETRY_DELAYS_SECONDS) + 1):
            try:
                return self._intent(row, now=now)
            except Exception as exc:
                if (
                    not self._is_transient_error(exc)
                    or attempt >= len(self.SAFE_RETRY_DELAYS_SECONDS)
                ):
                    raise
                self._recover_transport(symbol=symbol)
                sleep(self.SAFE_RETRY_DELAYS_SECONDS[attempt])
        return None

    def _broker_exposure_block(self, symbol: str) -> str | None:
        """Reconcile current cTrader exposure before consuming the durable signal.

        Fail closed when total broker capacity cannot be read. For the cTrader
        gateway, also reject stacking a second position on the same symbol.
        """
        try:
            open_positions = int(self.gateway.position_count())
        except Exception as exc:
            return f"BROKER_POSITION_RECONCILIATION_FAILED:{type(exc).__name__}:{exc}"

        max_positions = int(self.demo.get("max_concurrent_positions", 1))
        if open_positions >= max_positions:
            return f"BROKER_CAPACITY_FULL:{open_positions}/{max_positions}"

        session = getattr(self.gateway, "session", None)
        if session is None:
            return None
        try:
            session.ensure_connected()
            target_symbol_id = int(session.symbol_info(symbol).symbolId)
            reconcile = session.reconcile()
            for position in tuple(getattr(reconcile, "position", ())):
                trade_data = getattr(position, "tradeData", None)
                position_symbol_id = getattr(trade_data, "symbolId", None)
                if (
                    position_symbol_id is not None
                    and int(position_symbol_id) == target_symbol_id
                ):
                    return f"BROKER_SYMBOL_ALREADY_OPEN:{symbol}"
        except Exception as exc:
            return f"BROKER_SYMBOL_RECONCILIATION_FAILED:{type(exc).__name__}:{exc}"
        return None

    def _broker_exposure_block_with_retry(self, symbol: str) -> str | None:
        block: str | None = None
        for attempt in range(len(self.SAFE_RETRY_DELAYS_SECONDS) + 1):
            block = self._broker_exposure_block(symbol)
            if block is None or not self._is_transient_error(block):
                return block
            if attempt >= len(self.SAFE_RETRY_DELAYS_SECONDS):
                return block
            self._recover_transport(symbol=symbol)
            sleep(self.SAFE_RETRY_DELAYS_SECONDS[attempt])
        return block

    def _execute_claimed_with_retry(self, intent: OrderIntent) -> tuple[bool, str | None]:
        """Execute a claimed signal; retry only while broker submission is known not to have started."""
        last_exc: Exception | None = None
        for attempt in range(len(self.SAFE_RETRY_DELAYS_SECONDS) + 1):
            try:
                receipt = self.router.execute(intent)
                return bool(receipt.accepted), None
            except Exception as exc:
                last_exc = exc
                if self._submission_uncertain(intent.signal_id):
                    return False, (
                        f"OUTCOME_UNCERTAIN:{type(exc).__name__}:{exc}"
                    )
                if (
                    not self._is_transient_error(exc)
                    or attempt >= len(self.SAFE_RETRY_DELAYS_SECONDS)
                ):
                    break
                self._recover_transport(symbol=intent.symbol)
                sleep(self.SAFE_RETRY_DELAYS_SECONDS[attempt])

        if last_exc is None:
            return False, "EXECUTION_FAILED:UNKNOWN"

        if self._is_transient_error(last_exc) and not self._submission_uncertain(
            intent.signal_id
        ):
            requeued = self._requeue_safe_transport_claim(intent.signal_id)
            state = "REQUEUED" if requeued else "REQUEUE_FAILED"
            return False, (
                f"TRANSIENT_{state}:{type(last_exc).__name__}:{last_exc}"
            )

        return False, f"EXECUTION_BLOCKED:{type(last_exc).__name__}:{last_exc}"

    def poll_once(self, *, limit: int = 10) -> DemoAutoReport:
        if self.policy.live_safety.get("require_control_plane", False):
            if self.control_gate is None:
                return DemoAutoReport(
                    0, 0, 0, 0, ("CONTROL_PLANE_BLOCKED:NOT_CONFIGURED",)
                )
            try:
                self.control_gate.assert_orders_allowed(self.policy.mode.value)
            except Exception as exc:
                return DemoAutoReport(
                    0,
                    0,
                    0,
                    0,
                    (f"CONTROL_PLANE_BLOCKED:{type(exc).__name__}:{exc}",),
                )

        now = datetime.now(tz=UTC)
        rows = self.store.list_execution_ready_signals(limit=limit)
        eligible = 0
        claimed = 0
        executed = 0
        skipped: list[str] = []

        for row in rows:
            signal_id = str(row.get("id", "UNKNOWN"))
            try:
                intent = self._intent_with_transport_retry(row, now=now)
            except Exception as exc:
                skipped.append(f"{signal_id}:INTENT_ERROR:{type(exc).__name__}:{exc}")
                continue
            if intent is None:
                skipped.append(f"{signal_id}:NOT_ELIGIBLE")
                continue
            eligible += 1

            exposure_block = self._broker_exposure_block_with_retry(intent.symbol)
            if exposure_block is not None:
                skipped.append(f"{signal_id}:{exposure_block}")
                continue

            try:
                if not self.store.claim_signal_for_execution(intent.signal_id):
                    skipped.append(f"{signal_id}:CLAIM_LOST")
                    continue
                claimed += 1
            except Exception as exc:
                skipped.append(f"{signal_id}:CLAIM_ERROR:{type(exc).__name__}:{exc}")
                continue

            accepted, failure = self._execute_claimed_with_retry(intent)
            if accepted:
                executed += 1
            elif failure is not None:
                skipped.append(f"{signal_id}:{failure}")
            else:
                skipped.append(f"{signal_id}:BROKER_NOT_ACCEPTED")

        return DemoAutoReport(
            scanned=len(rows),
            eligible=eligible,
            claimed=claimed,
            executed=executed,
            skipped=tuple(skipped),
        )

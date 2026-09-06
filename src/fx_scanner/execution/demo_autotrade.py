from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite
from time import sleep
from typing import Any

from .demo_position_transition import close_opposite_symbol_positions, inspect_symbol_exposure
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

    Same-symbol stacking is allowed only when the new qualified signal has the
    same direction as existing scanner-linked positions. A qualified opposite
    signal closes scanner-linked opposite positions first, never blind-retries
    an uncertain close, then revalidates the new signal before broker submission.
    Account-wide capacity and all existing execution/risk guards remain active.
    """

    SAFE_RETRY_DELAYS_SECONDS = (0.5, 1.5)
    SAME_DIRECTION_STACKING_REASON = "BROKER_SYMBOL_SAME_DIRECTION_ALLOWED"
    OPPOSITE_CLOSE_REQUIRED = "BROKER_OPPOSITE_DIRECTION_CLOSE_REQUIRED"
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

    def __init__(self, *, cfg, policy, gateway, router, store, adaptive_policy=None):
        self.cfg = cfg
        self.policy = policy
        self.gateway = gateway
        self.router = router
        self.store = store
        self.adaptive_policy = adaptive_policy
        self.demo = policy.demo_safety
        self.control_gate = getattr(router, "control_gate", None)
        self.max_entry_drift_r = self._demo_entry_drift_r()

    @staticmethod
    def _dt(value: Any) -> datetime | None:
        if value in (None, ""):
            return None
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(UTC)

    @staticmethod
    def _demo_entry_drift_r() -> float:
        raw = os.getenv("CTRADER_DEMO_MAX_ENTRY_DRIFT_R", "0.50").strip()
        try:
            value = float(raw)
        except ValueError as exc:
            raise ValueError("CTRADER_DEMO_MAX_ENTRY_DRIFT_R_INVALID") from exc
        if not isfinite(value) or not 0.0 <= value <= 1.0:
            raise ValueError("CTRADER_DEMO_MAX_ENTRY_DRIFT_R_OUT_OF_RANGE")
        return value

    @classmethod
    def _is_transient_error(cls, exc_or_text: Any) -> bool:
        if isinstance(exc_or_text, BaseException):
            text = f"{type(exc_or_text).__name__}:{exc_or_text}".upper()
        else:
            text = str(exc_or_text).upper()
        return any(marker in text for marker in cls.TRANSIENT_ERROR_MARKERS)

    def _submission_uncertain(self, signal_id: str) -> bool:
        duplicates = getattr(self.router, "duplicates", None)
        checker = getattr(duplicates, "is_uncertain", None)
        if checker is None:
            return True
        try:
            return bool(checker(signal_id))
        except Exception:
            return True

    def _recover_transport(self, *, symbol: str | None = None) -> None:
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
            pass

    def _requeue_safe_transport_claim(self, signal_id: str) -> bool:
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

    def _required_score(self, row: dict[str, Any]) -> float:
        base = float(self.cfg.scoring["states"]["execution_candidate_min"])
        if self.adaptive_policy is None:
            return base
        required = float(self.adaptive_policy.required_score(row))
        if not isfinite(required) or required < base or required > 100.0:
            raise ValueError("CTRADER_DEMO_ADAPTIVE_SCORE_FLOOR_INVALID")
        return required

    def _intent_diagnostic(self, row: dict[str, Any], *, now: datetime) -> tuple[OrderIntent | None, str | None]:
        signal_id = str(row.get("id", "")).strip()
        symbol = str(row.get("symbol", "")).upper().strip()
        direction = str(row.get("direction", "")).upper().strip()
        if not signal_id or symbol not in self.cfg.pair_map or direction not in {"LONG", "SHORT"}:
            return None, "IDENTITY_INVALID"
        if str(row.get("state", "")).upper() != "EXECUTION_READY":
            return None, "STATE_NOT_EXECUTION_READY"
        guards = row.get("active_guards")
        if guards not in (None, [], ()):
            return None, "ACTIVE_GUARDS"
        coverage = float(row.get("data_coverage") or 0.0)
        if coverage < float(self.demo["min_signal_coverage"]):
            return None, "COVERAGE_BELOW_MIN"
        required_score = self._required_score(row)
        final_score = row.get("final_score")
        if final_score is not None and float(final_score) < required_score:
            base_score = float(self.cfg.scoring["states"]["execution_candidate_min"])
            if required_score > base_score + 1e-9:
                return None, f"ADAPTIVE_SCORE_BELOW_{required_score:.2f}"
            return None, "SCORE_BELOW_MIN"
        observed_at = self._dt(row.get("observed_at"))
        if observed_at is None:
            return None, "OBSERVED_AT_INVALID"
        age = (now - observed_at).total_seconds()
        if age < -1.0:
            return None, "SIGNAL_TIMESTAMP_IN_FUTURE"
        if age > float(self.policy.order["max_signal_age_seconds"]):
            return None, "SIGNAL_TOO_OLD"
        expires_at = self._dt(row.get("expires_at"))
        if expires_at is not None and now > expires_at:
            return None, "SIGNAL_EXPIRED"
        try:
            entry_low = float(row["entry_low"])
            entry_high = float(row["entry_high"])
            stop_loss = float(row["sl"])
            take_profit = float(row["tp2"])
            rr2 = float(row["rr2"])
        except (TypeError, ValueError, KeyError):
            return None, "PLAN_FIELDS_INVALID"
        minimum_rr = float(self.cfg.strategy["trade_plan"]["minimum_tp2_rr"])
        if not (0 < entry_low < entry_high and rr2 >= minimum_rr):
            return None, "PLAN_GEOMETRY_INVALID"
        side = OrderSide.BUY if direction == "LONG" else OrderSide.SELL
        quote = self.gateway.market_quote(symbol)
        executable = float(quote.ask if side == OrderSide.BUY else quote.bid)
        if side == OrderSide.BUY:
            if not (stop_loss < executable < take_profit):
                return None, "LIVE_SLTP_GEOMETRY_INVALID"
            planned_risk = entry_high - stop_loss
            live_risk = executable - stop_loss
            live_reward = take_profit - executable
        else:
            if not (take_profit < executable < stop_loss):
                return None, "LIVE_SLTP_GEOMETRY_INVALID"
            planned_risk = stop_loss - entry_low
            live_risk = stop_loss - executable
            live_reward = executable - take_profit
        if planned_risk <= 0 or live_risk <= 0 or live_reward <= 0:
            return None, "LIVE_RISK_GEOMETRY_INVALID"
        live_rr2 = live_reward / live_risk
        if live_rr2 + 1e-9 < minimum_rr:
            return None, f"LIVE_RR_BELOW_MIN_{live_rr2:.3f}"
        if executable < entry_low:
            drift = entry_low - executable
        elif executable > entry_high:
            drift = executable - entry_high
        else:
            drift = 0.0
        drift_r = drift / planned_risk
        if drift_r > self.max_entry_drift_r + 1e-9:
            return None, f"ENTRY_DRIFT_R_EXCEEDED_{drift_r:.3f}"
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
            risk_pct=min(float(self.cfg.risk["risk_per_trade_pct"]), float(self.demo["max_risk_pct"])),
            comment=f"DEMO_AUTO:{row.get('setup_type') or 'UNKNOWN'}",
        ), None

    def _intent(self, row: dict[str, Any], *, now: datetime) -> OrderIntent | None:
        intent, _reason = self._intent_diagnostic(row, now=now)
        return intent

    def _intent_with_transport_retry(self, row: dict[str, Any], *, now: datetime) -> tuple[OrderIntent | None, str | None]:
        symbol = str(row.get("symbol", "")).upper().strip() or None
        for attempt in range(len(self.SAFE_RETRY_DELAYS_SECONDS) + 1):
            try:
                return self._intent_diagnostic(row, now=now)
            except Exception as exc:
                if not self._is_transient_error(exc) or attempt >= len(self.SAFE_RETRY_DELAYS_SECONDS):
                    raise
                self._recover_transport(symbol=symbol)
                sleep(self.SAFE_RETRY_DELAYS_SECONDS[attempt])
        return None, "UNKNOWN"

    def _broker_exposure_block(self, intent: OrderIntent) -> str | None:
        session = getattr(self.gateway, "session", None)
        if session is None:
            try:
                open_positions = int(self.gateway.position_count())
            except Exception as exc:
                return f"BROKER_POSITION_RECONCILIATION_FAILED:{type(exc).__name__}:{exc}"
            max_positions = int(self.demo.get("max_concurrent_positions", 1))
            return f"BROKER_CAPACITY_FULL:{open_positions}/{max_positions}" if open_positions >= max_positions else None
        direction = "LONG" if intent.side == OrderSide.BUY else "SHORT"
        prefix = str(self.policy.order.get("comment_prefix", "FXIS"))
        try:
            session.ensure_connected()
            exposure = inspect_symbol_exposure(
                session=session,
                store=self.store,
                symbol=intent.symbol,
                direction=direction,
                comment_prefix=prefix,
            )
        except Exception as exc:
            return f"BROKER_SYMBOL_RECONCILIATION_FAILED:{type(exc).__name__}:{exc}"
        if exposure.unmanaged:
            return f"BROKER_SYMBOL_UNMANAGED_POSITION:{intent.symbol}"
        if exposure.opposite_direction:
            return self.OPPOSITE_CLOSE_REQUIRED
        try:
            open_positions = int(self.gateway.position_count())
        except Exception as exc:
            return f"BROKER_POSITION_RECONCILIATION_FAILED:{type(exc).__name__}:{exc}"
        max_positions = int(self.demo.get("max_concurrent_positions", 1))
        if open_positions >= max_positions:
            return f"BROKER_CAPACITY_FULL:{open_positions}/{max_positions}"
        if exposure.same_direction:
            _same_direction_policy = self.SAME_DIRECTION_STACKING_REASON
        return None

    def _close_opposite_symbol_positions(self, intent: OrderIntent) -> str | None:
        session = getattr(self.gateway, "session", None)
        if session is None:
            return "BROKER_OPPOSITE_DIRECTION_SESSION_UNAVAILABLE"
        direction = "LONG" if intent.side == OrderSide.BUY else "SHORT"
        prefix = str(self.policy.order.get("comment_prefix", "FXIS"))
        return close_opposite_symbol_positions(
            session=session,
            store=self.store,
            symbol=intent.symbol,
            direction=direction,
            new_signal_id=intent.signal_id,
            comment_prefix=prefix,
        )

    def _broker_exposure_block_with_retry(self, intent: OrderIntent) -> str | None:
        block: str | None = None
        for attempt in range(len(self.SAFE_RETRY_DELAYS_SECONDS) + 1):
            block = self._broker_exposure_block(intent)
            if block == self.OPPOSITE_CLOSE_REQUIRED:
                close_block = self._close_opposite_symbol_positions(intent)
                if close_block is not None:
                    return close_block
                block = self._broker_exposure_block(intent)
            if block is None or not self._is_transient_error(block):
                return block
            if attempt >= len(self.SAFE_RETRY_DELAYS_SECONDS):
                return block
            self._recover_transport(symbol=intent.symbol)
            sleep(self.SAFE_RETRY_DELAYS_SECONDS[attempt])
        return block

    def _execute_claimed_with_retry(self, intent: OrderIntent) -> tuple[bool, str | None]:
        last_exc: Exception | None = None
        for attempt in range(len(self.SAFE_RETRY_DELAYS_SECONDS) + 1):
            try:
                receipt = self.router.execute(intent)
                return bool(receipt.accepted), None
            except Exception as exc:
                last_exc = exc
                if self._submission_uncertain(intent.signal_id):
                    return False, f"OUTCOME_UNCERTAIN:{type(exc).__name__}:{exc}"
                if not self._is_transient_error(exc) or attempt >= len(self.SAFE_RETRY_DELAYS_SECONDS):
                    break
                self._recover_transport(symbol=intent.symbol)
                sleep(self.SAFE_RETRY_DELAYS_SECONDS[attempt])
        if last_exc is None:
            return False, "EXECUTION_FAILED:UNKNOWN"
        if self._is_transient_error(last_exc) and not self._submission_uncertain(intent.signal_id):
            requeued = self._requeue_safe_transport_claim(intent.signal_id)
            state = "REQUEUED" if requeued else "REQUEUE_FAILED"
            return False, f"TRANSIENT_{state}:{type(last_exc).__name__}:{last_exc}"
        return False, f"EXECUTION_BLOCKED:{type(last_exc).__name__}:{last_exc}"

    def poll_once(self, *, limit: int = 10) -> DemoAutoReport:
        if self.policy.live_safety.get("require_control_plane", False):
            if self.control_gate is None:
                return DemoAutoReport(0, 0, 0, 0, ("CONTROL_PLANE_BLOCKED:NOT_CONFIGURED",))
            try:
                self.control_gate.assert_orders_allowed(self.policy.mode.value)
            except Exception as exc:
                return DemoAutoReport(0, 0, 0, 0, (f"CONTROL_PLANE_BLOCKED:{type(exc).__name__}:{exc}",))
        now = datetime.now(tz=UTC)
        rows = self.store.list_execution_ready_signals(limit=limit)
        eligible = claimed = executed = 0
        skipped: list[str] = []
        for row in rows:
            signal_id = str(row.get("id", "UNKNOWN"))
            try:
                intent, ineligible_reason = self._intent_with_transport_retry(row, now=now)
            except Exception as exc:
                skipped.append(f"{signal_id}:INTENT_ERROR:{type(exc).__name__}:{exc}")
                continue
            if intent is None:
                skipped.append(f"{signal_id}:NOT_ELIGIBLE:{ineligible_reason or 'UNKNOWN'}")
                continue
            eligible += 1
            exposure_block = self._broker_exposure_block_with_retry(intent)
            if exposure_block is not None:
                skipped.append(f"{signal_id}:{exposure_block}")
                continue
            # A reversal may have closed an existing position. Revalidate fresh
            # quote/age/RR/drift after that broker side effect before new entry.
            try:
                refreshed_intent, refresh_reason = self._intent_with_transport_retry(
                    row, now=datetime.now(tz=UTC)
                )
            except Exception as exc:
                skipped.append(f"{signal_id}:POST_TRANSITION_REVALIDATION_ERROR:{type(exc).__name__}:{exc}")
                continue
            if refreshed_intent is None:
                skipped.append(f"{signal_id}:POST_TRANSITION_NOT_ELIGIBLE:{refresh_reason or 'UNKNOWN'}")
                continue
            intent = refreshed_intent
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
        return DemoAutoReport(scanned=len(rows), eligible=eligible, claimed=claimed, executed=executed, skipped=tuple(skipped))

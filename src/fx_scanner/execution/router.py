from __future__ import annotations

import os
from dataclasses import asdict
from datetime import datetime, timezone

from ..exceptions import FXScannerError
from .duplicate_guard import DuplicateOrderGuard
from .kill_switch import KillSwitch
from .models import ExecutionMode, OrderIntent, OrderReceipt
from .policy import ExecutionPolicy


UTC = timezone.utc


class ExecutionBlocked(FXScannerError):
    pass


class ExecutionRouter:
    """Centralized broker-agnostic execution state machine.

    In dual-feed mode, strategy decisions arrive with canonical symbols. A
    revalidator reconciles FP Markets cTrader research prices against HFM Cent
    MT5 and returns an execution-ready intent with broker symbol and broker-
    specific position size. No Supabase network call is permitted here.
    """

    def __init__(
        self,
        policy: ExecutionPolicy,
        *,
        duplicate_guard: DuplicateOrderGuard | None = None,
        kill_switch: KillSwitch | None = None,
        gateway=None,
        session=None,
        control_gate=None,
        revalidator=None,
        audit_sink=None,
    ):
        self.policy = policy
        safety = policy.live_safety
        if duplicate_guard is None and safety.get("require_persistent_idempotency", False):
            state_env = str(safety.get("idempotency_state_path_env", "")).strip()
            state_path = os.getenv(state_env, "").strip() if state_env else ""
            duplicate_guard = DuplicateOrderGuard(state_path or None)
        self.duplicates = duplicate_guard or DuplicateOrderGuard()
        self.kill_switch = kill_switch or KillSwitch(
            safety["kill_switch_env"],
            safety.get("kill_switch_safe_value", "0"),
        )
        self.gateway = gateway
        self.session = session
        self.control_gate = control_gate
        self.revalidator = revalidator
        self.audit_sink = audit_sink

    def _audit(self, event_type: str, *, account_id: str = "UNKNOWN", accepted=None, code=None, message=None, payload=None) -> None:
        if self.audit_sink is None:
            return
        backend = getattr(getattr(self.gateway, "backend", None), "value", "MT5")
        try:
            self.audit_sink.emit({
                "backend": str(backend),
                "account_id": str(account_id),
                "signal_key": str((payload or {}).get("signal_id", "UNKNOWN")),
                "event_type": event_type,
                "accepted": accepted,
                "code": code,
                "message": message,
                "payload": payload or {},
            })
        except Exception:
            # Audit is deliberately non-critical-path. Safety decisions must not
            # depend on telemetry availability.
            pass

    def _assert_dynamic_safety(self, intent: OrderIntent) -> None:
        if self.kill_switch.engaged():
            raise ExecutionBlocked("KILL_SWITCH_ENGAGED")
        max_age = int(self.policy.order.get("max_signal_age_seconds", 300))
        age = (datetime.now(tz=UTC) - intent.created_at).total_seconds()
        if age < -1.0:
            raise ExecutionBlocked("SIGNAL_TIMESTAMP_IN_FUTURE")
        if age > max_age:
            raise ExecutionBlocked("STALE_SIGNAL")

    def _assert_common(self, intent: OrderIntent) -> None:
        self._assert_dynamic_safety(intent)
        if self.duplicates.is_duplicate(intent.signal_id):
            raise ExecutionBlocked("DUPLICATE_SIGNAL")

    def _assert_control_plane(self) -> None:
        safety = self.policy.live_safety
        if not safety.get("require_control_plane", False):
            return
        if self.control_gate is None:
            raise ExecutionBlocked("CONTROL_PLANE_NOT_CONFIGURED")
        try:
            self.control_gate.assert_orders_allowed(self.policy.mode.value)
        except Exception as exc:
            raise ExecutionBlocked(f"CONTROL_PLANE_BLOCK:{exc}") from exc

    def _assert_live_environment(self, account_id: str) -> None:
        safety = self.policy.live_safety
        if os.getenv(safety["live_enable_env"]) != safety["live_enable_value"]:
            raise ExecutionBlocked("LIVE_ENV_GATE_CLOSED")
        allowed_raw = os.getenv(safety["account_allowlist_env"], "")
        allowlist = {x.strip() for x in allowed_raw.split(",") if x.strip()}
        if safety.get("require_account_allowlist", True) and str(account_id) not in allowlist:
            raise ExecutionBlocked("ACCOUNT_NOT_ALLOWLISTED")
        if safety.get("require_persistent_idempotency", False) and self.duplicates.path is None:
            raise ExecutionBlocked("PERSISTENT_IDEMPOTENCY_NOT_CONFIGURED")
        self._assert_control_plane()

    def execute(self, intent: OrderIntent, *, user_confirmed: bool = False) -> OrderReceipt:
        self._assert_common(intent)
        mode = self.policy.mode
        if mode == ExecutionMode.DISABLED:
            raise ExecutionBlocked("EXECUTION_DISABLED")
        if mode == ExecutionMode.CONFIRM_TO_TRADE and not user_confirmed:
            raise ExecutionBlocked("USER_CONFIRMATION_REQUIRED")
        if mode not in (ExecutionMode.SIMULATION, ExecutionMode.CONFIRM_TO_TRADE, ExecutionMode.AUTO):
            raise ExecutionBlocked("UNSUPPORTED_MODE")

        if not self.duplicates.try_claim(intent.signal_id):
            raise ExecutionBlocked("DUPLICATE_SIGNAL")

        account_id = "UNKNOWN"
        submit_attempted = False
        submit_outcome_known = False
        try:
            if mode == ExecutionMode.SIMULATION:
                self._assert_dynamic_safety(intent)
                self.duplicates.mark_executed(intent.signal_id)
                return OrderReceipt(
                    intent.signal_id,
                    intent.symbol,
                    mode,
                    True,
                    None,
                    "SIMULATED",
                    intent.volume,
                    intent.entry_price,
                )

            if self.gateway is None:
                raise ExecutionBlocked("BROKER_GATEWAY_NOT_CONFIGURED")
            if self.session is not None:
                try:
                    self.session.ensure_connected()
                except Exception as exc:
                    raise ExecutionBlocked(f"BROKER_SESSION_UNHEALTHY:{exc}") from exc

            effective_intent = intent
            account = None
            if self.policy.live_safety.get("require_revalidation", False):
                if self.revalidator is None:
                    raise ExecutionBlocked("REVALIDATOR_NOT_CONFIGURED")
                try:
                    validated = self.revalidator.revalidate(intent)
                except Exception as exc:
                    self._audit(
                        "REVALIDATION_BLOCK",
                        code=type(exc).__name__,
                        message=str(exc),
                        payload={"signal_id": intent.signal_id, "symbol": intent.symbol},
                    )
                    raise ExecutionBlocked(f"REVALIDATION_BLOCK:{exc}") from exc
                effective_intent = validated.prepared_intent
                account = validated.account_snapshot
                account_id = str(account.account_id)
                self._audit(
                    "REVALIDATION_PASS",
                    account_id=account_id,
                    accepted=True,
                    code="OK",
                    message="dual-feed reconciliation passed",
                    payload={
                        "signal_id": intent.signal_id,
                        "symbol": intent.symbol,
                        "broker_symbol": effective_intent.broker_symbol,
                        "volume": effective_intent.volume,
                        "metrics": asdict(validated.metrics),
                    },
                )

            if account is None:
                account = self.gateway.account_snapshot()
                account_id = str(account.account_id)

            self._assert_live_environment(account_id)
            if not account.trade_allowed:
                raise ExecutionBlocked("ACCOUNT_TRADING_NOT_ALLOWED")

            preflight = self.gateway.preflight(effective_intent, self.policy.order)
            if not preflight.accepted:
                raise ExecutionBlocked(f"PREFLIGHT_REJECTED:{preflight.code}:{preflight.message}")

            # Re-check mutable safety immediately before the side effect.
            self._assert_dynamic_safety(intent)
            self._assert_control_plane()

            submit_attempted = True
            result = self.gateway.submit(preflight)
            submit_outcome_known = True
            if not result.accepted:
                raise ExecutionBlocked(f"ORDER_SEND_REJECTED:{result.code}:{result.message}")

            self.duplicates.mark_executed(intent.signal_id)
            self._audit(
                "ORDER_ACCEPTED",
                account_id=account_id,
                accepted=True,
                code=result.code,
                message=result.message,
                payload={
                    "signal_id": intent.signal_id,
                    "symbol": intent.symbol,
                    "broker_symbol": effective_intent.broker_symbol,
                    "broker_order_id": result.broker_order_id,
                },
            )
            return OrderReceipt(
                intent.signal_id,
                intent.symbol,
                mode,
                True,
                result.broker_order_id,
                f"{result.backend.value}_ACCEPTED:{result.code}:{result.message}",
                result.executed_volume,
                result.executed_price,
            )
        except Exception as exc:
            if submit_attempted and not submit_outcome_known:
                self.duplicates.mark_uncertain(intent.signal_id)
                self._audit(
                    "ORDER_OUTCOME_UNCERTAIN",
                    account_id=account_id,
                    accepted=None,
                    code="RECONCILIATION_REQUIRED",
                    message=str(exc),
                    payload={"signal_id": intent.signal_id, "symbol": intent.symbol},
                )
            else:
                self.duplicates.release_claim(intent.signal_id)
            self._audit(
                "EXECUTION_BLOCKED",
                account_id=account_id,
                accepted=False,
                code=type(exc).__name__,
                message=str(exc),
                payload={"signal_id": intent.signal_id, "symbol": intent.symbol},
            )
            raise

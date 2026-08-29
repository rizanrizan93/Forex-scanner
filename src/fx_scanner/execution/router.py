from __future__ import annotations

import os
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

    All live order side effects must pass through this router. The selected
    gateway may be cTrader or MT5, but the safety contract is identical.
    """

    def __init__(
        self,
        policy: ExecutionPolicy,
        *,
        duplicate_guard: DuplicateOrderGuard | None = None,
        kill_switch: KillSwitch | None = None,
        gateway=None,
        session=None,
    ):
        self.policy = policy
        self.duplicates = duplicate_guard or DuplicateOrderGuard()
        safety = policy.live_safety
        self.kill_switch = kill_switch or KillSwitch(
            safety["kill_switch_env"],
            safety.get("kill_switch_safe_value", "0"),
        )
        self.gateway = gateway
        self.session = session

    def _assert_dynamic_safety(self, intent: OrderIntent) -> None:
        if self.kill_switch.engaged():
            raise ExecutionBlocked("KILL_SWITCH_ENGAGED")
        max_age = int(self.policy.order.get("max_signal_age_seconds", 300))
        age = (datetime.now(tz=UTC) - intent.created_at).total_seconds()
        if age > max_age:
            raise ExecutionBlocked("STALE_SIGNAL")

    def _assert_common(self, intent: OrderIntent) -> None:
        self._assert_dynamic_safety(intent)
        if self.duplicates.is_duplicate(intent.signal_id):
            raise ExecutionBlocked("DUPLICATE_SIGNAL")

    def _assert_live_environment(self, account_id: str) -> None:
        safety = self.policy.live_safety
        if os.getenv(safety["live_enable_env"]) != safety["live_enable_value"]:
            raise ExecutionBlocked("LIVE_ENV_GATE_CLOSED")
        allowed_raw = os.getenv(safety["account_allowlist_env"], "")
        allowlist = {x.strip() for x in allowed_raw.split(",") if x.strip()}
        if safety.get("require_account_allowlist", True) and str(account_id) not in allowlist:
            raise ExecutionBlocked("ACCOUNT_NOT_ALLOWLISTED")

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

            account = self.gateway.account_snapshot()
            self._assert_live_environment(account.account_id)
            if not account.trade_allowed:
                raise ExecutionBlocked("ACCOUNT_TRADING_NOT_ALLOWED")

            preflight = self.gateway.preflight(intent, self.policy.order)
            if not preflight.accepted:
                raise ExecutionBlocked(f"PREFLIGHT_REJECTED:{preflight.code}:{preflight.message}")

            self._assert_dynamic_safety(intent)

            result = self.gateway.submit(preflight)
            if not result.accepted:
                raise ExecutionBlocked(f"ORDER_SEND_REJECTED:{result.code}:{result.message}")

            self.duplicates.mark_executed(intent.signal_id)
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
        except Exception:
            self.duplicates.release_claim(intent.signal_id)
            raise

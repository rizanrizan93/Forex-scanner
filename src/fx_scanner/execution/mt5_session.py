from __future__ import annotations

from dataclasses import dataclass
from time import monotonic, sleep
from typing import Callable

from ..exceptions import CollectorUnavailable
from .runtime import BackoffPolicy, CircuitBreaker


@dataclass(frozen=True, slots=True)
class SessionHealth:
    connected: bool
    terminal_ok: bool
    account_ok: bool
    circuit_state: str
    consecutive_failures: int


class PersistentMT5Session:
    """Keeps one MT5 terminal session alive and reconnects conservatively.

    The gateway is expected to provide connect(), close(), terminal_health(), and
    account_snapshot(). No order is ever sent from this class.
    """

    def __init__(
        self,
        gateway,
        *,
        backoff: BackoffPolicy | None = None,
        circuit_breaker: CircuitBreaker | None = None,
        sleeper: Callable[[float], None] = sleep,
    ):
        self.gateway = gateway
        self.backoff = backoff or BackoffPolicy()
        self.breaker = circuit_breaker or CircuitBreaker()
        self.sleeper = sleeper
        self.failure_count = 0

    def health(self) -> SessionHealth:
        connected = bool(getattr(self.gateway, "connected", False))
        terminal_ok = False
        account_ok = False
        if connected:
            try:
                terminal_ok = bool(self.gateway.terminal_health())
                self.gateway.account_snapshot()
                account_ok = True
            except Exception:
                terminal_ok = False
                account_ok = False
        return SessionHealth(
            connected=connected,
            terminal_ok=terminal_ok,
            account_ok=account_ok,
            circuit_state=self.breaker.state.value,
            consecutive_failures=self.breaker.consecutive_failures,
        )

    def ensure_connected(self, *, now_mono: float | None = None, max_attempts: int = 3) -> None:
        now_mono = monotonic() if now_mono is None else now_mono
        if not self.breaker.allow(now_mono):
            raise CollectorUnavailable("MT5_CIRCUIT_OPEN")

        health = self.health()
        if health.connected and health.terminal_ok and health.account_ok:
            self.failure_count = 0
            self.breaker.record_success()
            return

        try:
            self.gateway.close()
        except Exception:
            pass

        last_exc: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                self.gateway.connect()
                post = self.health()
                if not (post.connected and post.terminal_ok and post.account_ok):
                    raise CollectorUnavailable("MT5_HEALTH_CHECK_FAILED")
                self.failure_count = 0
                self.breaker.record_success()
                return
            except Exception as exc:
                last_exc = exc
                self.failure_count += 1
                self.breaker.record_failure(now_mono)
                if attempt < max_attempts and self.breaker.allow(now_mono):
                    self.sleeper(self.backoff.delay(self.failure_count))

        raise CollectorUnavailable(f"MT5_RECONNECT_FAILED:{last_exc}")

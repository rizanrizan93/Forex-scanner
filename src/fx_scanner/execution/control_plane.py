from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from time import monotonic
from typing import Callable

from ..exceptions import FXScannerError
from ..storage.supabase_operational import ExecutionControlSnapshot, SupabaseOperationalStore


class ControlPlaneBlocked(FXScannerError):
    pass


@dataclass(frozen=True, slots=True)
class CachedControlState:
    snapshot: ExecutionControlSnapshot
    refreshed_mono: float


class ControlPlaneGate:
    """In-memory live-order gate refreshed asynchronously from Supabase.

    The execution path never performs network I/O. It only inspects this cache.
    If the cache is missing or stale, new live orders fail closed.
    """

    def __init__(self, *, max_age_seconds: float = 5.0, clock: Callable[[], float] = monotonic):
        if max_age_seconds <= 0:
            raise ValueError("max_age_seconds must be positive")
        self.max_age_seconds = float(max_age_seconds)
        self.clock = clock
        self._lock = Lock()
        self._state: CachedControlState | None = None

    def refresh(self, store: SupabaseOperationalStore) -> ExecutionControlSnapshot:
        snapshot = store.get_execution_control()
        with self._lock:
            self._state = CachedControlState(snapshot, self.clock())
        return snapshot

    def snapshot(self) -> CachedControlState | None:
        with self._lock:
            return self._state

    def assert_orders_allowed(self, required_mode: str) -> None:
        with self._lock:
            state = self._state
        if state is None:
            raise ControlPlaneBlocked("CONTROL_STATE_MISSING")
        age = self.clock() - state.refreshed_mono
        if age < 0 or age > self.max_age_seconds:
            raise ControlPlaneBlocked(f"CONTROL_STATE_STALE:{age:.3f}s")

        snap = state.snapshot
        if snap.emergency_stop:
            raise ControlPlaneBlocked("EMERGENCY_STOP")
        if not snap.new_orders_enabled:
            raise ControlPlaneBlocked("NEW_ORDERS_DISABLED")
        if snap.execution_mode != str(required_mode).upper():
            raise ControlPlaneBlocked(
                f"MODE_MISMATCH:db={snap.execution_mode}:runtime={str(required_mode).upper()}"
            )

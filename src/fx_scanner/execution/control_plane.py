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


class ControlPlaneRefreshWorker:
    """Isolated periodic Supabase refresh worker.

    Network failures are contained. The last good cache is retained; once it
    exceeds ControlPlaneGate.max_age_seconds, live execution fails closed.
    """

    def __init__(self, store: SupabaseOperationalStore, gate: ControlPlaneGate, *, interval_seconds: float = 2.0):
        from threading import Event, Thread

        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        self.store = store
        self.gate = gate
        self.interval_seconds = float(interval_seconds)
        self._Event = Event
        self._Thread = Thread
        self._stop = Event()
        self._thread = None
        self.last_error: str | None = None
        self.refresh_count = 0
        self.failure_count = 0

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def refresh_once(self) -> None:
        try:
            self.gate.refresh(self.store)
            self.refresh_count += 1
            self.last_error = None
        except Exception as exc:
            self.failure_count += 1
            self.last_error = f"{type(exc).__name__}: {exc}"

    def _run(self) -> None:
        from time import monotonic

        deadline = monotonic()
        while not self._stop.is_set():
            now = monotonic()
            if now >= deadline:
                self.refresh_once()
                deadline = now + self.interval_seconds
            self._stop.wait(timeout=min(0.25, max(0.0, deadline - monotonic())))

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._thread = self._Thread(target=self._run, name="fx-control-plane-refresh", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            if self._thread.is_alive():
                raise RuntimeError("CONTROL_PLANE_WORKER_STOP_TIMEOUT")

    def health(self) -> dict[str, object]:
        return {
            "running": self.running,
            "refresh_count": self.refresh_count,
            "failure_count": self.failure_count,
            "last_error": self.last_error,
            "cache_present": self.gate.snapshot() is not None,
        }

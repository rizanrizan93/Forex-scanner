from __future__ import annotations

from queue import Empty, Full, Queue
from threading import Event, Thread
from typing import Any


class AsyncOperationalAudit:
    """Best-effort Supabase audit writer isolated from the order critical path."""

    def __init__(self, store, *, maxsize: int = 1000, poll_seconds: float = 0.25):
        if maxsize <= 0 or poll_seconds <= 0:
            raise ValueError("invalid audit worker configuration")
        self.store = store
        self.queue: Queue[dict[str, Any]] = Queue(maxsize=maxsize)
        self.poll_seconds = float(poll_seconds)
        self._stop = Event()
        self._thread: Thread | None = None
        self.written = 0
        self.dropped = 0
        self.failures = 0
        self.last_error: str | None = None

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def emit(self, event: dict[str, Any]) -> bool:
        try:
            self.queue.put_nowait(dict(event))
            return True
        except Full:
            self.dropped += 1
            return False

    def _run(self) -> None:
        while not self._stop.is_set() or not self.queue.empty():
            try:
                event = self.queue.get(timeout=self.poll_seconds)
            except Empty:
                continue
            try:
                self.store.record_order_event(**event)
                self.written += 1
                self.last_error = None
            except Exception as exc:
                self.failures += 1
                self.last_error = f"{type(exc).__name__}: {exc}"
            finally:
                self.queue.task_done()

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._thread = Thread(target=self._run, name="fx-supabase-audit", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            if self._thread.is_alive():
                raise RuntimeError("AUDIT_WORKER_STOP_TIMEOUT")

    def health(self) -> dict[str, Any]:
        return {
            "running": self.running,
            "queued": self.queue.qsize(),
            "written": self.written,
            "dropped": self.dropped,
            "failures": self.failures,
            "last_error": self.last_error,
        }

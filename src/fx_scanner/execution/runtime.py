from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from enum import StrEnum
from queue import Empty, Full, Queue
from threading import Event, Lock, Thread
from time import monotonic
from typing import Any, Callable


class CircuitState(StrEnum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


@dataclass(frozen=True, slots=True)
class BackoffPolicy:
    initial_seconds: float = 1.0
    multiplier: float = 2.0
    max_seconds: float = 30.0

    def delay(self, failure_count: int) -> float:
        if failure_count <= 0:
            return 0.0
        return min(self.initial_seconds * (self.multiplier ** (failure_count - 1)), self.max_seconds)


@dataclass(slots=True)
class CircuitBreaker:
    failure_threshold: int = 3
    recovery_seconds: float = 30.0
    state: CircuitState = CircuitState.CLOSED
    consecutive_failures: int = 0
    opened_at: float | None = None

    def allow(self, now_mono: float | None = None) -> bool:
        now_mono = monotonic() if now_mono is None else now_mono
        if self.state == CircuitState.CLOSED:
            return True
        if self.state == CircuitState.OPEN:
            if self.opened_at is not None and now_mono - self.opened_at >= self.recovery_seconds:
                self.state = CircuitState.HALF_OPEN
                return True
            return False
        return True

    def record_success(self) -> None:
        self.consecutive_failures = 0
        self.opened_at = None
        self.state = CircuitState.CLOSED

    def record_failure(self, now_mono: float | None = None) -> None:
        now_mono = monotonic() if now_mono is None else now_mono
        self.consecutive_failures += 1
        if self.state == CircuitState.HALF_OPEN or self.consecutive_failures >= self.failure_threshold:
            self.state = CircuitState.OPEN
            self.opened_at = now_mono


@dataclass(frozen=True, slots=True)
class JobRunResult:
    name: str
    status: str
    lag_seconds: float
    duration_seconds: float
    error: str | None = None


@dataclass(slots=True)
class ScheduledJob:
    name: str
    interval_seconds: float
    max_lag_seconds: float
    handler: Callable[[], Any]
    next_deadline: float | None = None
    lock: Lock = field(default_factory=Lock)
    runs: int = 0
    skipped_overlap: int = 0
    skipped_lag: int = 0
    failures: int = 0
    last_error: str | None = None
    last_duration_seconds: float = 0.0
    last_lag_seconds: float = 0.0
    last_status: str | None = None

    def arm(self, now_mono: float) -> None:
        if self.next_deadline is None:
            self.next_deadline = now_mono

    def is_due(self, now_mono: float) -> bool:
        self.arm(now_mono)
        assert self.next_deadline is not None
        return now_mono >= self.next_deadline

    def _advance_deadline(self, now_mono: float) -> None:
        self.next_deadline = now_mono + self.interval_seconds

    def _advance_after_run(self, deadline: float, now_mono: float, duration_seconds: float) -> None:
        finished = now_mono + duration_seconds
        nominal_next = deadline + self.interval_seconds
        self.next_deadline = nominal_next if finished <= nominal_next else finished + self.interval_seconds

    def run_due(self, now_mono: float | None = None) -> JobRunResult | None:
        now_mono = monotonic() if now_mono is None else now_mono
        if not self.is_due(now_mono):
            return None
        assert self.next_deadline is not None
        deadline = self.next_deadline
        lag = max(0.0, now_mono - deadline)
        self.last_lag_seconds = lag

        if lag > self.max_lag_seconds:
            self.skipped_lag += 1
            self.last_status = "SKIPPED_LAG"
            self._advance_deadline(now_mono)
            return JobRunResult(self.name, "SKIPPED_LAG", lag, 0.0)

        if not self.lock.acquire(blocking=False):
            self.skipped_overlap += 1
            self.last_status = "SKIPPED_OVERLAP"
            self._advance_deadline(now_mono)
            return JobRunResult(self.name, "SKIPPED_OVERLAP", lag, 0.0)

        started = monotonic()
        try:
            self.handler()
            duration = monotonic() - started
            self.runs += 1
            self.last_duration_seconds = duration
            self.last_error = None
            self.last_status = "OK"
            return JobRunResult(self.name, "OK", lag, duration)
        except Exception as exc:
            duration = monotonic() - started
            self.failures += 1
            self.last_duration_seconds = duration
            self.last_error = f"{type(exc).__name__}: {exc}"
            self.last_status = "ERROR"
            return JobRunResult(self.name, "ERROR", lag, duration, self.last_error)
        finally:
            self.lock.release()
            self._advance_after_run(deadline, now_mono, self.last_duration_seconds)


@dataclass(frozen=True, slots=True)
class RuntimeHealth:
    healthy: bool
    job_status: dict[str, dict[str, Any]]
    recent_results: tuple[JobRunResult, ...]


class RuntimeSupervisor:
    def __init__(self, history_size: int = 100):
        self.jobs: dict[str, ScheduledJob] = {}
        self.history: deque[JobRunResult] = deque(maxlen=history_size)

    def add_job(self, job: ScheduledJob) -> None:
        if job.name in self.jobs:
            raise ValueError(f"duplicate job name: {job.name}")
        if job.interval_seconds <= 0 or job.max_lag_seconds < 0:
            raise ValueError("invalid scheduler interval/lag")
        self.jobs[job.name] = job

    def tick(self, now_mono: float | None = None) -> tuple[JobRunResult, ...]:
        now_mono = monotonic() if now_mono is None else now_mono
        results: list[JobRunResult] = []
        for job in self.jobs.values():
            result = job.run_due(now_mono)
            if result is not None:
                self.history.append(result)
                results.append(result)
        return tuple(results)

    def health(self) -> RuntimeHealth:
        status: dict[str, dict[str, Any]] = {}
        healthy = True
        for name, job in self.jobs.items():
            status[name] = {
                "runs": job.runs,
                "failures": job.failures,
                "skipped_overlap": job.skipped_overlap,
                "skipped_lag": job.skipped_lag,
                "last_error": job.last_error,
                "last_duration_seconds": job.last_duration_seconds,
                "last_lag_seconds": job.last_lag_seconds,
                "last_status": job.last_status,
                "next_deadline": job.next_deadline,
            }
            if job.last_status in {"ERROR", "SKIPPED_LAG", "SKIPPED_OVERLAP"}:
                healthy = False
        return RuntimeHealth(healthy, status, tuple(self.history))


@dataclass(frozen=True, slots=True)
class QueueResult:
    item_id: str
    status: str
    value: Any = None
    error: str | None = None


class SerializedExecutionQueue:
    def __init__(self, maxsize: int = 100):
        self._queue: Queue[tuple[str, Any]] = Queue(maxsize=maxsize)
        self._processing_lock = Lock()

    @property
    def size(self) -> int:
        return self._queue.qsize()

    def submit(self, item_id: str, payload: Any) -> None:
        try:
            self._queue.put_nowait((item_id, payload))
        except Full as exc:
            raise RuntimeError("EXECUTION_QUEUE_FULL") from exc

    def process_one(self, handler: Callable[[Any], Any]) -> QueueResult | None:
        if not self._processing_lock.acquire(blocking=False):
            return QueueResult("", "BUSY")
        try:
            try:
                item_id, payload = self._queue.get_nowait()
            except Empty:
                return None
            try:
                value = handler(payload)
                return QueueResult(item_id, "OK", value=value)
            except Exception as exc:
                return QueueResult(item_id, "ERROR", error=f"{type(exc).__name__}: {exc}")
            finally:
                self._queue.task_done()
        finally:
            self._processing_lock.release()

    def process_one_blocking(self, handler: Callable[[Any], Any], timeout: float = 0.5) -> QueueResult | None:
        if not self._processing_lock.acquire(blocking=False):
            return QueueResult("", "BUSY")
        try:
            try:
                item_id, payload = self._queue.get(timeout=timeout)
            except Empty:
                return None
            try:
                value = handler(payload)
                return QueueResult(item_id, "OK", value=value)
            except Exception as exc:
                return QueueResult(item_id, "ERROR", error=f"{type(exc).__name__}: {exc}")
            finally:
                self._queue.task_done()
        finally:
            self._processing_lock.release()


class ExecutionQueueWorker:
    def __init__(self, queue: SerializedExecutionQueue, handler: Callable[[Any], Any], *, poll_seconds: float = 0.25, history_size: int = 100):
        if poll_seconds <= 0:
            raise ValueError("poll_seconds must be positive")
        self.queue = queue
        self.handler = handler
        self.poll_seconds = poll_seconds
        self.history: deque[QueueResult] = deque(maxlen=history_size)
        self._stop = Event()
        self._thread: Thread | None = None
        self.current_item_id: str | None = None
        self.busy_since: float | None = None
        self.completed_count = 0
        self.error_count = 0

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._thread = Thread(target=self._run, name="fx-execution-worker", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            self.busy_since = monotonic()
            result = self.queue.process_one_blocking(self.handler, timeout=self.poll_seconds)
            self.busy_since = None
            if result is not None and result.status != "BUSY":
                self.current_item_id = result.item_id
                self.history.append(result)
                self.completed_count += 1
                if result.status == "ERROR":
                    self.error_count += 1
                self.current_item_id = None

    def health(self, max_busy_seconds: float = 10.0) -> dict[str, Any]:
        busy_seconds = 0.0 if self.busy_since is None else max(0.0, monotonic() - self.busy_since)
        return {
            "running": self.running,
            "queue_size": self.queue.size,
            "busy_seconds": busy_seconds,
            "stuck": busy_seconds > max_busy_seconds,
            "completed_count": self.completed_count,
            "error_count": self.error_count,
            "current_item_id": self.current_item_id,
        }

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            if self._thread.is_alive():
                raise RuntimeError("EXECUTION_WORKER_STOP_TIMEOUT")


class ConcurrentRuntimeSupervisor:
    def __init__(self, max_workers: int = 4, history_size: int = 100):
        if max_workers <= 0:
            raise ValueError("max_workers must be positive")
        from concurrent.futures import ThreadPoolExecutor
        self.jobs: dict[str, ScheduledJob] = {}
        self.history: deque[JobRunResult] = deque(maxlen=history_size)
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="fx-runtime")
        self._pending: dict[str, Any] = {}
        self._closed = False

    def add_job(self, job: ScheduledJob) -> None:
        if self._closed:
            raise RuntimeError("supervisor is closed")
        if job.name in self.jobs:
            raise ValueError(f"duplicate job name: {job.name}")
        if job.interval_seconds <= 0 or job.max_lag_seconds < 0:
            raise ValueError("invalid scheduler interval/lag")
        self.jobs[job.name] = job

    def collect_completed(self) -> tuple[JobRunResult, ...]:
        completed: list[JobRunResult] = []
        for name, future in list(self._pending.items()):
            if not future.done():
                continue
            del self._pending[name]
            try:
                result = future.result()
            except Exception as exc:
                result = JobRunResult(name, "SUPERVISOR_ERROR", 0.0, 0.0, f"{type(exc).__name__}: {exc}")
            if result is not None:
                self.history.append(result)
                completed.append(result)
        return tuple(completed)

    def tick(self, now_mono: float | None = None) -> tuple[JobRunResult, ...]:
        if self._closed:
            raise RuntimeError("supervisor is closed")
        now_mono = monotonic() if now_mono is None else now_mono
        completed = list(self.collect_completed())
        for name, job in self.jobs.items():
            if name in self._pending:
                continue
            if job.is_due(now_mono):
                self._pending[name] = self._executor.submit(job.run_due, now_mono)
        return tuple(completed)

    def health(self) -> RuntimeHealth:
        self.collect_completed()
        status: dict[str, dict[str, Any]] = {}
        healthy = True
        for name, job in self.jobs.items():
            status[name] = {
                "runs": job.runs,
                "failures": job.failures,
                "skipped_overlap": job.skipped_overlap,
                "skipped_lag": job.skipped_lag,
                "last_error": job.last_error,
                "last_duration_seconds": job.last_duration_seconds,
                "last_lag_seconds": job.last_lag_seconds,
                "last_status": job.last_status,
                "next_deadline": job.next_deadline,
                "running": name in self._pending,
            }
            if job.last_status in {"ERROR", "SKIPPED_LAG", "SKIPPED_OVERLAP"}:
                healthy = False
        return RuntimeHealth(healthy, status, tuple(self.history))

    def shutdown(self, wait: bool = True) -> tuple[JobRunResult, ...]:
        if self._closed:
            return self.collect_completed()
        self._executor.shutdown(wait=wait, cancel_futures=not wait)
        self._closed = True
        return self.collect_completed()

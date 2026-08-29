from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .models import OrderIntent, OrderReceipt
from .policy import ExecutionPolicy
from .runtime import ConcurrentRuntimeSupervisor, ExecutionQueueWorker, RuntimeHealth, SerializedExecutionQueue
from .scheduler import build_runtime_job


@dataclass(frozen=True, slots=True)
class RuntimeHandlers:
    heavy_scan: Callable[[], Any]
    fast_setup: Callable[[], Any]
    execution_watch: Callable[[], Any]
    position_monitor: Callable[[], Any]


class TradingRuntimeService:
    """Wires the four cadence tiers and the serialized execution queue.

    The handlers are intentionally dependency-injected. Strategy logic is not
    implemented in v0.3, so runtime hardening can be validated independently.
    """

    def __init__(self, policy: ExecutionPolicy, router, handlers: RuntimeHandlers):
        self.policy = policy
        self.router = router
        self.queue = SerializedExecutionQueue(
            maxsize=int(policy.runtime.get("execution_queue_maxsize", 100))
        )
        self.supervisor = ConcurrentRuntimeSupervisor(max_workers=int(policy.runtime.get("concurrent_workers", 4)))

        def execute_payload(payload: tuple[OrderIntent, bool]) -> OrderReceipt:
            intent, user_confirmed = payload
            return self.router.execute(intent, user_confirmed=user_confirmed)

        self._execute_payload = execute_payload
        self.execution_worker = ExecutionQueueWorker(
            self.queue,
            self._execute_payload,
            poll_seconds=float(policy.runtime.get("execution_worker_poll_seconds", 0.25)),
        )
        lag = policy.runtime.get("max_lag_seconds", {})
        scheduler = policy.scheduler
        self.supervisor.add_job(build_runtime_job(
            "heavy_scan",
            scheduler["heavy_scan_seconds"],
            int(lag.get("heavy_scan", 120)),
            handlers.heavy_scan,
        ))
        self.supervisor.add_job(build_runtime_job(
            "fast_setup",
            scheduler["fast_setup_seconds"],
            int(lag.get("fast_setup", 15)),
            handlers.fast_setup,
        ))
        self.supervisor.add_job(build_runtime_job(
            "execution_watch",
            scheduler["execution_watch_seconds"],
            int(lag.get("execution_watch", 3)),
            handlers.execution_watch,
        ))
        self.supervisor.add_job(build_runtime_job(
            "position_monitor",
            scheduler["position_monitor_seconds"],
            int(lag.get("position_monitor", 3)),
            handlers.position_monitor,
        ))

    def submit_order(self, intent: OrderIntent, *, user_confirmed: bool = False) -> None:
        self.queue.submit(intent.signal_id, (intent, user_confirmed))

    def process_one_order(self):
        return self.queue.process_one(self._execute_payload)

    def start_execution_worker(self) -> None:
        self.execution_worker.start()

    def stop_execution_worker(self) -> None:
        self.execution_worker.stop()

    def tick(self, now_mono: float | None = None):
        return self.supervisor.tick(now_mono)

    def collect_completed(self):
        return self.supervisor.collect_completed()

    def shutdown(self, wait: bool = True):
        if self.execution_worker.running:
            self.execution_worker.stop()
        return self.supervisor.shutdown(wait=wait)

    def health(self) -> RuntimeHealth:
        return self.supervisor.health()

    def full_health(self, *, max_execution_busy_seconds: float = 10.0) -> dict[str, Any]:
        supervisor = self.supervisor.health()
        worker = self.execution_worker.health(max_busy_seconds=max_execution_busy_seconds)
        return {
            "healthy": bool(supervisor.healthy and not worker["stuck"]),
            "supervisor": supervisor,
            "execution_worker": worker,
        }

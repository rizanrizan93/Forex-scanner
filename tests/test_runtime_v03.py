from __future__ import annotations

from types import SimpleNamespace

import pytest

from fx_scanner.exceptions import CollectorUnavailable
from fx_scanner.execution.mt5_session import PersistentMT5Session
from fx_scanner.execution.policy import load_execution_policy
from fx_scanner.execution.runtime import (
    BackoffPolicy,
    CircuitBreaker,
    CircuitState,
    RuntimeSupervisor,
    ScheduledJob,
    SerializedExecutionQueue,
)


def test_v03_runtime_config_is_present_and_safe():
    policy = load_execution_policy()
    assert policy.mode.value == "DISABLED"
    assert policy.runtime["max_lag_seconds"]["execution_watch"] == 0.5
    assert policy.scheduler["execution_watch_seconds"] == 0.25
    assert policy.runtime["execution_queue_maxsize"] == 100
    assert policy.runtime["concurrent_workers"] == 4
    assert policy.runtime["circuit_breaker"]["failure_threshold"] == 3


def test_scheduled_job_skips_late_cycle_without_catchup():
    calls = []
    job = ScheduledJob("execution", 2.0, 3.0, lambda: calls.append(1))
    job.arm(100.0)
    result = job.run_due(104.0)
    assert result is not None and result.status == "SKIPPED_LAG"
    assert calls == []
    assert job.next_deadline == 106.0
    assert job.skipped_lag == 1


def test_scheduled_job_skips_overlap():
    job = ScheduledJob("position", 2.0, 3.0, lambda: None)
    job.arm(100.0)
    assert job.lock.acquire(blocking=False)
    try:
        result = job.run_due(100.0)
    finally:
        job.lock.release()
    assert result is not None and result.status == "SKIPPED_OVERLAP"
    assert job.skipped_overlap == 1


def test_supervisor_contains_job_exception_and_runs_other_jobs():
    calls = []
    supervisor = RuntimeSupervisor()
    supervisor.add_job(ScheduledJob("bad", 10, 1, lambda: (_ for _ in ()).throw(RuntimeError("boom"))))
    supervisor.add_job(ScheduledJob("good", 10, 1, lambda: calls.append("good")))
    results = supervisor.tick(50.0)
    assert [r.status for r in results] == ["ERROR", "OK"]
    assert calls == ["good"]
    assert supervisor.health().healthy is False


def test_no_catchup_storm_after_long_pause():
    count = 0

    def handler():
        nonlocal count
        count += 1

    supervisor = RuntimeSupervisor()
    job = ScheduledJob("fast", 2, 3, handler)
    supervisor.add_job(job)
    supervisor.tick(0.0)
    assert count == 1
    results = supervisor.tick(100.0)
    assert len(results) == 1 and results[0].status == "SKIPPED_LAG"
    assert count == 1
    assert job.next_deadline == 102.0


def test_execution_queue_is_fifo_and_serialized():
    queue = SerializedExecutionQueue(maxsize=3)
    queue.submit("A", 1)
    queue.submit("B", 2)
    r1 = queue.process_one(lambda x: x * 10)
    r2 = queue.process_one(lambda x: x * 10)
    assert (r1.item_id, r1.value) == ("A", 10)
    assert (r2.item_id, r2.value) == ("B", 20)


def test_execution_queue_backpressure():
    queue = SerializedExecutionQueue(maxsize=1)
    queue.submit("A", 1)
    with pytest.raises(RuntimeError, match="EXECUTION_QUEUE_FULL"):
        queue.submit("B", 2)


def test_circuit_breaker_opens_and_half_opens():
    breaker = CircuitBreaker(failure_threshold=3, recovery_seconds=30)
    breaker.record_failure(10)
    breaker.record_failure(11)
    assert breaker.state == CircuitState.CLOSED
    breaker.record_failure(12)
    assert breaker.state == CircuitState.OPEN
    assert not breaker.allow(20)
    assert breaker.allow(42)
    assert breaker.state == CircuitState.HALF_OPEN
    breaker.record_success()
    assert breaker.state == CircuitState.CLOSED


def test_backoff_is_bounded():
    policy = BackoffPolicy(initial_seconds=1, multiplier=2, max_seconds=10)
    assert [policy.delay(x) for x in range(1, 7)] == [1, 2, 4, 8, 10, 10]


class FakeGateway:
    def __init__(self, fail_connects=0):
        self.connected = False
        self.fail_connects = fail_connects
        self.connect_calls = 0
        self.close_calls = 0

    def connect(self):
        self.connect_calls += 1
        if self.connect_calls <= self.fail_connects:
            raise CollectorUnavailable("connect fail")
        self.connected = True

    def close(self):
        self.close_calls += 1
        self.connected = False

    def terminal_health(self):
        return self.connected

    def account_snapshot(self):
        if not self.connected:
            raise CollectorUnavailable("not connected")
        return SimpleNamespace(login=12345)


def test_persistent_mt5_session_reconnects_with_backoff():
    gateway = FakeGateway(fail_connects=1)
    sleeps = []
    session = PersistentMT5Session(
        gateway,
        backoff=BackoffPolicy(1, 2, 10),
        circuit_breaker=CircuitBreaker(3, 30),
        sleeper=sleeps.append,
    )
    session.ensure_connected(now_mono=100, max_attempts=3)
    assert gateway.connected
    assert gateway.connect_calls == 2
    assert sleeps == [1]
    assert session.breaker.state == CircuitState.CLOSED


def test_persistent_mt5_session_circuit_opens_after_repeated_failure():
    gateway = FakeGateway(fail_connects=99)
    session = PersistentMT5Session(
        gateway,
        circuit_breaker=CircuitBreaker(2, 30),
        sleeper=lambda _: None,
    )
    with pytest.raises(CollectorUnavailable, match="MT5_RECONNECT_FAILED"):
        session.ensure_connected(now_mono=100, max_attempts=3)
    assert session.breaker.state == CircuitState.OPEN
    with pytest.raises(CollectorUnavailable, match="MT5_CIRCUIT_OPEN"):
        session.ensure_connected(now_mono=110, max_attempts=1)


def test_health_recovers_after_transient_job_error():
    state = {"fail": True}

    def handler():
        if state["fail"]:
            raise RuntimeError("temporary")

    supervisor = RuntimeSupervisor()
    job = ScheduledJob("watch", 2, 3, handler)
    supervisor.add_job(job)
    supervisor.tick(0)
    assert supervisor.health().healthy is False
    state["fail"] = False
    supervisor.tick(2)
    assert supervisor.health().healthy is True
    assert job.failures == 1


def test_slow_job_waits_full_interval_after_completion(monkeypatch):
    times = iter([100.0, 105.0])
    monkeypatch.setattr("fx_scanner.execution.runtime.monotonic", lambda: next(times))
    job = ScheduledJob("slow", 2, 3, lambda: None)
    job.arm(100.0)
    result = job.run_due(100.0)
    assert result.status == "OK"
    assert result.duration_seconds == 5.0
    assert job.next_deadline == 107.0


def test_concurrent_supervisor_prevents_heavy_job_from_blocking_fast_job():
    from threading import Event
    from fx_scanner.execution.runtime import ConcurrentRuntimeSupervisor

    heavy_started = Event()
    release_heavy = Event()
    fast_ran = Event()

    def heavy():
        heavy_started.set()
        assert release_heavy.wait(timeout=1.0)

    def fast():
        fast_ran.set()

    supervisor = ConcurrentRuntimeSupervisor(max_workers=2)
    supervisor.add_job(ScheduledJob("heavy", 900, 120, heavy))
    supervisor.add_job(ScheduledJob("fast", 2, 3, fast))
    supervisor.tick(0.0)
    assert heavy_started.wait(timeout=0.5)
    assert fast_ran.wait(timeout=0.5)
    release_heavy.set()
    supervisor.shutdown(wait=True)


def test_execution_worker_contains_item_error_and_continues():
    from time import sleep
    from fx_scanner.execution.runtime import ExecutionQueueWorker

    queue = SerializedExecutionQueue(maxsize=4)
    queue.submit("bad", "bad")
    queue.submit("good", "good")

    def handler(value):
        if value == "bad":
            raise RuntimeError("boom")
        return value.upper()

    worker = ExecutionQueueWorker(queue, handler, poll_seconds=0.01)
    worker.start()
    for _ in range(100):
        if len(worker.history) >= 2:
            break
        sleep(0.005)
    worker.stop()
    assert [r.item_id for r in worker.history] == ["bad", "good"]
    assert [r.status for r in worker.history] == ["ERROR", "OK"]
    assert worker.history[-1].value == "GOOD"

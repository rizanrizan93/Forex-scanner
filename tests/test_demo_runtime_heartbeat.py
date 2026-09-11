import pytest

from fx_scanner import demo_runtime_heartbeat as runtime


class Store:
    def __init__(self):
        self.calls = []

    def write_heartbeat(self, worker_name, *, healthy, lag_seconds, details):
        self.calls.append((worker_name, healthy, lag_seconds, details))


def test_runtime_heartbeat_records_failure_without_live_authority(monkeypatch):
    store = Store()
    monkeypatch.setattr(runtime.SupabaseOperationalStore, "from_env", lambda: store)
    monkeypatch.setenv("GITHUB_SHA", "abc123")
    monkeypatch.setenv("GITHUB_RUN_ID", "42")

    runtime.record_runtime_heartbeat("ctrader_demo_auto_pipeline", "FAILED")

    worker, healthy, lag, details = store.calls[0]
    assert worker == "ctrader_demo_auto_pipeline"
    assert healthy is False
    assert lag == 0.0
    assert details["environment"] == "DEMO"
    assert details["live_unlock"] is False
    assert details["git_sha"] == "abc123"


@pytest.mark.parametrize("worker,status", [("bad-worker", "SUCCESS"), ("ok_worker", "UNKNOWN")])
def test_runtime_heartbeat_rejects_unbounded_identity_or_status(monkeypatch, worker, status):
    monkeypatch.setattr(
        runtime.SupabaseOperationalStore,
        "from_env",
        lambda: (_ for _ in ()).throw(AssertionError("must fail before persistence")),
    )
    with pytest.raises(ValueError):
        runtime.record_runtime_heartbeat(worker, status)

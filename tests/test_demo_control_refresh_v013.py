from types import SimpleNamespace

from fx_scanner.execution.control_plane import ControlPlaneGate, ControlPlaneRefreshWorker


class Store:
    def __init__(self):
        self.calls = 0

    def get_execution_control(self):
        self.calls += 1
        return SimpleNamespace(
            emergency_stop=False,
            new_orders_enabled=True,
            execution_mode="AUTO",
        )


def test_control_refresh_worker_keeps_auto_gate_fresh():
    now = [0.0]
    gate = ControlPlaneGate(max_age_seconds=5.0, clock=lambda: now[0])
    store = Store()
    worker = ControlPlaneRefreshWorker(store, gate, interval_seconds=1.0)
    worker.refresh_once()
    gate.assert_orders_allowed("AUTO")
    now[0] = 4.9
    gate.assert_orders_allowed("AUTO")
    worker.refresh_once()
    now[0] = 9.8
    gate.assert_orders_allowed("AUTO")
    assert store.calls == 2

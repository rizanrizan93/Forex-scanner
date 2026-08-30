from datetime import datetime, timezone

import pytest

from fx_scanner.execution.control_plane import (
    ControlPlaneBlocked,
    ControlPlaneGate,
    ControlPlaneRefreshWorker,
)
from fx_scanner.storage.supabase_operational import ExecutionControlSnapshot

UTC = timezone.utc


class Store:
    def __init__(self, state):
        self.state = state
        self.fail = False

    def get_execution_control(self):
        if self.fail:
            raise RuntimeError("db unavailable")
        return self.state


def snap(mode="AUTO", enabled=True, emergency=False):
    return ExecutionControlSnapshot(
        control_key="primary",
        execution_mode=mode,
        new_orders_enabled=enabled,
        emergency_stop=emergency,
        close_all_requested=False,
        version=2,
        updated_at=datetime.now(tz=UTC),
    )


def test_missing_cache_blocks():
    now = [100.0]
    gate = ControlPlaneGate(max_age_seconds=5, clock=lambda: now[0])
    with pytest.raises(ControlPlaneBlocked, match="MISSING"):
        gate.assert_orders_allowed("AUTO")


def test_emergency_stop_blocks():
    now = [100.0]
    gate = ControlPlaneGate(max_age_seconds=5, clock=lambda: now[0])
    gate.refresh(Store(snap(emergency=True)))
    with pytest.raises(ControlPlaneBlocked, match="EMERGENCY_STOP"):
        gate.assert_orders_allowed("AUTO")


def test_enabled_matching_mode_passes_and_stale_blocks():
    now = [100.0]
    gate = ControlPlaneGate(max_age_seconds=5, clock=lambda: now[0])
    gate.refresh(Store(snap()))
    gate.assert_orders_allowed("AUTO")
    now[0] = 106.0
    with pytest.raises(ControlPlaneBlocked, match="STALE"):
        gate.assert_orders_allowed("AUTO")


def test_mode_mismatch_blocks():
    gate = ControlPlaneGate(max_age_seconds=5, clock=lambda: 100.0)
    gate.refresh(Store(snap(mode="CONFIRM_TO_TRADE")))
    with pytest.raises(ControlPlaneBlocked, match="MODE_MISMATCH"):
        gate.assert_orders_allowed("AUTO")


def test_refresh_failure_keeps_last_good_cache_until_it_ages_out():
    now = [100.0]
    state = snap()
    store = Store(state)
    gate = ControlPlaneGate(max_age_seconds=5, clock=lambda: now[0])
    worker = ControlPlaneRefreshWorker(store, gate, interval_seconds=2)
    worker.refresh_once()
    assert worker.refresh_count == 1
    store.fail = True
    worker.refresh_once()
    assert worker.failure_count == 1
    gate.assert_orders_allowed("AUTO")
    now[0] = 106.0
    with pytest.raises(ControlPlaneBlocked, match="STALE"):
        gate.assert_orders_allowed("AUTO")

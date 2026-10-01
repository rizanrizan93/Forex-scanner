from __future__ import annotations

import sys
from datetime import UTC, datetime
from types import SimpleNamespace

from fx_scanner.execution.control_plane import ExecutionControlSnapshot


def test_v330_decision_center_reads_exactly_one_latest_row_per_worker():
    from fx_scanner.demo_xau_decision_center_v296 import (
        ENGINE_SPECS,
        SUPPORT_WORKERS,
        _latest_heartbeats,
    )

    calls = []

    class Query:
        def __init__(self):
            self.worker = None
            self.limit_n = None
        def table(self, name):
            assert name == "runtime_heartbeats"
            return self
        def select(self, fields):
            assert fields == "worker_name,observed_at,healthy,details"
            return self
        def eq(self, field, value):
            assert field == "worker_name"
            self.worker = value
            return self
        def order(self, field, desc=False):
            assert field == "observed_at"
            assert desc is True
            return self
        def limit(self, n):
            self.limit_n = n
            return self
        def execute(self):
            calls.append((self.worker, self.limit_n))
            return SimpleNamespace(data=[{
                "worker_name": self.worker,
                "observed_at": "2026-10-01T08:00:00+00:00",
                "healthy": True,
                "details": {"worker": self.worker},
            }])

    store = SimpleNamespace(client=Query())
    out = _latest_heartbeats(store)
    expected = tuple(dict.fromkeys(
        [spec["worker"] for spec in ENGINE_SPECS.values()]
        + list(SUPPORT_WORKERS)
    ))
    assert set(out) == set(expected)
    assert len(calls) == len(expected)
    assert all(limit_n == 1 for _, limit_n in calls)
    assert [worker for worker, _ in calls] == list(expected)


def test_v330_bridge_reuses_cached_atlas_when_operational_projection_times_out(
    monkeypatch,
):
    from fx_scanner import xau_dashboard_bridge_v254 as bridge

    now = datetime(2026, 10, 1, 8, 20, tzinfo=UTC)
    previous = {
        "contract": bridge.CONTRACT,
        "as_of": now.isoformat(),
        "source": {
            "structural_as_of": now.isoformat(),
            "support_as_of": now.isoformat(),
            "cold_as_of": now.isoformat(),
            "outcomes_as_of": now.isoformat(),
            "egress_budget": {
                "structural_payload_bytes": 1,
                "support_payload_bytes": 1,
                "cold_payload_bytes": 1,
                "outcome_payload_bytes": 1,
            },
        },
        "backend": {
            "heartbeats": [{
                "worker_name": "ctrader_demo_xau_supply_demand_atlas_v182",
                "observed_at": "2026-10-01T08:19:00+00:00",
                "healthy": True,
                "details": {
                    "evaluation": {
                        "last_closed_m15_price": 4150.0,
                        "state": "ATLAS_AVAILABLE",
                    }
                },
            }],
            "latest_run": None,
            "rankings": [],
            "signals": [],
            "macro": [],
            "performance": [],
            "xau_outcomes": [],
            "xau_signals": [],
            "afic_forecast_states": [],
            "afic_prepared_plans": [],
            "afic_execution_geometry": [],
            "xau_execution_events": [],
            "xau_geometry_events": [],
            "xau_prepared_plan_lifecycle": [],
            "control": {},
        },
    }

    class Reader:
        def __init__(self, *_args):
            pass
        def heartbeats_for_workers(self, *_args):
            return ()
        def latest_rizan_prepared_heartbeat(self):
            return None
        def latest_rizan_v229_execution_heartbeat(self):
            return None
        def latest_rizan_child_executor_heartbeat(self):
            return None
        def latest_xau_atlas_operational_heartbeat(self):
            raise RuntimeError("statement timeout")
        def latest_xau_v226_operational_heartbeat(self):
            return None
        def latest_signals_for_symbol(self, *_args, **_kwargs):
            return ()
        def latest_afic_forecast_states(self, **_kwargs):
            return ()
        def latest_afic_prepared_plans(self, **_kwargs):
            return ()
        def latest_xau_geometry_events_compact(self, **_kwargs):
            return ()
        def latest_xau_execution_events(self, **_kwargs):
            return ()
        def latest_xau_prepared_plan_lifecycle(self, **_kwargs):
            return ()
        def latest_rizan_execution_geometry_compact(self, **_kwargs):
            return ()

    monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "test")
    monkeypatch.setitem(
        sys.modules,
        "supabase",
        SimpleNamespace(create_client=lambda *_args: None),
    )
    monkeypatch.setattr(bridge, "SupabaseDashboardReader", Reader)
    monkeypatch.setattr(
        bridge,
        "SupabaseOperationalStore",
        lambda *_args, **_kwargs: SimpleNamespace(
            get_execution_control=lambda: ExecutionControlSnapshot(
                control_key="primary",
                execution_mode="AUTO",
                new_orders_enabled=True,
                emergency_stop=False,
                close_all_requested=False,
                version=1,
                updated_at=now,
            )
        ),
    )

    out = bridge.build_snapshot(previous=previous, now=now)
    atlas_rows = [
        row for row in out["backend"]["heartbeats"]
        if row.get("worker_name") == "ctrader_demo_xau_supply_demand_atlas_v182"
    ]
    assert len(atlas_rows) == 1
    assert (
        atlas_rows[0]["details"]["evaluation"]["last_closed_m15_price"]
        == 4150.0
    )
    assert out["source"]["operational_read_degraded"] is True
    assert any(
        str(item).startswith("V182_OPERATIONAL:")
        for item in out["source"]["operational_read_errors"]
    )

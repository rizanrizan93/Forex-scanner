from datetime import UTC, datetime, timedelta
import gzip
import json

import pytest

from fx_scanner.xau_dashboard_bridge_v254 import fetch_snapshot, validate_snapshot


def _payload(as_of: datetime) -> dict:
    return {
        "contract": "XAU_RIZAN_DASHBOARD_BRIDGE_V254",
        "as_of": as_of.isoformat(),
        "backend": {
            "control": {},
            "heartbeats": [],
            "xau_signals": [],
            "afic_forecast_states": [],
            "afic_prepared_plans": [],
            "xau_execution_events": [],
            "xau_geometry_events": [],
        },
    }


def test_dashboard_bridge_rejects_stale_snapshot_by_default() -> None:
    now = datetime(2026, 9, 29, 0, 47, tzinfo=UTC)
    with pytest.raises(ValueError, match="snapshot stale"):
        validate_snapshot(_payload(now - timedelta(minutes=10)), now=now)


def test_dashboard_bridge_can_return_stale_snapshot_for_degraded_read_only_ui() -> None:
    now = datetime(2026, 9, 29, 0, 47, tzinfo=UTC)
    out = validate_snapshot(
        _payload(now - timedelta(minutes=10)),
        now=now,
        require_fresh=False,
    )
    assert out["bridge"]["fresh"] is False
    assert out["bridge"]["age_seconds"] == 600.0


def test_dashboard_bridge_fetch_accepts_gzip_large_transport() -> None:
    now = datetime(2026, 9, 29, 1, 0, tzinfo=UTC)
    payload = _payload(now)
    payload["source"] = {"project_ref": "naxvdtvlfatljzzwhrmo"}
    raw = gzip.compress(json.dumps(payload).encode("utf-8"))

    class Headers:
        def get(self, key):
            return "gzip" if key == "Content-Encoding" else None

    class Response:
        headers = Headers()

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, *_args):
            return raw

    seen = {}

    def opener(request, timeout):
        seen["timeout"] = timeout
        seen["accept_encoding"] = request.headers.get("Accept-encoding")
        return Response()

    out = fetch_snapshot(
        "https://example.invalid/dashboard.json",
        now=now,
        opener=opener,
    )
    assert out["bridge"]["fresh"] is True
    assert seen["timeout"] == 20.0
    assert str(seen["accept_encoding"]).lower() == "gzip"


def test_dashboard_bridge_bounds_minute_level_history_payload() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    text = (root / "src/fx_scanner/xau_dashboard_bridge_v254.py").read_text()
    assert 'latest_signals_for_symbol("XAUUSD", limit=8)' in text
    assert "latest_xau_geometry_events_compact(limit=2)" in text
    assert "latest_xau_execution_events(limit=4)" in text
    assert "latest_xau_prepared_plan_lifecycle(limit=4)" in text


def test_v259_bridge_refreshes_compact_operational_structure_each_minute() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    text = (root / "src/fx_scanner/xau_dashboard_bridge_v254.py").read_text()
    assert "latest_xau_atlas_operational_heartbeat()" in text
    assert "latest_xau_v226_operational_heartbeat()" in text
    assert "merge_runtime_heartbeat_rows" in text
    assert '"operational_structure_refresh_seconds": int(HOT_REFRESH_SECONDS)' in text


def test_v2592_bridge_keeps_one_dedicated_rizan_geometry_for_v240_parity() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    text = (root / "src/fx_scanner/xau_dashboard_bridge_v254.py").read_text()
    assert "latest_afic_forecast_states(limit=6)" in text
    assert "latest_rizan_execution_geometry_compact(limit=1)" in text
    assert '"afic_execution_geometry": rizan_geometry' in text


def test_v2593_geometry_hot_path_never_fetches_full_payload() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    bridge = (root / "src/fx_scanner/xau_dashboard_bridge_v254.py").read_text()
    dashboard = (root / "src/fx_scanner/dashboard.py").read_text()
    assert "latest_xau_geometry_events_compact(limit=2)" in bridge
    assert "latest_rizan_execution_geometry_compact(limit=1)" in bridge
    assert "def latest_xau_geometry_events_compact" in dashboard
    assert "def latest_rizan_execution_geometry_compact" in dashboard


def test_public_snapshot_strips_nested_private_account_fields():
    from fx_scanner.xau_dashboard_bridge_v254 import _sanitize
    payload = {"balance": 100, "heartbeats": [{"details": {"equity": 101, "margin_free": 99, "state": "WAIT"}}]}
    assert _sanitize(payload) == {"heartbeats": [{"details": {"state": "WAIT"}}]}


def test_bridge_does_not_read_or_republish_cached_private_account(monkeypatch):
    import sys
    from types import SimpleNamespace
    from fx_scanner import xau_dashboard_bridge_v254 as bridge
    from fx_scanner.execution.control_plane import ExecutionControlSnapshot

    now = datetime(2026, 9, 29, 3, tzinfo=UTC)
    previous = _payload(now)
    previous["source"] = {key: now.isoformat() for key in
                          ("structural_as_of", "support_as_of", "cold_as_of", "outcomes_as_of", "audit_as_of")}
    previous["source"]["egress_budget"] = {"audit_payload_bytes": 20000}
    previous["backend"]["heartbeats"] = [{"worker_name": "test"}]
    previous["backend"]["broker_account"] = {"balance": 999}
    previous["backend"]["broker_positions"] = [{"position_id": "private"}]
    previous["backend"]["xau_geometry_events"] = [{"code": "XAU_RIZAN_DEPTH_EXECUTION_V1"}]

    class Reader:
        def __init__(self, *_): pass
        def heartbeats_for_workers(self, *_): return ()
        def latest_rizan_prepared_heartbeat(self): return None
        def latest_rizan_v229_execution_heartbeat(self): return None
        def latest_rizan_child_executor_heartbeat(self): return None
        def latest_signals_for_symbol(self, *_, **kw): return ()
        def latest_afic_forecast_states(self, **kw): return ()
        def latest_afic_prepared_plans(self, **kw): return ()
        def latest_broker_account(self): raise AssertionError("private read")
        def latest_xau_geometry_events_compact(self, **kw): return ()
        def latest_xau_execution_events(self, **kw): return ()
        def latest_xau_prepared_plan_lifecycle(self, **kw): return ()
        def latest_rizan_execution_geometry_compact(self, **kw): return ()
        def latest_xau_atlas_operational_heartbeat(self): return None
        def latest_xau_v226_operational_heartbeat(self): return None

    monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "test")
    monkeypatch.setitem(sys.modules, "supabase", SimpleNamespace(create_client=lambda *a: None))
    monkeypatch.setattr(bridge, "SupabaseDashboardReader", Reader)
    monkeypatch.setattr(bridge, "SupabaseOperationalStore", lambda *a, **kw:
                        SimpleNamespace(get_execution_control=lambda: ExecutionControlSnapshot(
                            control_key="primary", execution_mode="AUTO", new_orders_enabled=True,
                            emergency_stop=False, close_all_requested=False, version=1, updated_at=now)))
    out = bridge.build_snapshot(previous=previous, now=now)
    assert out["backend"]["broker_account"] is None
    assert out["backend"]["broker_positions"] == []
    assert out["backend"]["account_telemetry_redacted"] is True
    assert out["source"]["account_telemetry_public"] is False


def test_v229_query_projects_display_fields_without_duplicate_candidate_or_hazard():
    from types import SimpleNamespace
    from fx_scanner.dashboard import SupabaseDashboardReader
    selected = []
    class Query:
        def table(self, name): return self
        def select(self, fields): selected.append(fields); return self
        def eq(self, *a): return self
        def order(self, *a, **kw): return self
        def limit(self, n): return self
        def execute(self):
            return SimpleNamespace(data=[{
                "worker_name": "ctrader_demo_xau_v229_depth_execution",
                "plan_execution_phase": "RETEST_CONFIRMATION",
                "plan_children": [{"slot": 3, "submit_eligible": False}],
                "plan_diagnostics": {"reason": "TERMINAL_RR_BELOW_MINIMUM"},
                "structure_admission": {"allowed": True},
            }])
    result = SupabaseDashboardReader(Query()).latest_rizan_v229_execution_heartbeat()
    assert "plan:details->plan" not in selected[0]
    assert "plan_children:details->plan->children" in selected[0]
    assert result["details"]["plan"]["execution_phase"] == "RETEST_CONFIRMATION"
    assert result["details"]["plan"]["children"][0]["submit_eligible"] is False
    assert result["details"]["plan_diagnostics"]["reason"] == "TERMINAL_RR_BELOW_MINIMUM"


def test_v317_bridge_refreshes_v296_v297_in_hot_tier():
    from fx_scanner.xau_dashboard_bridge_v254 import HOT_HEARTBEATS
    assert "ctrader_demo_xau_decision_center_v296" in HOT_HEARTBEATS
    assert "ctrader_demo_xau_meta_research_sampler_v297" in HOT_HEARTBEATS
    assert "ctrader_demo_xau_structural_research_probe_v318" in HOT_HEARTBEATS
    assert "ctrader_demo_xau_micro_entry_refinement_v320" in HOT_HEARTBEATS
    assert "ctrader_demo_xau_micro_entry_dual_cycle_v321" in HOT_HEARTBEATS
    assert "ctrader_demo_xau_micro_handoff_v322" in HOT_HEARTBEATS

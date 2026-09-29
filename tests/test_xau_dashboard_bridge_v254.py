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
    assert 'latest_signals_for_symbol("XAUUSD", limit=12)' in text
    assert "latest_xau_geometry_events(limit=8)" in text
    assert "latest_xau_execution_events(limit=12)" in text
    assert "latest_xau_prepared_plan_lifecycle(limit=15)" in text


def test_public_snapshot_removes_nested_account_finances():
    from fx_scanner.xau_dashboard_bridge_v254 import _sanitize
    value = {"equity": 123, "nested": [{"account_balance": 456, "margin_free": 78,
             "client_secret": "never-public", "direction": "LONG"}]}
    assert _sanitize(value) == {"nested": [{"direction": "LONG"}]}


def test_bridge_reuses_audit_history_but_never_fetches_private_account(monkeypatch):
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
        def latest_afic_forecast_states(self): return ()
        def latest_afic_prepared_plans(self): return ()
        def latest_broker_account(self): raise AssertionError("private read")
        def latest_xau_geometry_events(self, **kw): raise AssertionError("audit cache bypass")

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
    assert out["source"]["audit_reused"] is True
    assert out["backend"]["xau_geometry_events"] == previous["backend"]["xau_geometry_events"]

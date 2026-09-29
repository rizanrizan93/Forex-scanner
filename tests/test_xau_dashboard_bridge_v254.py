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
    assert "latest_xau_geometry_events(limit=4)" in text
    assert "latest_xau_execution_events(limit=6)" in text
    assert "latest_xau_prepared_plan_lifecycle(limit=8)" in text


def test_v259_bridge_refreshes_compact_operational_structure_each_minute() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    text = (root / "src/fx_scanner/xau_dashboard_bridge_v254.py").read_text()
    assert "latest_xau_atlas_operational_heartbeat()" in text
    assert "latest_xau_v226_operational_heartbeat()" in text
    assert "merge_runtime_heartbeat_rows" in text
    assert '"operational_structure_refresh_seconds": int(HOT_REFRESH_SECONDS)' in text

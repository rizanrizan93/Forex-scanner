from datetime import UTC, datetime, timedelta

import pytest

from fx_scanner.xau_dashboard_bridge_v254 import validate_snapshot


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

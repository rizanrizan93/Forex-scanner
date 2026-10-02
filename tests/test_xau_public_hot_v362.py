import json
from datetime import UTC, datetime

from fx_scanner.xau_public_hot_v362 import (
    CONTRACT,
    overlay_public_hot_backend,
    fetch_public_hot_snapshot,
    validate_public_hot_snapshot,
)


class _Response:
    def __init__(self, payload):
        self.payload = payload
        self.headers = {}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def _payload(observed_at="2026-10-02T13:20:00+00:00"):
    return {
        "contract": CONTRACT,
        "primary_observed_at": observed_at,
        "executor_observed_at": observed_at,
        "heartbeats": [
            {
                "worker_name": "ctrader_demo_xau_sd_liquidity_v342",
                "observed_at": observed_at,
                "healthy": True,
                "lag_seconds": 0,
                "details": {"evaluation": {"price_now": 4190.0}},
            }
        ],
        "control": {
            "execution_mode": "AUTO",
            "new_orders_enabled": True,
            "emergency_stop": False,
        },
    }


def test_v362_public_hot_freshness_uses_primary_engine_timestamp():
    out = validate_public_hot_snapshot(
        _payload(),
        now=datetime(2026, 10, 2, 13, 21, 0, tzinfo=UTC),
    )
    assert out["hot_transport"]["fresh"] is True
    assert out["hot_transport"]["age_seconds"] == 60.0


def test_v362_public_hot_marks_old_primary_stale():
    out = validate_public_hot_snapshot(
        _payload(),
        now=datetime(2026, 10, 2, 13, 23, 0, tzinfo=UTC),
    )
    assert out["hot_transport"]["fresh"] is False


def test_v362_fetch_uses_publishable_apikey_without_service_secret():
    seen = {}

    def opener(request, timeout):
        seen["apikey"] = request.headers.get("Apikey")
        seen["authorization"] = request.headers.get("Authorization")
        seen["timeout"] = timeout
        return _Response(_payload())

    out = fetch_public_hot_snapshot(
        publishable_key="sb_publishable_test",
        opener=opener,
        now=datetime(2026, 10, 2, 13, 21, 0, tzinfo=UTC),
    )
    assert out["hot_transport"]["fresh"] is True
    assert seen["apikey"] == "sb_publishable_test"
    assert seen["authorization"] is None


def test_v362_hot_rows_override_stale_bridge_rows_and_control():
    old = {
        "heartbeats": [
            {
                "worker_name": "ctrader_demo_xau_sd_liquidity_v342",
                "observed_at": "2026-10-02T13:10:00+00:00",
                "details": {"evaluation": {"price_now": 4180.0}},
            },
            {
                "worker_name": "cold_worker",
                "observed_at": "2026-10-02T12:00:00+00:00",
                "details": {},
            },
        ],
        "control": {"execution_mode": "DISABLED"},
    }
    hot = _payload()
    merged = overlay_public_hot_backend(old, hot)
    rows = {row["worker_name"]: row for row in merged["heartbeats"]}
    assert rows["ctrader_demo_xau_sd_liquidity_v342"]["details"]["evaluation"]["price_now"] == 4190.0
    assert "cold_worker" in rows
    assert merged["control"]["execution_mode"] == "AUTO"

import json
from datetime import UTC, datetime
import pytest

from fx_scanner.xau_public_hot_v362 import (
    CONTRACT,
    overlay_public_hot_backend,
    fetch_public_hot_snapshot,
    fetch_supabase_public_hot_snapshot,
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

    out = fetch_supabase_public_hot_snapshot(
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


def _bridge(primary_time="2026-10-02T13:20:00+00:00", backend="turso"):
    from fx_scanner.xau_dashboard_bridge_v254 import CONTRACT as BRIDGE_CONTRACT
    hot = _payload(primary_time)
    return {
        "contract": BRIDGE_CONTRACT,
        "as_of": "2026-10-02T13:21:00+00:00",
        "source": {"database_backend": backend},
        "backend": {
            "heartbeats": hot["heartbeats"], "control": hot["control"],
            "xau_signals": [], "afic_forecast_states": [],
            "afic_prepared_plans": [], "xau_execution_events": [],
            "xau_geometry_events": [],
        },
    }


def test_default_hot_reader_uses_turso_bridge_without_db_credentials():
    def opener(request, timeout):
        assert request.get_method() == "GET"
        assert "dashboard-snapshots-v344" in request.full_url
        assert request.headers.get("Apikey") is None
        assert request.headers.get("Authorization") is None
        return _Response(_bridge())
    out = fetch_public_hot_snapshot(opener=opener, now=datetime(2026, 10, 2, 13, 21, tzinfo=UTC))
    assert out["hot_transport"]["source"] == "TURSO_DASHBOARD_BRIDGE"
    assert out["hot_transport"]["age_seconds"] == 60
    assert out["heartbeats"][0]["details"]["evaluation"]["price_now"] == 4190


@pytest.mark.parametrize("case", ["old_primary", "old_publication", "supabase", "unhealthy", "missing_primary"])
def test_turso_reader_rejects_stale_or_wrong_source_without_fallback(case):
    payload = _bridge()
    if case == "old_primary":
        payload["backend"]["heartbeats"][0]["observed_at"] = "2026-10-02T13:10:00+00:00"
    elif case == "old_publication":
        payload["as_of"] = "2026-10-02T13:10:00+00:00"
    elif case == "supabase":
        payload["source"]["database_backend"] = "supabase"
    elif case == "unhealthy":
        payload["backend"]["heartbeats"][0]["healthy"] = False
    else:
        payload["backend"]["heartbeats"][0]["worker_name"] = "other_worker"
    calls = []
    def opener(request, timeout):
        calls.append(request.full_url)
        return _Response(payload)
    with pytest.raises(ValueError):
        fetch_public_hot_snapshot(opener=opener, now=datetime(2026, 10, 2, 13, 21, tzinfo=UTC))
    assert len(calls) == (2 if case in {"old_publication", "old_primary", "missing_primary"} else 1)


def test_event_calendar_display_accepts_mixed_values_without_changing_raw_data():
    from fx_scanner.xau_dual_engine_dashboard_v344_legacy import _event_value
    import pandas as pd
    import pyarrow as pa
    raw = [None, 1.5, "N/A", "2.5%", float("nan")]
    frame = pd.DataFrame({name: [_event_value(v) for v in raw] for name in ("Forecast", "Previous", "Actual")})
    assert pa.Table.from_pandas(frame).num_rows == 5
    assert raw[1] == 1.5
    assert frame["Forecast"].tolist() == ["—", "1.5", "N/A", "2.5%", "—"]


@pytest.mark.parametrize("stale_field", ["publication", "primary"])
def test_stale_cdn_resolves_immutable_snapshot_and_still_validates_freshness(stale_field):
    old = _bridge()
    if stale_field == "publication":
        old["as_of"] = "2026-10-02T13:10:00+00:00"
    else:
        old["backend"]["heartbeats"][0]["observed_at"] = "2026-10-02T13:10:00+00:00"
    sha = "a" * 40
    calls = []
    def opener(request, timeout):
        calls.append(request.full_url)
        if "api.github.com" in request.full_url:
            return _Response({"object": {"sha": sha}})
        return _Response(_bridge() if sha in request.full_url else old)
    now = datetime(2026, 10, 2, 13, 21, tzinfo=UTC)
    out = fetch_public_hot_snapshot(opener=opener, now=now)
    assert out["hot_transport"]["fresh"]
    assert len(calls) == 3
    assert sha in calls[-1]
    # Multiple pages share the reference lookup budget.
    fetch_public_hot_snapshot(opener=opener, now=now)
    assert sum("api.github.com" in url for url in calls) == 1

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fx_scanner.xau_event_confidence_v377 import (
    CONTRACT,
    decorate_event_dict,
    event_confidence,
    prepare_dashboard_event,
    prepare_dashboard_heartbeat,
)


def _event(**overrides):
    now = datetime(2026, 10, 4, 0, 0, tzinfo=UTC)
    base = {
        "title": "Consumer Price Index",
        "scheduled_at": (now + timedelta(days=10)).isoformat(),
        "category": "CPI",
        "source_tier": "OFFICIAL",
        "actual": None,
        "forecast": None,
        "previous": None,
        "gold_bias": "NEUTRAL_UNKNOWN",
        "gold_bias_confidence": "LOW",
    }
    base.update(overrides)
    return now, base


def test_v377_schedule_only_is_not_misrepresented_as_directional_low():
    now, event = _event()
    out = event_confidence(event, now=now)
    assert out["confidence_contract"] == CONTRACT
    assert out["numeric_coverage"] == "SCHEDULE_ONLY"
    assert out["data_confidence"] == "LOW"
    assert out["direction_confidence"] == "UNAVAILABLE"
    assert out["actual_status"] == "PENDING_RELEASE"
    assert out["forecast_status"] == "NO_CONSENSUS_AVAILABLE"


def test_v377_consensus_ready_separates_data_and_direction_confidence():
    now, event = _event(forecast=3.1, previous=3.0)
    out = event_confidence(event, now=now)
    assert out["numeric_coverage"] == "CONSENSUS_READY"
    assert out["data_confidence"] == "MEDIUM"
    assert out["direction_confidence"] == "LOW"


def test_v377_official_post_release_actual_has_high_data_confidence():
    now, event = _event(
        scheduled_at=(datetime(2026, 10, 3, 12, 30, tzinfo=UTC)).isoformat(),
        source_tier="OFFICIAL_ACTUAL_WITH_DISCOVERY_CONSENSUS",
        actual=29_000.0,
        forecast=89_000.0,
        previous=162_000.0,
    )
    out = event_confidence(event, now=now)
    assert out["numeric_coverage"] == "POST_RELEASE_READY"
    assert out["data_confidence"] == "HIGH"
    assert out["direction_confidence"] == "MEDIUM"
    assert out["actual_status"] == "AVAILABLE"


def test_v377_language_event_is_explicitly_undetermined():
    now, event = _event(category="FED_SPEECH", title="FOMC Member Speaks")
    out = event_confidence(event, now=now)
    assert out["direction_confidence"] == "UNDETERMINED"


def test_v377_storage_decoration_preserves_none_numeric_fields():
    now, event = _event()
    out = decorate_event_dict(event, now=now)
    assert out["actual"] is None
    assert out["forecast"] is None
    assert out["previous"] is None
    assert out["numeric_coverage"] == "SCHEDULE_ONLY"


def test_v377_dashboard_copy_replaces_blank_cells_with_status_labels():
    now, event = _event()
    out = prepare_dashboard_event(event, now=now)
    assert out["actual"] == "MENUNGGU RILIS"
    assert out["forecast"] == "BELUM ADA KONSENSUS"
    assert out["previous"] == "BELUM TERSEDIA"
    assert out["gold_bias_confidence"] == "ARAH:UNAVAILABLE | DATA:LOW"


def test_v377_post_release_missing_actual_is_visible_not_blank():
    fixture_now = datetime(2026, 10, 4, 0, 0, tzinfo=UTC)
    now, event = _event(
        scheduled_at=(fixture_now - timedelta(hours=2)).isoformat()
    )
    out = prepare_dashboard_event(event, now=now)
    assert out["actual"] == "BELUM TERSEDIA"
    assert out["actual_status"] == "NOT_AVAILABLE_POST_RELEASE"


def test_v377_heartbeat_transform_is_display_only_and_covers_all_event_slots():
    now, event = _event()
    heartbeat = {
        "details": {
            "risk": {
                "focal_event": dict(event),
                "upcoming_events": [dict(event)],
                "latest_released_event": {},
            },
            "dashboard_projection": {
                "focal_event": dict(event),
                "upcoming_events": [dict(event)],
            },
        }
    }
    out = prepare_dashboard_heartbeat(heartbeat, now=now)
    assert heartbeat["details"]["risk"]["focal_event"]["forecast"] is None
    assert out["details"]["risk"]["focal_event"]["forecast"] == "BELUM ADA KONSENSUS"
    assert out["details"]["risk"]["upcoming_events"][0]["actual"] == "MENUNGGU RILIS"
    assert out["details"]["dashboard_projection"]["focal_event"]["previous"] == "BELUM TERSEDIA"


def test_v377_worker_wrapper_adds_metadata_without_changing_numeric_payload():
    from fx_scanner import demo_xau_event_risk_v192 as base
    from fx_scanner import demo_xau_event_risk_v377 as wrapper

    original_method = base.RiskEvent.as_dict
    original_contract = base.CONTRACT
    original_installed = wrapper._INSTALLED
    try:
        wrapper._INSTALLED = False
        wrapper.install_v377()
        at = datetime.now(tz=UTC) + timedelta(days=1)
        event = base.RiskEvent(
            event_id="cpi",
            title="Consumer Price Index",
            scheduled_at=at,
            impact="HIGH",
            category="CPI",
            source="BLS_OFFICIAL_ICS",
            source_tier="OFFICIAL",
            source_url="https://www.bls.gov/example",
        )
        payload = event.as_dict()
        assert base.CONTRACT == wrapper.CONTRACT
        assert payload["actual"] is None
        assert payload["forecast"] is None
        assert payload["previous"] is None
        assert payload["data_confidence"] == "LOW"
        assert payload["direction_confidence"] == "UNAVAILABLE"
    finally:
        base.RiskEvent.as_dict = original_method
        base.CONTRACT = original_contract
        wrapper._INSTALLED = original_installed
def test_mixed_calendar_values_serialize_to_arrow():
    import pandas as pd
    import pyarrow as pa
    from fx_scanner.xau_dual_engine_dashboard_v344_legacy import _event_value

    values = [None, 175.0, "2.1%", float("nan"), -0.4]
    frame = pd.DataFrame({column: [_event_value(value) for value in values]
                          for column in ("Forecast", "Previous", "Actual")})
    assert pa.Table.from_pandas(frame).num_rows == len(values)

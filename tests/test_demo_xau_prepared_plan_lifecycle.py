from datetime import UTC, datetime, timedelta

from fx_scanner.demo_xau_prepared_plan_lifecycle import (
    FORECAST_EVENT_TYPE,
    PREPARED_EVENT_TYPE,
    TRACKED_EVENT_TYPES,
    _cancel_reason,
    _same_map_touch_confirm,
    lifecycle_metrics,
    lifecycle_state,
)


def test_lifecycle_state_preserves_terminal_broker_authority_precedence():
    now = datetime(2026, 9, 23, 0, 0, tzinfo=UTC)
    assert lifecycle_state(
        cancelled_at=now,
        first_touch_at=now,
        confirmed_at=now,
        execution_ready_at=now,
        order_accepted_at=now,
        protection_verified_at=now,
        closed_at=now,
    ) == "CLOSED"
    assert lifecycle_state(
        cancelled_at=now,
        first_touch_at=now,
        confirmed_at=now,
        execution_ready_at=now,
        order_accepted_at=now,
        protection_verified_at=now,
        closed_at=None,
    ) == "PROTECTED"


def test_lifecycle_state_waiting_touch_confirm_cancel_paths():
    now = datetime(2026, 9, 23, 0, 0, tzinfo=UTC)
    assert lifecycle_state(
        cancelled_at=None,
        first_touch_at=None,
        confirmed_at=None,
        execution_ready_at=None,
        order_accepted_at=None,
        protection_verified_at=None,
        closed_at=None,
    ) == "WAITING_PRICE"
    assert lifecycle_state(
        cancelled_at=None,
        first_touch_at=now,
        confirmed_at=None,
        execution_ready_at=None,
        order_accepted_at=None,
        protection_verified_at=None,
        closed_at=None,
    ) == "ZONE_ENTERED"
    assert lifecycle_state(
        cancelled_at=None,
        first_touch_at=now,
        confirmed_at=now,
        execution_ready_at=None,
        order_accepted_at=None,
        protection_verified_at=None,
        closed_at=None,
    ) == "CONFIRMED"
    assert lifecycle_state(
        cancelled_at=now,
        first_touch_at=None,
        confirmed_at=None,
        execution_ready_at=None,
        order_accepted_at=None,
        protection_verified_at=None,
        closed_at=None,
    ) == "CANCELLED"


def test_cancel_reason_maps_superseded_plan_to_h4_remap():
    created = datetime(2026, 9, 22, 20, 1, tzinfo=UTC)
    next_map = created + timedelta(hours=4)
    signal = {
        "state": "INVALIDATED",
        "active_guards": ["AFIC_MAP_SUPERSEDED"],
        "expires_at": (created + timedelta(hours=24)).isoformat(),
    }
    forecast_events = (
        {
            "observed_at": next_map.isoformat(),
            "payload": {
                "forecast": {
                    "map_at": "2026-09-23T00:00:00+00:00",
                    "state": "NO_MAP_ZONE",
                }
            },
        },
    )
    at, reason = _cancel_reason(
        signal,
        created_at=created,
        map_at="2026-09-22T20:00:00+00:00",
        forecast_events=forecast_events,
        now=next_map,
    )
    assert at == next_map
    assert reason == "H4_REMAP"


def test_cancel_reason_prefers_same_map_price_invalidation():
    created = datetime(2026, 9, 22, 20, 1, tzinfo=UTC)
    invalid = created + timedelta(minutes=44)
    signal = {
        "state": "INVALIDATED",
        "active_guards": ["AFIC_MAP_SUPERSEDED"],
        "expires_at": (created + timedelta(hours=24)).isoformat(),
    }
    forecast_events = (
        {
            "observed_at": invalid.isoformat(),
            "payload": {
                "forecast": {
                    "map_at": "2026-09-22T20:00:00+00:00",
                    "state": "INVALIDATED_AFTER_TOUCH_REMAP_DUE",
                }
            },
        },
    )
    at, reason = _cancel_reason(
        signal,
        created_at=created,
        map_at="2026-09-22T20:00:00+00:00",
        forecast_events=forecast_events,
        now=invalid,
    )
    assert at == invalid
    assert reason == "PRICE_INVALIDATION_AFTER_TOUCH"


def test_lifecycle_metrics_are_denominator_safe_and_explicit():
    rows = (
        {
            "lifecycle_state": "CANCELLED",
            "first_touch_at": "2026-09-22T20:15:00+00:00",
            "confirmed_at": None,
            "order_accepted_at": None,
            "post_cancel_terminal_hit": True,
        },
        {
            "lifecycle_state": "PROTECTED",
            "first_touch_at": "2026-09-22T21:15:00+00:00",
            "confirmed_at": "2026-09-22T21:30:00+00:00",
            "order_accepted_at": "2026-09-22T21:31:00+00:00",
            "post_cancel_terminal_hit": False,
        },
    )
    metrics = lifecycle_metrics(rows)
    assert metrics["plans"] == 2
    assert metrics["zone_reach_rate"] == 1.0
    assert metrics["touch_to_confirmation_rate"] == 0.5
    assert metrics["cancellation_rate"] == 0.5
    assert metrics["execution_conversion_rate"] == 0.5
    assert metrics["post_cancel_terminal_hit_rate"] == 1.0


def test_lifecycle_event_retrieval_is_scoped_to_relevant_event_families():
    assert PREPARED_EVENT_TYPE in TRACKED_EVENT_TYPES
    assert FORECAST_EVENT_TYPE in TRACKED_EVENT_TYPES
    assert "ORDER_ACCEPTED" in TRACKED_EVENT_TYPES
    assert "POSITION_PROTECTION_VERIFIED" in TRACKED_EVENT_TYPES
    assert "DEMO_TRADE_CLOSED" in TRACKED_EVENT_TYPES


def test_same_map_confirm_timeout_is_not_mislabeled_price_invalidation():
    created = datetime(2026, 9, 22, 8, 0, tzinfo=UTC)
    timeout = datetime(2026, 9, 22, 11, 1, tzinfo=UTC)
    signal = {
        "state": "INVALIDATED",
        "active_guards": ["AFIC_MAP_SUPERSEDED"],
        "expires_at": (created + timedelta(hours=24)).isoformat(),
    }
    events = (
        {
            "observed_at": timeout.isoformat(),
            "payload": {"forecast": {
                "map_at": "2026-09-22T08:00:00+00:00",
                "state": "CONFIRM_TIMEOUT_REMAP_DUE",
            }},
        },
    )
    at, reason = _cancel_reason(
        signal,
        created_at=created,
        map_at="2026-09-22T08:00:00+00:00",
        forecast_events=events,
        now=timeout,
    )
    assert at == timeout
    assert reason == "CONFIRMATION_TIMEOUT"


def test_same_map_no_map_zone_reports_pre_map_invalidation():
    created = datetime(2026, 9, 22, 20, 1, tzinfo=UTC)
    revalidated = datetime(2026, 9, 22, 22, 38, tzinfo=UTC)
    signal = {
        "state": "INVALIDATED",
        "active_guards": ["AFIC_MAP_SUPERSEDED"],
        "expires_at": (created + timedelta(hours=24)).isoformat(),
    }
    events = (
        {
            "observed_at": revalidated.isoformat(),
            "payload": {"forecast": {
                "map_at": "2026-09-22T20:00:00+00:00",
                "state": "NO_MAP_ZONE",
                "zone_diagnostics": {
                    "invalidated_before_map": 2,
                    "structurally_active_fresh": 0,
                },
            }},
        },
    )
    at, reason = _cancel_reason(
        signal,
        created_at=created,
        map_at="2026-09-22T20:00:00+00:00",
        forecast_events=events,
        now=revalidated,
    )
    assert at == revalidated
    assert reason == "INVALIDATED_BEFORE_MAP"


def test_touch_metric_ignores_historical_touch_before_plan_creation():
    created = datetime(2026, 9, 22, 20, 1, tzinfo=UTC)
    events = (
        {
            "observed_at": (created + timedelta(minutes=5)).isoformat(),
            "payload": {"forecast": {
                "map_at": "2026-09-22T20:00:00+00:00",
                "state": "APPROACHING_ZONE",
                "first_touch_at": "2026-09-22T01:45:00+00:00",
                "map_first_touch_at": None,
            }},
        },
    )
    touch, confirm = _same_map_touch_confirm(
        events,
        created_at=created,
        map_at="2026-09-22T20:00:00+00:00",
    )
    assert touch is None
    assert confirm is None


def test_touch_metric_accepts_post_plan_durable_touch():
    created = datetime(2026, 9, 22, 8, 0, tzinfo=UTC)
    touch_at = created + timedelta(minutes=45)
    events = (
        {
            "observed_at": created + timedelta(hours=1),
            "payload": {"forecast": {
                "map_at": "2026-09-22T08:00:00+00:00",
                "state": "ZONE_TOUCHED_WAIT_CONFIRM",
                "first_touch_at": touch_at.isoformat(),
            }},
        },
    )
    touch, confirm = _same_map_touch_confirm(
        events,
        created_at=created,
        map_at="2026-09-22T08:00:00+00:00",
    )
    assert touch == touch_at
    assert confirm is None

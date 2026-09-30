from datetime import UTC, datetime, timedelta

from fx_scanner.demo_xau_prepared_plan_lifecycle import (
    FORECAST_EVENT_TYPE,
    PREPARED_EVENT_TYPE,
    TRACKED_EVENT_TYPES,
    _cancel_reason,
    _effective_event_cutoff,
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


def test_lifecycle_metrics_are_denominator_safe_and_split_active_vs_post_cancel():
    rows = (
        {
            "lifecycle_state": "CANCELLED",
            "cancelled_at": "2026-09-22T20:10:00+00:00",
            "first_touch_at": "2026-09-22T20:15:00+00:00",
            "confirmed_at": None,
            "order_accepted_at": None,
            "post_cancel_terminal_hit": True,
            "metadata": {
                "touch_while_active": False,
                "post_cancel_touch": True,
                "confirmation_while_active": False,
            },
        },
        {
            "lifecycle_state": "PROTECTED",
            "cancelled_at": None,
            "first_touch_at": "2026-09-22T21:15:00+00:00",
            "confirmed_at": "2026-09-22T21:30:00+00:00",
            "order_accepted_at": "2026-09-22T21:31:00+00:00",
            "post_cancel_terminal_hit": False,
            "metadata": {
                "touch_while_active": True,
                "post_cancel_touch": False,
                "confirmation_while_active": True,
            },
        },
    )
    metrics = lifecycle_metrics(rows)
    assert metrics["plans"] == 2
    assert metrics["active_zone_reach_rate"] == 0.5
    assert metrics["touch_to_confirmation_rate"] == 1.0
    assert metrics["cancellation_rate"] == 0.5
    assert metrics["execution_conversion_rate"] == 0.5
    assert metrics["post_cancel_zone_reach_rate"] == 1.0
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


def test_lifecycle_metrics_fallback_classifies_touch_chronology_without_metadata():
    rows = (
        {
            "lifecycle_state": "CANCELLED",
            "cancelled_at": "2026-09-22T20:10:00+00:00",
            "first_touch_at": "2026-09-22T20:15:00+00:00",
            "confirmed_at": None,
            "order_accepted_at": None,
            "post_cancel_terminal_hit": False,
        },
        {
            "lifecycle_state": "CANCELLED",
            "cancelled_at": "2026-09-22T21:20:00+00:00",
            "first_touch_at": "2026-09-22T21:15:00+00:00",
            "confirmed_at": None,
            "order_accepted_at": None,
            "post_cancel_terminal_hit": False,
        },
    )
    metrics = lifecycle_metrics(rows)
    assert metrics["active_zone_reach_rate"] == 0.5
    assert metrics["post_cancel_zone_reach_rate"] == 0.5


def test_v282_cancel_reason_maps_v280_operational_guards() -> None:
    created = datetime(2026, 9, 30, 1, 0, tzinfo=UTC)
    cases = {
        "V280_MISSED_ENTRY_WAIT_NEXT_SETUP": "MISSED_ENTRY_NO_CHASE",
        "V280_BREAK_RISK": "BREAK_RISK",
        "V280_SETUP_INVALID": "SETUP_INVALID",
    }
    for guard, expected in cases.items():
        signal = {
            "state": "INVALIDATED",
            "active_guards": [guard],
            "expires_at": (created + timedelta(hours=12)).isoformat(),
        }
        at, reason = _cancel_reason(
            signal,
            created_at=created,
            map_at="2026-09-30T00:00:00+00:00",
            forecast_events=(),
            now=created + timedelta(minutes=5),
        )
        assert at == created
        assert reason == expected


def test_v282_lifecycle_metrics_report_stage_latencies_and_v280_prevention() -> None:
    rows = (
        {
            "created_at": "2026-09-30T00:00:00+00:00",
            "first_touch_at": "2026-09-30T00:10:00+00:00",
            "confirmed_at": "2026-09-30T00:14:00+00:00",
            "execution_ready_at": "2026-09-30T00:15:00+00:00",
            "order_accepted_at": "2026-09-30T00:16:00+00:00",
            "protection_verified_at": "2026-09-30T00:17:00+00:00",
            "cancelled_at": None,
            "cancel_reason": None,
            "lifecycle_state": "PROTECTED",
            "post_cancel_terminal_hit": False,
            "metadata": {
                "touch_while_active": True,
                "post_cancel_touch": False,
                "confirmation_while_active": True,
            },
        },
        {
            "created_at": "2026-09-30T00:20:00+00:00",
            "first_touch_at": "2026-09-30T00:25:00+00:00",
            "confirmed_at": None,
            "execution_ready_at": None,
            "order_accepted_at": None,
            "protection_verified_at": None,
            "cancelled_at": "2026-09-30T00:28:00+00:00",
            "cancel_reason": "MISSED_ENTRY_NO_CHASE",
            "lifecycle_state": "CANCELLED",
            "post_cancel_terminal_hit": False,
            "metadata": {
                "touch_while_active": True,
                "post_cancel_touch": False,
                "confirmation_while_active": False,
            },
        },
        {
            "created_at": "2026-09-30T00:30:00+00:00",
            "first_touch_at": None,
            "confirmed_at": None,
            "execution_ready_at": None,
            "order_accepted_at": None,
            "protection_verified_at": None,
            "cancelled_at": "2026-09-30T00:34:00+00:00",
            "cancel_reason": "BREAK_RISK",
            "lifecycle_state": "CANCELLED",
            "post_cancel_terminal_hit": False,
            "metadata": {
                "touch_while_active": False,
                "post_cancel_touch": False,
                "confirmation_while_active": False,
            },
        },
    )
    metrics = lifecycle_metrics(rows)
    assert metrics["v280_prevented_entry_count"] == 2
    assert metrics["v280_no_chase_prevented_count"] == 1
    assert metrics["v280_break_risk_block_count"] == 1
    assert metrics["v280_setup_invalid_block_count"] == 0
    assert metrics["latency"]["created_to_first_touch"]["n"] == 2
    assert metrics["latency"]["created_to_first_touch"]["median_minutes"] == 7.5
    assert metrics["latency"]["first_touch_to_confirmation"]["median_minutes"] == 4.0
    assert metrics["latency"]["confirmation_to_execution_ready"]["median_minutes"] == 1.0
    assert metrics["latency"]["execution_ready_to_order_accepted"]["median_minutes"] == 1.0
    assert metrics["latency"]["order_accepted_to_protection"]["median_minutes"] == 1.0
    assert metrics["latency"]["first_touch_to_cancel_or_invalidation"]["median_minutes"] == 3.0


def test_v282_lifecycle_reconstruction_reduces_postgrest_egress() -> None:
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1]
        / "src/fx_scanner/demo_xau_prepared_plan_lifecycle.py"
    ).read_text()
    assert "LOOKBACK_DAYS = 7" in source
    assert 'else "observed_at,event_type,signal_key,accepted"' in source
    assert '.eq("accepted", True)' in source
    assert '"event_read_contract": "V288_PLAN_SCOPED_FAIL_SOFT_RECONSTRUCTION"' in source


def test_v282_v280_stage_block_event_supplies_exact_invalidation_time() -> None:
    created = datetime(2026, 9, 30, 1, 0, tzinfo=UTC)
    blocked = created + timedelta(minutes=7)
    signal = {
        "state": "INVALIDATED",
        "active_guards": ["V280_MISSED_ENTRY_WAIT_NEXT_SETUP"],
        "expires_at": (created + timedelta(hours=12)).isoformat(),
    }
    signal_events = (
        {
            "observed_at": blocked.isoformat(),
            "event_type": "DEMO_XAU_RIZAN_STAGE_BLOCK",
            "signal_key": "signal-1",
            "code": "V280_MISSED_ENTRY_WAIT_NEXT_SETUP",
        },
    )
    at, reason = _cancel_reason(
        signal,
        created_at=created,
        map_at="2026-09-30T00:00:00+00:00",
        forecast_events=(),
        signal_events=signal_events,
        now=blocked + timedelta(minutes=1),
    )
    assert at == blocked
    assert reason == "MISSED_ENTRY_NO_CHASE"


def test_v288_effective_event_cutoff_tracks_oldest_actual_prepared_plan() -> None:
    requested = datetime(2026, 9, 23, 0, 0, tzinfo=UTC)
    prepared_at = datetime(2026, 9, 29, 8, 0, tzinfo=UTC)
    cutoff = _effective_event_cutoff(
        requested_cutoff=requested,
        prepared_rows=(
            {"observed_at": prepared_at.isoformat()},
            {"observed_at": (prepared_at + timedelta(hours=2)).isoformat()},
        ),
    )
    assert cutoff == prepared_at - timedelta(minutes=15)


def test_v288_effective_event_cutoff_falls_back_to_requested_without_plans() -> None:
    requested = datetime(2026, 9, 23, 0, 0, tzinfo=UTC)
    assert _effective_event_cutoff(
        requested_cutoff=requested,
        prepared_rows=(),
    ) == requested


def test_v288_lifecycle_event_reads_are_plan_scoped_and_fail_soft() -> None:
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1]
        / "src/fx_scanner/demo_xau_prepared_plan_lifecycle.py"
    ).read_text()
    assert "MAX_PREPARED_ROWS_PER_TYPE = 500" in source
    assert "EVENT_CUTOFF_PAD_MINUTES = 15" in source
    assert "def _events_with_diagnostics(" in source
    assert "legacy_fallback_used" in source
    assert "if prepared_rows:" in source
    assert '"severity": "DEGRADED"' in source
    assert '"severity": "CRITICAL"' in source
    assert '"event_read_contract": "V288_PLAN_SCOPED_FAIL_SOFT_RECONSTRUCTION"' in source
    assert '"event_diagnostics": event_diagnostics' in source
    assert '"degraded_sources"' in source
    assert '"downstream_reads_skipped_without_prepared_plan"' in source
    assert "if prepared_events:" in source


def test_v288_noncritical_query_failures_do_not_define_worker_health() -> None:
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1]
        / "src/fx_scanner/demo_xau_prepared_plan_lifecycle.py"
    ).read_text()
    assert "healthy = not critical_errors" in source
    assert "degraded = bool(errors)" in source
    assert "return 0 if healthy else 2" in source

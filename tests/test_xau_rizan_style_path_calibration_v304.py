from datetime import UTC, datetime, timedelta

from fx_scanner.models import Bar
from fx_scanner.xau_rizan_style_path_calibration_v304 import (
    CONTRACT,
    evaluate_reference_alignment,
    evaluate_reference_outcome,
    select_reference,
)


def _bar(at: datetime, open_: float, high: float, low: float, close: float) -> Bar:
    return Bar(
        symbol="XAUUSD",
        timeframe="M15",
        timestamp=at,
        open=open_,
        high=high,
        low=low,
        close=close,
        tick_count=100,
        spread_avg=0.2,
        spread_max=0.3,
    )


def _reference(available: datetime) -> dict:
    return {
        "reference_id": "REF-1",
        "symbol": "XAUUSD",
        "source_name": "PUBLIC_REFERENCE",
        "available_from": available.isoformat(),
        "horizon_hours": 48,
        "decision_zone": {"direction": "SHORT", "low": 4200.0, "high": 4212.0},
        "key_band": {"low": 4208.0, "high": 4212.0},
        "rejection_path": {
            "direction": "SHORT",
            "destinations": [
                {"low": 4153.0, "high": 4166.0},
                {"low": 4125.0, "high": 4140.0},
            ],
        },
        "acceptance_path": {
            "direction": "LONG",
            "destinations": [
                {"low": 4262.0, "high": 4273.0},
                {"low": 4284.0, "high": 4297.0},
            ],
        },
    }


def _style_path() -> dict:
    return {
        "state": "APPROACH_DECISION_ZONE",
        "active_direction": "LONG",
        "next_decision_zone": {
            "zone_id": "s1",
            "direction": "SHORT",
            "low": 4200.0,
            "high": 4212.0,
        },
        "key_levels": {
            "rejection_reclaim_key": 4200.0,
            "break_acceptance_key": 4212.0,
        },
        "rejection_branch": {
            "direction": "SHORT",
            "route": [
                {"price": 4180.0},
                {"price": 4160.0},
                {"price": 4135.0},
            ],
        },
        "acceptance_branch": {
            "direction": "LONG",
            "next_destination_zone": {
                "direction": "SHORT",
                "low": 4262.0,
                "high": 4273.0,
            },
        },
    }


def test_v304_select_reference_is_causal_and_horizon_bounded() -> None:
    available = datetime(2026, 9, 30, 10, 0, tzinfo=UTC)
    corpus = {"references": [_reference(available)]}
    assert select_reference(
        as_of=available - timedelta(seconds=1),
        corpus=corpus,
    ) == {}
    assert select_reference(
        as_of=available + timedelta(hours=24),
        corpus=corpus,
    )["reference_id"] == "REF-1"
    assert select_reference(
        as_of=available + timedelta(hours=49),
        corpus=corpus,
    ) == {}


def test_v304_alignment_measures_reference_geometry_not_winrate() -> None:
    available = datetime(2026, 9, 30, 10, 0, tzinfo=UTC)
    result = evaluate_reference_alignment(
        style_path=_style_path(),
        reference=_reference(available),
    )
    assert result["contract"] == CONTRACT
    assert result["state"] == "REFERENCE_ALIGNMENT_AVAILABLE"
    assert result["decision_zone_overlap_ratio"] == 1.0
    assert result["decision_zone_direction_match"] is True
    assert result["rejection_direction_match"] is True
    assert result["acceptance_direction_match"] is True
    assert result["acceptance_first_destination_overlap_ratio"] == 1.0
    assert result["rejection_first_destination_error_points"] == 0.0
    assert result["acceptance_key_error_points"] == 0.0
    assert result["rejection_key_error_points"] == 8.0
    assert result["score_semantics"] == "REFERENCE_GEOMETRY_ALIGNMENT_NOT_WIN_RATE"
    assert result["execution_authority"] is False
    assert result["execution_influence"] is False


def test_v304_rejection_outcome_ignores_pre_reference_bars() -> None:
    available = datetime(2026, 9, 30, 10, 0, tzinfo=UTC)
    reference = _reference(available)
    bars = (
        _bar(available - timedelta(minutes=15), 4204, 4215, 4199, 4214),
        _bar(available, 4194, 4204, 4190, 4202),
        _bar(available + timedelta(minutes=15), 4202, 4210, 4198, 4201),
        _bar(available + timedelta(minutes=30), 4201, 4209, 4180, 4185),
        _bar(available + timedelta(minutes=45), 4185, 4188, 4158, 4160),
        _bar(available + timedelta(minutes=60), 4160, 4162, 4132, 4136),
    )
    result = evaluate_reference_outcome(
        reference=reference,
        bars=bars,
        as_of=available + timedelta(hours=2),
    )
    assert result["decision_zone_arrived"] is True
    assert result["first_touch_at"] == available.isoformat()
    assert result["branch_outcome"] == "REJECTION_PATH_CONFIRMED"
    assert result["break_at"] is None
    assert result["rejection_destination_rank"] == 0
    assert result["terminal_rejection_path_complete"] is True
    assert result["reversal_price_error_to_key_band_points"] == 0.0
    assert result["prospective_no_lookahead"] is True


def test_v304_acceptance_break_then_destination_is_confirmed() -> None:
    available = datetime(2026, 9, 30, 10, 0, tzinfo=UTC)
    reference = _reference(available)
    bars = (
        _bar(available, 4198, 4204, 4196, 4202),
        _bar(available + timedelta(minutes=15), 4202, 4215, 4200, 4213),
        _bar(available + timedelta(minutes=30), 4213, 4240, 4210, 4235),
        _bar(available + timedelta(minutes=45), 4235, 4265, 4230, 4263),
        _bar(available + timedelta(minutes=60), 4263, 4290, 4260, 4286),
    )
    result = evaluate_reference_outcome(
        reference=reference,
        bars=bars,
        as_of=available + timedelta(hours=2),
    )
    assert result["branch_outcome"] == "ACCEPTANCE_PATH_CONFIRMED"
    assert result["break_at"] == (available + timedelta(minutes=15)).isoformat()
    assert result["acceptance_destination_rank"] == 0
    assert result["terminal_acceptance_path_complete"] is True

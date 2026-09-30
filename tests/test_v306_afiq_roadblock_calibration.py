from fx_scanner.xau_rizan_style_path_calibration_v304 import (
    evaluate_reference_alignment,
    evaluate_v304,
)


def _style():
    return {
        "state": "APPROACH_DECISION_ZONE",
        "price_now": 4187.8,
        "active_direction": "SHORT",
        "next_decision_zone": {
            "zone_id": "demand-1",
            "timeframe": "H1",
            "direction": "LONG",
            "low": 4153.0,
            "high": 4166.0,
        },
        "key_levels": {
            "rejection_reclaim_key": 4166.0,
            "break_acceptance_key": 4153.0,
            "midpoint": 4159.5,
        },
        "primary_path": {
            "direction": "SHORT",
            "route": [
                {"price": 4183.9, "source": "H1_SWING_HIGH"},
                {"price": 4160.0, "source": "ROUND_NUMBER"},
            ],
        },
        "rejection_branch": {"direction": "LONG", "route": []},
        "acceptance_branch": {
            "direction": "SHORT",
            "next_destination_zone": {
                "direction": "LONG",
                "low": 4125.0,
                "high": 4140.0,
            },
        },
    }


def _reference():
    return {
        "reference_id": "AFIQ-ROADBLOCK",
        "source_name": "PUBLIC_REFERENCE",
        "available_from": "2026-09-30T10:06:00+00:00",
        "decision_zone": {"direction": "LONG", "low": 4153.0, "high": 4166.0},
        "key_band": {"low": 4165.0, "high": 4167.0},
        "roadblock_key": {"price": 4183.85},
        "rejection_path": {"direction": "LONG", "destinations": []},
        "acceptance_path": {
            "direction": "SHORT",
            "destinations": [{"low": 4125.0, "high": 4140.0}],
        },
    }


def test_v306_alignment_measures_intermediate_roadblock_error() -> None:
    result = evaluate_reference_alignment(
        style_path=_style(),
        reference=_reference(),
    )
    assert result["reference_roadblock_price"] == 4183.85
    assert abs(result["roadblock_route_error_points"] - 0.05) < 1e-9


def test_v306_v304_payload_keeps_compact_rizan_baseline_geometry() -> None:
    result = evaluate_v304(
        style_path=_style(),
        bars=(),
        as_of=__import__("datetime").datetime(
            2026, 9, 30, 10, 7, tzinfo=__import__("datetime").UTC
        ),
        corpus={"references": [_reference() | {"symbol": "XAUUSD", "horizon_hours": 48}]},
    )
    snapshot = result["rizan_baseline_snapshot"]
    assert snapshot["active_direction"] == "SHORT"
    assert snapshot["decision_zone"]["zone_id"] == "demand-1"
    assert snapshot["key_levels"]["rejection_reclaim_key"] == 4166.0
    assert snapshot["acceptance_next_destination_zone"]["low"] == 4125.0

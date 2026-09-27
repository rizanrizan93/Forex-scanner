from datetime import UTC, datetime, timedelta

from fx_scanner.demo_xau_pressure_depth_prospective import (
    choose_touch_dom,
    opposing_dom_score,
    pressure_bucket,
    summarize,
)


def test_opposing_dom_score_reorients_by_zone_side():
    assert opposing_dom_score(direction="LONG", dom_pressure_score=20) == 60
    assert opposing_dom_score(direction="LONG", dom_pressure_score=80) == -60
    assert opposing_dom_score(direction="SHORT", dom_pressure_score=80) == 60
    assert opposing_dom_score(direction="SHORT", dom_pressure_score=20) == -60


def test_choose_touch_dom_prefers_sample_near_middle_of_touch_minute():
    touch = datetime(2026, 9, 28, 10, 0, tzinfo=UTC)
    rows = [
        {"observed_at": (touch - timedelta(seconds=20)).isoformat(), "dom_pressure_score": 30},
        {"observed_at": (touch + timedelta(seconds=28)).isoformat(), "dom_pressure_score": 35},
        {"observed_at": (touch + timedelta(seconds=58)).isoformat(), "dom_pressure_score": 70},
    ]
    chosen, slope = choose_touch_dom(rows, touch_at=touch)
    assert chosen is not None
    assert chosen["dom_pressure_score"] == 35
    assert slope is not None


def test_summary_maps_pressure_to_depth():
    rows = (
        {
            "pressure_bucket": "OPPOSING_STRONG",
            "turning_depth": 0.72,
            "max_depth_reached": 0.78,
            "reaction_hit_050": True,
            "invalidated": False,
        },
        {
            "pressure_bucket": "OPPOSING_STRONG",
            "turning_depth": 0.84,
            "max_depth_reached": 0.90,
            "reaction_hit_050": True,
            "invalidated": False,
        },
    )
    result = summarize(rows)
    cell = result["by_pressure_bucket"]["OPPOSING_STRONG"]
    assert cell["n"] == 2
    assert cell["turning_depth_median"] == 0.78
    assert cell["max_depth_median"] == 0.84


def test_bucket_contract():
    assert pressure_bucket(-50) == "COUNTER_STRONG"
    assert pressure_bucket(0) == "BALANCED"
    assert pressure_bucket(25) == "OPPOSING_MODERATE"
    assert pressure_bucket(70) == "OPPOSING_STRONG"

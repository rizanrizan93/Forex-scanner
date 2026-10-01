from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fx_scanner.xau_rizan_micro_handoff_v322 import (
    CONTRACT,
    SOURCE_RETEST_MAX_DISTANCE_ATR,
    build_micro_handoff_confluence,
)


def _bars(
    start: datetime,
    *,
    base: float,
    step: float,
    count: int,
    minutes: int,
) -> list[dict]:
    rows = []
    price = base
    for i in range(count):
        o = price
        c = price + step
        rows.append(
            {
                "time": (start + timedelta(minutes=i * minutes)).isoformat(),
                "open": o,
                "high": max(o, c) + 1.0,
                "low": min(o, c) - 1.0,
                "close": c,
            }
        )
        price = c
    return rows


def _atlas() -> dict:
    source = {
        "zone_id": "source-supply",
        "timeframe": "H1",
        "zone_class": "STRUCTURAL",
        "pattern": "STRUCTURAL_SUPPLY",
        "direction": "SHORT",
        "low": 118.0,
        "high": 130.0,
        "proximal": 118.0,
        "distal": 130.0,
        "atr_points": 12.0,
        "status": "IN_ZONE_PREPARE_ONLY",
        "lifecycle": {
            "active": True,
            "freshness": "FIRST_TEST",
            "touch_count": 1,
            "first_touch_at": "2026-10-01T01:00:00+00:00",
            "last_touch_at": "2026-10-01T01:05:00+00:00",
        },
    }
    destination = {
        "zone_id": "next-demand",
        "timeframe": "H1",
        "zone_class": "IMBALANCE",
        "pattern": "DBR",
        "direction": "LONG",
        "low": 90.0,
        "high": 100.0,
        "proximal": 100.0,
        "distal": 90.0,
        "atr_points": 10.0,
        "status": "ACTIVE_WATCH_PREPARE_ONLY",
        "lifecycle": {
            "active": True,
            "freshness": "FRESH",
            "touch_count": 0,
        },
    }
    return {
        "path_map": {
            "active_path": {
                "source_zone": source,
                "primary_opposing_zone": destination,
                "terminal_target_zone": destination,
                "destination_stack": [destination],
            }
        },
        "m5_path_projection": {
            "current_leg": {
                "micro_refinement": {
                    "state": "M5_TOUCH_WAIT_RECLAIM",
                    "direction": "SHORT",
                    "sweep": {
                        "price": 124.5,
                        "at": "2026-10-01T01:10:00+00:00",
                    },
                    "mss_level": 116.5,
                    "mss_confirmed": False,
                },
                "zone_reuse_v200": {
                    "state": "FIRST_TEST_PARENT_ACTIVE",
                    "priority": "WATCH_WITH_CONFIRMATION",
                    "active_candidate_micro_pocket": {
                        "low": 121.0,
                        "high": 124.0,
                        "source": "M5_SWEEP_ORIGIN_CANDIDATE",
                    },
                    "active_refined_micro_pocket": {},
                    "fresh_micro_confirmed": False,
                },
            }
        },
        "zones": [source, destination],
    }


def _inputs() -> tuple[list[dict], list[dict], list[dict]]:
    start = datetime(2026, 10, 1, 0, 0, tzinfo=UTC)
    return (
        _bars(start, base=110.0, step=0.2, count=40, minutes=5),
        _bars(start, base=108.0, step=0.4, count=30, minutes=15),
        _bars(start - timedelta(hours=20), base=100.0, step=0.8, count=30, minutes=60),
    )


def test_v322_active_source_primary_inside_source_and_exposes_micro_context() -> None:
    m5, m15, h1 = _inputs()
    result = build_micro_handoff_confluence(
        atlas_evaluation=_atlas(),
        bars_m5=m5,
        bars_m15=m15,
        bars_h1=h1,
        price_now=120.0,
    )
    assert result["contract"] == CONTRACT
    assert result["primary_setup_role"] == "ACTIVE_SOURCE_M5"
    assert result["direction"] == "SHORT"
    assert result["state"] == "ACTIVE_SOURCE_ZONE_MICRO_WATCH"
    context = result["active_source"]["micro_context"]
    assert context["state"] == "M5_TOUCH_WAIT_RECLAIM"
    assert context["sweep"]["price"] == 124.5
    assert context["mss_level"] == 116.5
    assert context["candidate_micro_pocket"]["low"] == 121.0
    assert result["source_no_chase"] is False


def test_v322_hands_focus_to_next_zone_after_source_moves_beyond_retest_window() -> None:
    m5, m15, h1 = _inputs()
    result = build_micro_handoff_confluence(
        atlas_evaluation=_atlas(),
        bars_m5=m5,
        bars_m15=m15,
        bars_h1=h1,
        price_now=108.0,
    )
    # Source supply low=118, ATR=12: 10/12=0.833 ATR > 0.75.
    assert result["active_source"]["distance_atr"] > SOURCE_RETEST_MAX_DISTANCE_ATR
    assert result["source_no_chase"] is True
    assert result["primary_setup_role"] == "NEXT_OPPOSING_M5"
    assert result["direction"] == "LONG"
    assert result["state"] == "SOURCE_MOVE_IN_FLIGHT_NO_CHASE_PREPARE_NEXT"


def test_v322_next_zone_wins_immediately_when_price_enters_it() -> None:
    m5, m15, h1 = _inputs()
    result = build_micro_handoff_confluence(
        atlas_evaluation=_atlas(),
        bars_m5=m5,
        bars_m15=m15,
        bars_h1=h1,
        price_now=95.0,
    )
    assert result["primary_setup_role"] == "NEXT_OPPOSING_M5"
    assert result["direction"] == "LONG"
    assert result["state"] == "NEXT_OPPOSING_ZONE_ENTERED"


def test_v322_is_context_only_and_never_authorizes_execution() -> None:
    m5, m15, h1 = _inputs()
    result = build_micro_handoff_confluence(
        atlas_evaluation=_atlas(),
        bars_m5=m5,
        bars_m15=m15,
        bars_h1=h1,
        price_now=120.0,
    )
    assert result["policy_effect"] == "RESEARCH_FORECAST_ONLY"
    assert result["execution_authority"] is False
    assert result["execution_influence"] is False
    assert result["live_execution_enabled"] is False

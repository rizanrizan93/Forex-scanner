from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fx_scanner.xau_rizan_micro_entry_dual_cycle_v321 import (
    CONTRACT,
    build_dual_cycle_micro_refinement,
)


def _bars(start: datetime, *, base: float, step: float, count: int, minutes: int) -> list[dict]:
    rows = []
    price = base
    for i in range(count):
        o = price
        c = price + step
        h = max(o, c) + 1.0
        l = min(o, c) - 1.0
        rows.append(
            {
                "time": (start + timedelta(minutes=i * minutes)).isoformat(),
                "open": o,
                "high": h,
                "low": l,
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
        "zones": [source, destination],
    }


def test_v321_prioritizes_active_source_when_price_is_inside_source_zone() -> None:
    start = datetime(2026, 10, 1, 0, 0, tzinfo=UTC)
    m5 = _bars(start, base=110.0, step=0.2, count=40, minutes=5)
    m15 = _bars(start, base=108.0, step=0.4, count=30, minutes=15)
    h1 = _bars(start - timedelta(hours=20), base=100.0, step=0.8, count=30, minutes=60)
    result = build_dual_cycle_micro_refinement(
        atlas_evaluation=_atlas(),
        bars_m5=m5,
        bars_m15=m15,
        bars_h1=h1,
        price_now=120.0,
    )
    assert result["contract"] == CONTRACT
    assert result["state"] == "ACTIVE_SOURCE_ZONE_MICRO_WATCH"
    assert result["primary_setup_role"] == "ACTIVE_SOURCE_M5"
    assert result["direction"] == "SHORT"
    assert result["active_source"]["m5"]["direction"] == "SHORT"
    assert result["next_opposing"]["m5"]["direction"] == "LONG"
    assert result["execution_authority"] is False


def test_v321_keeps_next_opposing_zone_visible_as_separate_cycle() -> None:
    start = datetime(2026, 10, 1, 0, 0, tzinfo=UTC)
    m5 = _bars(start, base=110.0, step=-0.1, count=40, minutes=5)
    m15 = _bars(start, base=112.0, step=-0.2, count=30, minutes=15)
    h1 = _bars(start - timedelta(hours=20), base=120.0, step=-0.5, count=30, minutes=60)
    result = build_dual_cycle_micro_refinement(
        atlas_evaluation=_atlas(),
        bars_m5=m5,
        bars_m15=m15,
        bars_h1=h1,
        price_now=110.0,
    )
    assert result["active_source"]["zone"]["zone_id"] == "source-supply"
    assert result["next_opposing"]["zone"]["zone_id"] == "next-demand"
    assert result["active_source"]["m5"]["selected_timeframe"] == "M5"
    assert result["active_source"]["h1"]["selected_timeframe"] == "H1"
    assert result["next_opposing"]["m5"]["selected_timeframe"] == "M5"
    assert result["next_opposing"]["h1"]["selected_timeframe"] == "H1"


def test_v321_prefers_next_zone_when_source_is_broken_side_and_destination_exists() -> None:
    atlas = _atlas()
    start = datetime(2026, 10, 1, 0, 0, tzinfo=UTC)
    m5 = _bars(start, base=130.0, step=0.1, count=30, minutes=5)
    m15 = _bars(start, base=126.0, step=0.2, count=30, minutes=15)
    h1 = _bars(start - timedelta(hours=20), base=115.0, step=0.7, count=30, minutes=60)
    result = build_dual_cycle_micro_refinement(
        atlas_evaluation=atlas,
        bars_m5=m5,
        bars_m15=m15,
        bars_h1=h1,
        price_now=135.0,
    )
    assert result["primary_setup_role"] == "NEXT_OPPOSING_M5"
    assert result["direction"] == "LONG"


def test_v321_never_has_broker_authority() -> None:
    start = datetime(2026, 10, 1, 0, 0, tzinfo=UTC)
    result = build_dual_cycle_micro_refinement(
        atlas_evaluation=_atlas(),
        bars_m5=_bars(start, base=110.0, step=0.2, count=30, minutes=5),
        bars_m15=_bars(start, base=110.0, step=0.2, count=30, minutes=15),
        bars_h1=_bars(start, base=110.0, step=0.2, count=30, minutes=60),
        price_now=120.0,
    )
    assert result["policy_effect"] == "RESEARCH_FORECAST_ONLY"
    assert result["execution_authority"] is False
    assert result["execution_influence"] is False
    assert result["live_execution_enabled"] is False

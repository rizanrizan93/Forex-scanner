from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd

from fx_scanner.research_xau_exhausted_demand_sweep_v351 import (
    _h2_cluster_below,
    _zone_timeline,
    aggregate_years,
    summarize,
)
from fx_scanner.xau_sd_liquidity_engine_v342 import SDZone


def _zone(tf: str = "H4", *, low: float = 100.0, high: float = 110.0) -> SDZone:
    return SDZone(
        zone_id=f"{tf}-z",
        timeframe=tf,
        direction="LONG",
        pattern="RBR",
        zone_class="STRUCTURAL_BOS",
        low=low,
        high=high,
        proximal=high - 1.0,
        distal=low,
        origin_at=datetime(2026, 1, 1, 0, 0, tzinfo=UTC),
        available_at=datetime(2026, 1, 1, 4 if tf == "H4" else 1, 0, tzinfo=UTC),
        atr=10.0,
        base_bars=1,
        base_range_atr=1.0,
        departure_range_atr=1.5,
        departure_body_fraction=0.8,
        structural_bos=True,
        score_seed=80.0,
    )


def test_v351_parent_becomes_near_exhausted_from_deep_mitigation():
    zone = _zone("H4")
    frame = pd.DataFrame(
        [
            {
                "timestamp": datetime(2026, 1, 1, 4, 0, tzinfo=UTC),
                "open": 112.0,
                "high": 113.0,
                "low": 111.0,
                "close": 112.0,
            },
            {
                "timestamp": datetime(2026, 1, 1, 8, 0, tzinfo=UTC),
                "open": 109.0,
                "high": 111.0,
                "low": 99.5,
                "close": 104.0,
            },
        ]
    )
    state = _zone_timeline(
        zone,
        frame,
        until=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
    )
    assert state["touch_count"] == 1
    assert state["mitigation_depth"] >= 0.95
    assert state["near_exhausted_at"] is not None
    assert state["invalidated_at"] is None


def test_v351_h2_cluster_is_preknown_and_below_fresh_h1():
    h1 = _zone("H1", low=100.0, high=104.0)
    as_of = datetime(2026, 1, 2, 0, 0, tzinfo=UTC)
    pivots = [
        {
            "kind": "SUPPORT",
            "price": 96.0,
            "available_at": as_of - timedelta(hours=4),
            "source": "H2_SWING_LOW",
        },
        {
            "kind": "RESISTANCE",
            "price": 96.8,
            "available_at": as_of - timedelta(hours=3),
            "source": "H2_SWING_HIGH",
        },
        {
            "kind": "SUPPORT",
            "price": 97.2,
            "available_at": as_of - timedelta(hours=2),
            "source": "H2_SWING_LOW",
        },
        {
            "kind": "SUPPORT",
            "price": 90.0,
            "available_at": as_of + timedelta(hours=1),
            "source": "H2_SWING_LOW",
        },
    ]
    cluster = _h2_cluster_below(pivots, as_of=as_of, h1_zone=h1)
    assert cluster
    assert cluster["low"] <= 96.0
    assert cluster["high"] >= 97.2
    assert cluster["strength"] == 3
    assert cluster["kind"] == "FLIP"


def test_v351_summary_separates_chain_stages():
    events = [
        {
            "year": 2025,
            "fresh_h1_available": True,
            "h2_cluster_available": True,
            "h1_touched": True,
            "h2_reached": True,
            "h2_before_parent_rebound": True,
            "confirmed": True,
            "opposing_supply_available": True,
            "clean_supply_hit": True,
            "minutes_exhausted_to_h1": 60.0,
            "minutes_h1_to_h2": 30.0,
            "sweep_extension_below_h1_atr": 0.8,
            "h2_cluster": {"strength": 4},
        },
        {
            "year": 2024,
            "fresh_h1_available": True,
            "h2_cluster_available": True,
            "h1_touched": True,
            "h2_reached": False,
            "h2_before_parent_rebound": False,
            "confirmed": False,
            "opposing_supply_available": False,
            "clean_supply_hit": False,
            "minutes_exhausted_to_h1": 90.0,
            "h2_cluster": {"strength": 2},
        },
    ]
    summary = summarize(events)
    assert summary["parent_exhausted_events"] == 2
    assert summary["h2_reached"] == 1
    assert summary["confirmation_after_h2"] == 1
    assert summary["clean_opposing_supply_hits"] == 1

    aggregate = aggregate_years(
        [
            {"year": 2024, "events": [events[1]]},
            {"year": 2025, "events": [events[0]]},
        ]
    )
    assert aggregate["periods"]["development_2012_2024"]["summary"]["parent_exhausted_events"] == 1
    assert aggregate["periods"]["oos_2025_2026"]["summary"]["parent_exhausted_events"] == 1
    assert aggregate["execution_authority"] is False

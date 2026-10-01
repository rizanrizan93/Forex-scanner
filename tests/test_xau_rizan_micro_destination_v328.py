from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fx_scanner.xau_rizan_micro_destination_v328 import (
    CONTRACT,
    build_opposing_zone_cascade,
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


def _zone(
    zone_id: str,
    *,
    direction: str,
    low: float,
    high: float,
    timeframe: str = "H1",
    touch_count: int = 0,
    mitigation_depth: float = 0.0,
) -> dict:
    return {
        "zone_id": zone_id,
        "timeframe": timeframe,
        "zone_class": "STRUCTURAL" if "source" in zone_id else "IMBALANCE",
        "pattern": (
            "STRUCTURAL_SUPPLY"
            if direction == "SHORT"
            else "DBR"
        ),
        "direction": direction,
        "low": low,
        "high": high,
        "proximal": high if direction == "LONG" else low,
        "distal": low if direction == "LONG" else high,
        "atr_points": max(high - low, 5.0),
        "status": (
            "IN_ZONE_PREPARE_ONLY"
            if touch_count
            else "ACTIVE_WATCH_PREPARE_ONLY"
        ),
        "lifecycle": {
            "active": True,
            "freshness": "FIRST_TEST" if touch_count else "FRESH",
            "touch_count": touch_count,
            "first_touch_at": (
                "2026-10-01T01:00:00+00:00" if touch_count else None
            ),
            "last_touch_at": (
                "2026-10-01T01:05:00+00:00" if touch_count else None
            ),
            "invalidated_at": None,
            "mitigation_depth": mitigation_depth,
        },
    }


def _atlas() -> dict:
    source = _zone(
        "source-supply",
        direction="SHORT",
        low=118.0,
        high=130.0,
        touch_count=1,
        mitigation_depth=0.35,
    )
    first = _zone(
        "first-demand",
        direction="LONG",
        low=90.0,
        high=100.0,
        touch_count=1,
        mitigation_depth=0.90,
    )
    deeper = _zone(
        "deeper-demand",
        direction="LONG",
        low=75.0,
        high=85.0,
        touch_count=0,
    )
    return {
        "path_map": {
            "active_path": {
                "source_zone": source,
                "primary_opposing_zone": first,
                "terminal_target_zone": first,
                "destination_stack": [first, deeper],
                "secondary_opposing_zones": [deeper],
            }
        },
        "m5_path_projection": {
            "current_leg": {
                "micro_refinement": {
                    "state": "M5_REFINEMENT_CONFIRMED_SHADOW",
                    "direction": "SHORT",
                    "sweep": {
                        "price": 124.5,
                        "at": "2026-10-01T01:10:00+00:00",
                    },
                    "mss_level": 116.5,
                    "mss_confirmed": True,
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
                    "fresh_micro_confirmed": True,
                },
            }
        },
        "zones": [source, first, deeper],
    }


def _inputs() -> tuple[list[dict], list[dict], list[dict]]:
    start = datetime(2026, 10, 1, 0, 0, tzinfo=UTC)
    return (
        _bars(start, base=110.0, step=-0.2, count=40, minutes=5),
        _bars(start, base=112.0, step=-0.4, count=30, minutes=15),
        _bars(
            start - timedelta(hours=20),
            base=120.0,
            step=-0.8,
            count=30,
            minutes=60,
        ),
    )


def test_v328_cascades_past_breached_primary_into_deeper_zone() -> None:
    m5, m15, h1 = _inputs()
    result = build_opposing_zone_cascade(
        atlas_evaluation=_atlas(),
        bars_m5=m5,
        bars_m15=m15,
        bars_h1=h1,
        price_now=80.0,
    )

    assert result["contract"] == CONTRACT
    assert result["state"] == "CASCADED_OPPOSING_ZONE_ENTERED"
    assert result["primary_setup_role"] == "NEXT_OPPOSING_M5"
    assert result["direction"] == "LONG"
    assert result["next_opposing"]["zone"]["zone_id"] == "deeper-demand"

    cascade = result["destination_cascade"]
    assert cascade["selected_rank"] == 2
    assert cascade["skipped_count"] == 1
    assert cascade["skipped_zones"][0]["zone_id"] == "first-demand"
    assert cascade["skipped_zones"][0]["reason"] == "LIVE_PRICE_BEYOND_DISTAL"

    liquidity = result["liquidity_sweep_context"]
    assert liquidity["state"] == "POSSIBLE_LIQUIDITY_SWEEP_OR_ACCEPTANCE"
    assert liquidity["requires_reclaim_or_structural_remap"] is True


def test_v328_keeps_first_opposing_zone_when_price_is_inside_it() -> None:
    m5, m15, h1 = _inputs()
    result = build_opposing_zone_cascade(
        atlas_evaluation=_atlas(),
        bars_m5=m5,
        bars_m15=m15,
        bars_h1=h1,
        price_now=95.0,
    )

    assert result["state"] == "NEXT_OPPOSING_ZONE_ENTERED"
    assert result["primary_setup_role"] == "NEXT_OPPOSING_M5"
    assert result["next_opposing"]["zone"]["zone_id"] == "first-demand"
    assert result["destination_cascade"]["selected_rank"] == 1
    assert result["destination_cascade"]["skipped_count"] == 0


def test_v328_waits_for_structural_remap_when_all_opposing_zones_are_breached() -> None:
    m5, m15, h1 = _inputs()
    result = build_opposing_zone_cascade(
        atlas_evaluation=_atlas(),
        bars_m5=m5,
        bars_m15=m15,
        bars_h1=h1,
        price_now=70.0,
    )

    assert result["state"] == "WAIT_STRUCTURAL_REMAP_AFTER_OPPOSING_BREACH"
    assert result["primary_setup_role"] == "NONE"
    assert result["direction"] is None
    assert result["decision_zone"] is None
    assert result["levels"] is None
    assert result["next_opposing"]["zone"] == {}
    assert result["destination_cascade"]["skipped_count"] == 2


def test_v328_rejects_explicitly_invalidated_zone_before_selecting_deeper() -> None:
    atlas = _atlas()
    first = atlas["path_map"]["active_path"]["primary_opposing_zone"]
    first["lifecycle"]["invalidated_at"] = "2026-10-01T02:00:00+00:00"
    m5, m15, h1 = _inputs()

    result = build_opposing_zone_cascade(
        atlas_evaluation=atlas,
        bars_m5=m5,
        bars_m15=m15,
        bars_h1=h1,
        price_now=80.0,
    )

    assert result["next_opposing"]["zone"]["zone_id"] == "deeper-demand"
    skipped = result["destination_cascade"]["skipped_zones"]
    assert skipped[0]["zone_id"] == "first-demand"
    assert skipped[0]["reason"] == "ZONE_INACTIVE_BROKEN_OR_INVALID"


def test_v328_never_authorizes_execution() -> None:
    m5, m15, h1 = _inputs()
    result = build_opposing_zone_cascade(
        atlas_evaluation=_atlas(),
        bars_m5=m5,
        bars_m15=m15,
        bars_h1=h1,
        price_now=80.0,
    )
    assert result["policy_effect"] == "RESEARCH_FORECAST_ONLY"
    assert result["execution_authority"] is False
    assert result["execution_influence"] is False
    assert result["live_execution_enabled"] is False

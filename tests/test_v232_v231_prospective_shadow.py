from datetime import UTC, datetime, timedelta
from pathlib import Path

from fx_scanner.demo_xau_v232_v231_prospective_shadow import (
    build_shadow_forecasts,
    evaluate_shadow_order,
)
from fx_scanner.models import Bar

ROOT = Path(__file__).resolve().parents[1]


def _bar(ts: datetime, *, o: float, h: float, l: float, c: float) -> Bar:
    return Bar(
        symbol="XAUUSD",
        timeframe="M1",
        timestamp=ts,
        open=o,
        high=h,
        low=l,
        close=c,
        tick_count=100,
        spread_avg=0.2,
        spread_max=0.3,
    )


def _source(*, source_layer: str = "M15_NESTED_LOCATOR", direction: str = "LONG") -> dict:
    candidate = {
        "candidate_type": "DEPTH_ENTRY_CANDIDATE",
        "direction": direction,
        "entry_low": 105.5,
        "entry_high": 107.5,
        "entry_reference": 106.3,
        "source_layer": source_layer,
        "approach_state": "AHEAD",
        "display_status": "PREPARE_ONLY_FRESH_FIRST_TOUCH",
        "calibrated_fresh_first_touch": True,
    }
    h4 = {
        "zone": {
            "zone_id": "h4-zone",
            "low": 100.0,
            "high": 110.0,
            "atr_points": 10.0,
        }
    }
    return {
        "observed_at": "2026-09-25T12:00:00+00:00",
        "healthy": True,
        "details": {
            "code_version": "v226sha",
            "evaluation": {
                "state": "RIZAN_DEPTH_MAP_AVAILABLE",
                "focus_direction": direction,
                "depth_entry_candidate": candidate,
                direction.lower(): {
                    "h4": h4,
                    "depth_entry_candidate": candidate,
                },
            },
        },
    }


def _atlas(*, direction: str = "LONG", terminal: float = 120.0) -> dict:
    path_key = "demand_to_supply" if direction == "LONG" else "supply_to_demand"
    terminal_zone = (
        {"low": terminal, "high": terminal + 2.0}
        if direction == "LONG"
        else {"low": terminal - 2.0, "high": terminal}
    )
    return {
        "observed_at": "2026-09-25T12:00:00+00:00",
        "healthy": True,
        "details": {
            "evaluation": {
                "path_map": {
                    path_key: {
                        "terminal_target_zone": terminal_zone,
                    }
                }
            }
        },
    }


def test_v232_builds_two_terminal_only_nested_shadow_orders() -> None:
    rows = build_shadow_forecasts(
        source_heartbeat=_source(),
        atlas_heartbeat=_atlas(),
    )
    assert [row["slot"] for row in rows] == ["NEAR_EDGE", "REFERENCE"]
    assert all(row["source_layer"] == "M15_NESTED_LOCATOR" for row in rows)
    assert all(row["target_source"] == "ATLAS_TERMINAL_OPPOSING_ZONE" for row in rows)
    assert all(row["rr"] >= 1.0 for row in rows)
    assert all(row["sl"] == 98.5 for row in rows)
    assert all(row["tp"] == 120.0 for row in rows)
    assert all(row["execution_authority"] is False for row in rows)
    assert all(row["risk_percent_filter"] is None for row in rows)


def test_v232_rejects_h4_only_and_missing_or_bad_terminal_target() -> None:
    assert build_shadow_forecasts(
        source_heartbeat=_source(source_layer="H4_HISTORICAL_HOTSPOT"),
        atlas_heartbeat=_atlas(),
    ) == []
    assert build_shadow_forecasts(
        source_heartbeat=_source(),
        atlas_heartbeat={
            "observed_at": "2026-09-25T12:00:00+00:00",
            "healthy": True,
            "details": {"evaluation": {"path_map": {}}},
        },
    ) == []
    # Favorable but too close to provide RR >= 1 from either entry.
    assert build_shadow_forecasts(
        source_heartbeat=_source(),
        atlas_heartbeat=_atlas(terminal=108.0),
    ) == []


def test_v232_short_geometry_is_symmetric() -> None:
    source = _source(direction="SHORT")
    source["details"]["evaluation"]["depth_entry_candidate"]["entry_low"] = 102.5
    source["details"]["evaluation"]["depth_entry_candidate"]["entry_high"] = 104.5
    source["details"]["evaluation"]["depth_entry_candidate"]["entry_reference"] = 103.7
    side = source["details"]["evaluation"]["short"]
    side["depth_entry_candidate"] = source["details"]["evaluation"]["depth_entry_candidate"]

    rows = build_shadow_forecasts(
        source_heartbeat=source,
        atlas_heartbeat=_atlas(direction="SHORT", terminal=85.0),
    )
    assert len(rows) == 2
    assert rows[0]["entry"] == 102.5
    assert rows[0]["sl"] == 111.5
    assert rows[0]["tp"] == 85.0
    assert rows[0]["rr"] >= 1.0


def test_v232_stop_wins_on_fill_bar_and_tp_requires_future_bar() -> None:
    forecast = build_shadow_forecasts(
        source_heartbeat=_source(),
        atlas_heartbeat=_atlas(),
    )[0]
    start = datetime(2026, 9, 25, 12, 1, tzinfo=UTC)

    stopped = evaluate_shadow_order(
        [
            _bar(start, o=111.0, h=108.0, l=98.0, c=106.0),
        ],
        forecast=forecast,
        now=start + timedelta(minutes=2),
    )
    assert stopped["status"] == "SL_ENTRY_BAR_CONSERVATIVE"

    pending = evaluate_shadow_order(
        [
            # Entry and TP both print on fill bar, but TP is not credited.
            _bar(start, o=111.0, h=121.0, l=107.0, c=118.0),
        ],
        forecast=forecast,
        now=start + timedelta(minutes=2),
    )
    assert pending["status"] == "PENDING_EXIT"


def test_v232_scores_future_tp_and_16h_time_exit() -> None:
    forecast = build_shadow_forecasts(
        source_heartbeat=_source(),
        atlas_heartbeat=_atlas(),
    )[0]
    start = datetime(2026, 9, 25, 12, 1, tzinfo=UTC)

    tp = evaluate_shadow_order(
        [
            _bar(start, o=111.0, h=108.0, l=107.0, c=107.5),
            _bar(start + timedelta(minutes=1), o=107.5, h=121.0, l=106.0, c=120.5),
        ],
        forecast=forecast,
        now=start + timedelta(minutes=3),
    )
    assert tp["status"] == "TP"
    assert tp["gross_pnl_usd"] > 0

    timeout = evaluate_shadow_order(
        [
            _bar(start, o=111.0, h=108.0, l=107.0, c=107.5),
            _bar(start + timedelta(hours=15), o=107.5, h=110.0, l=104.0, c=109.0),
        ],
        forecast=forecast,
        now=start + timedelta(hours=16, minutes=2),
    )
    assert timeout["status"] == "TIME_EXIT_16H"


def test_v232_is_maintenance_shadow_only() -> None:
    source = (
        ROOT / "src/fx_scanner/demo_xau_v232_v231_prospective_shadow.py"
    ).read_text()
    assert '"execution_influence": False' in source
    assert '"execution_authority": False' in source
    assert '"promotion_authority": False' in source
    assert 'TARGET_SOURCE = "ATLAS_TERMINAL_OPPOSING_ZONE"' in source
    assert 'ALLOWED_SOURCES = {"H1_NESTED_LOCATOR", "M15_NESTED_LOCATOR"}' in source
    assert 'risk_percent_filter": None' in source

    workflow = (
        ROOT / ".github/workflows/ctrader-demo-maintenance-pipeline.yml"
    ).read_text()
    assert "python -m fx_scanner.demo_xau_v232_v231_prospective_shadow" in workflow
    assert workflow.index("demo_xau_v227_depth_map_prospective") < workflow.index(
        "demo_xau_v232_v231_prospective_shadow"
    )

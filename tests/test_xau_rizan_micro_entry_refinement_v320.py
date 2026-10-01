from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fx_scanner.xau_rizan_micro_entry_refinement_v320 import (
    CONTRACT,
    STEP_ATR_FRACTION,
    build_micro_entry_refinement,
)


def _bars(
    rows: list[tuple[float, float, float, float]],
    *,
    start: datetime,
    minutes: int = 5,
) -> list[dict]:
    output = []
    for i, (o, h, l, c) in enumerate(rows):
        output.append(
            {
                "time": (start + timedelta(minutes=i * minutes)).isoformat(),
                "open": o,
                "high": h,
                "low": l,
                "close": c,
            }
        )
    return output


def _atlas_with_zone(direction: str) -> dict:
    zone = {
        "zone_id": "decision-zone",
        "timeframe": "H1",
        "zone_class": "IMBALANCE",
        "pattern": "DBR" if direction == "LONG" else "RBD",
        "direction": direction,
        "low": 100.0,
        "high": 110.0,
        "proximal": 110.0 if direction == "LONG" else 100.0,
        "distal": 100.0 if direction == "LONG" else 110.0,
        "atr_points": 8.0,
        "status": "ACTIVE_WATCH_PREPARE_ONLY",
        "lifecycle": {"active": True, "freshness": "FRESH"},
    }
    opposite = {
        "zone_id": "opposing",
        "timeframe": "H1",
        "direction": "SHORT" if direction == "LONG" else "LONG",
        "low": 130.0 if direction == "LONG" else 70.0,
        "high": 140.0 if direction == "LONG" else 80.0,
        "proximal": 130.0 if direction == "LONG" else 80.0,
        "distal": 140.0 if direction == "LONG" else 70.0,
        "status": "ACTIVE_WATCH_PREPARE_ONLY",
        "lifecycle": {"active": True, "freshness": "FRESH"},
    }
    return {
        "path_map": {
            "active_path": {
                "reaction_direction": "SHORT" if direction == "LONG" else "LONG",
                "primary_opposing_zone": zone,
                "terminal_target_zone": zone,
            }
        },
        "zones": [zone, opposite],
    }


def test_v320_long_reconstructs_a_x_y_and_5_8_13_delta_ladder() -> None:
    start = datetime(2026, 10, 1, 0, 0, tzinfo=UTC)
    rows = [
        (116, 117, 114, 115),
        (115, 116, 113, 114),
        (114, 115, 108, 111),  # touch decision zone
        (111, 114, 110, 113),
        (113, 118, 112, 117),
        (117, 120, 116, 119),  # impulse away
        (119, 119.5, 114.5, 115.5),
        (115.5, 117, 113.0, 114.0),  # candidate higher-low pivot A
        (114.0, 118, 114.2, 117.5),
        (117.5, 121, 117, 120),
        (120, 122, 119, 121),
        (121, 123, 120, 122),
        (122, 124, 121, 123),
        (123, 125, 122, 124),
        (124, 126, 123, 125),
        (125, 127, 124, 126),
    ]
    bars = _bars(rows, start=start)
    result = build_micro_entry_refinement(
        atlas_evaluation=_atlas_with_zone("LONG"),
        bars_m5=bars,
        bars_m15=[],
        price_now=120.0,
    )
    assert result["contract"] == CONTRACT
    assert result["direction"] == "LONG"
    assert result["state"] == "MICRO_LADDER_CONFIRMED"
    assert result["anchor"]["confirmed"] is True
    assert abs(result["levels"]["a"] - 113.0) < 1e-9

    delta = result["delta"]["value"]
    assert abs(result["levels"]["x"] - (113.0 + delta)) < 1e-9
    assert abs(result["levels"]["y"] - (113.0 + 2 * delta)) < 1e-9
    assert abs(result["levels"]["tp1"] - (113.0 + 5 * delta)) < 1e-9
    assert abs(result["levels"]["tp2"] - (113.0 + 8 * delta)) < 1e-9
    assert abs(result["levels"]["tp3"] - (113.0 + 13 * delta)) < 1e-9
    assert result["levels"]["sl"] < 100.0
    assert result["reclaim_confirmed"] is True
    assert result["execution_authority"] is False


def test_v320_projects_ladder_before_touch_but_does_not_mark_entries_eligible() -> None:
    start = datetime(2026, 10, 1, 0, 0, tzinfo=UTC)
    rows = [
        (120 + i * 0.2, 122 + i * 0.2, 119 + i * 0.2, 121 + i * 0.2)
        for i in range(20)
    ]
    result = build_micro_entry_refinement(
        atlas_evaluation=_atlas_with_zone("LONG"),
        bars_m5=_bars(rows, start=start),
        bars_m15=[],
        price_now=124.0,
    )
    assert result["state"] == "MICRO_LADDER_PROJECTED_WAIT_A"
    assert result["anchor"]["confirmed"] is False
    assert result["phase"] == "WAIT_ANCHOR_A"
    assert all(not row["eligible"] for row in result["entries"])
    assert result["delta"]["verified_original_formula"] is False


def test_v320_short_mirrors_ladder_and_structural_stop() -> None:
    start = datetime(2026, 10, 1, 0, 0, tzinfo=UTC)
    rows = [
        (94, 96, 92, 93),
        (93, 101, 92, 99),  # touches supply 100-110
        (99, 100, 96, 97),
        (97, 98, 92, 93),
        (93, 94, 88, 89),
        (89, 94, 88.5, 93),  # pullback starts
        (93, 96.0, 92, 94),  # candidate lower-high pivot A
        (94, 94.5, 90, 91),
        (91, 92, 87, 88),
        (88, 89, 85, 86),
        (86, 87, 83, 84),
        (84, 85, 81, 82),
        (82, 83, 79, 80),
        (80, 81, 77, 78),
        (78, 79, 75, 76),
        (76, 77, 73, 74),
    ]
    result = build_micro_entry_refinement(
        atlas_evaluation=_atlas_with_zone("SHORT"),
        bars_m5=_bars(rows, start=start),
        bars_m15=[],
        price_now=90.0,
    )
    assert result["direction"] == "SHORT"
    assert result["levels"]["x"] < result["levels"]["a"]
    assert result["levels"]["y"] < result["levels"]["x"]
    assert result["levels"]["tp1"] < result["levels"]["y"]
    assert result["levels"]["sl"] > 110.0


def test_v320_contract_is_reconstruction_not_claimed_exact_clone() -> None:
    assert STEP_ATR_FRACTION == 0.22
    start = datetime(2026, 10, 1, 0, 0, tzinfo=UTC)
    rows = [
        (120 + i, 122 + i, 119 + i, 121 + i)
        for i in range(20)
    ]
    result = build_micro_entry_refinement(
        atlas_evaluation=_atlas_with_zone("LONG"),
        bars_m5=_bars(rows, start=start),
        bars_m15=[],
        price_now=140.0,
    )
    assert result["policy_effect"] == "RESEARCH_FORECAST_ONLY"
    assert result["execution_influence"] is False
    assert result["live_execution_enabled"] is False
    assert "original proprietary indicator formula is unknown" in result["interpretation"]

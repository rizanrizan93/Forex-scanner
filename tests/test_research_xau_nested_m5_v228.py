from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd

from fx_scanner.demo_xau_supply_demand_atlas_v182 import SDZone
from fx_scanner.research_xau_nested_m5_v228 import (
    EXECUTION_AUTHORITY,
    LADDER_QUANTILES,
    _detect_m5_zones,
    _ladder_report,
    _m15_probability_geometry,
    _probability_weighted_m5_key,
)

ROOT = Path(__file__).resolve().parents[1]


def test_v228_m5_zone_is_available_only_after_departure_close() -> None:
    start = datetime(2026, 9, 25, 0, tzinfo=UTC)
    rows = []
    for i in range(19):
        rows.append(
            {
                "time": start + timedelta(minutes=5 * i),
                "open": 100.0,
                "high": 100.4,
                "low": 99.6,
                "close": 100.0 if i % 2 == 0 else 99.9,
            }
        )
    departure_open = start + timedelta(minutes=5 * 19)
    rows.append(
        {
            "time": departure_open,
            "open": 100.0,
            "high": 106.0,
            "low": 99.8,
            "close": 105.5,
        }
    )
    zones = _detect_m5_zones(pd.DataFrame(rows))
    assert zones
    zone = zones[-1]
    assert zone.timeframe == "M5"
    assert zone.available_at == departure_open + timedelta(minutes=5)
    assert zone.departure_at == zone.available_at


def test_v228_four_slot_ladder_is_monotonic_and_balances_fill() -> None:
    depths = [i / 100.0 for i in range(1, 96)]
    report = _ladder_report(depths)
    assert report["n"] == len(depths)
    assert len(report["depths"]) == 4
    assert report["depths"] == sorted(report["depths"])
    assert report["any_fill_rate"] >= 0.89
    assert 1.9 <= report["mean_filled_orders"] <= 2.2
    assert tuple(report["quantiles"]) == LADDER_QUANTILES


def test_v228_workflow_is_2012_2026_shadow_only() -> None:
    workflow = (ROOT / ".github/workflows/research-xau-nested-m5-depth-v228.yml").read_text()
    assert "2012" in workflow and "2026" in workflow
    assert "research_xau_histdata_download_v193" in workflow
    assert "research_xau_nested_m5_v228_year_runtime" in workflow
    assert EXECUTION_AUTHORITY is False
    source = (ROOT / "src/fx_scanner/research_xau_nested_m5_v228.py").read_text()
    assert 'POLICY_EFFECT = "SHADOW_ONLY"' in source
    assert "EXECUTION_INFLUENCE = False" in source
    assert "EXECUTION_AUTHORITY = False" in source


def _sd_zone(
    zone_id: str,
    *,
    direction: str = "LONG",
    low: float,
    high: float,
    available_at: datetime,
    timeframe: str,
) -> SDZone:
    return SDZone(
        zone_id=zone_id,
        timeframe=timeframe,
        zone_class="IMBALANCE",
        pattern="DBR" if direction == "LONG" else "RBD",
        direction=direction,
        low=low,
        high=high,
        proximal=high if direction == "LONG" else low,
        distal=low if direction == "LONG" else high,
        available_at=available_at,
        origin_at=available_at - timedelta(minutes=10),
        departure_at=available_at,
        atr_points=5.0,
        base_bars=1,
        base_range_atr=(high - low) / 5.0,
        departure_range_atr=1.2,
        departure_body_fraction=0.7,
        structural_bos=False,
    )


def test_v228_probability_weighted_selector_prefers_m15_probability_corridor() -> None:
    now = datetime(2026, 9, 25, 12, tzinfo=UTC)
    parent = _sd_zone(
        "m15-parent",
        low=100.0,
        high=110.0,
        available_at=now - timedelta(hours=2),
        timeframe="M15",
    )
    # Narrower but far from the frozen V225.2 M15 reversal corridor.
    narrow_off_corridor = _sd_zone(
        "off",
        low=100.5,
        high=101.0,
        available_at=now - timedelta(minutes=20),
        timeframe="M5",
    )
    # Slightly wider, but centered around the frozen M15 median reversal price.
    probability_aligned = _sd_zone(
        "aligned",
        low=107.0,
        high=108.2,
        available_at=now - timedelta(minutes=30),
        timeframe="M5",
    )

    geometry = _m15_probability_geometry(parent)
    assert geometry["corridor_low"] < geometry["median_price"] < geometry["corridor_high"]

    ranked = sorted(
        [narrow_off_corridor, probability_aligned],
        key=lambda zone: _probability_weighted_m5_key(zone, parent=parent),
    )
    assert ranked[0].zone_id == "aligned"

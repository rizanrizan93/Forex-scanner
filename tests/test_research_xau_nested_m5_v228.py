from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd

from fx_scanner.research_xau_nested_m5_v228 import (
    EXECUTION_AUTHORITY,
    LADDER_QUANTILES,
    _detect_m5_zones,
    _ladder_report,
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

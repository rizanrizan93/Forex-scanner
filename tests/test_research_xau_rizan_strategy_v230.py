from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd

from fx_scanner.research_xau_rizan_strategy_v230 import (
    _candidate_geometry,
    _exit_child,
    apply_account_cap,
    frozen_ladder_depths,
)
from fx_scanner.research_xau_zone_reversal_depth_v225 import SDZone

ROOT = Path(__file__).resolve().parents[1]


def _zone(zone_id: str, timeframe: str, direction: str, low: float, high: float) -> SDZone:
    now = datetime(2026, 9, 25, tzinfo=UTC)
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
        available_at=now,
        origin_at=now - timedelta(hours=1),
        departure_at=now,
        atr_points=4.0,
        base_bars=1,
        base_range_atr=(high-low)/4.0,
        departure_range_atr=1.2,
        departure_body_fraction=0.7,
        structural_bos=False,
    )


def test_v230_frozen_depths_match_current_v2252_production_priors():
    h4_long = frozen_ladder_depths("H4", "LONG")
    m15_short = frozen_ladder_depths("M15", "SHORT")
    assert [round(x, 6) for x in h4_long] == [0.030782, 0.115227, 0.286335, 0.599159]
    assert [round(x, 6) for x in m15_short] == [0.031895, 0.11985, 0.280978, 0.607029]


def test_v230_candidate_prefers_nested_m15_then_h1_then_h4():
    h4 = _zone("h4", "H4", "LONG", 100.0, 120.0)
    h1 = _zone("h1", "H1", "LONG", 106.0, 116.0)
    m15 = _zone("m15", "M15", "LONG", 109.0, 114.0)

    source, geometry = _candidate_geometry(h4=h4, h1=h1, m15=m15)
    assert source == "M15"
    assert 100.0 <= geometry["low"] < geometry["high"] <= 120.0

    source_h1, geometry_h1 = _candidate_geometry(h4=h4, h1=h1, m15=None)
    assert source_h1 == "H1"
    assert geometry_h1

    source_h4, geometry_h4 = _candidate_geometry(h4=h4, h1=None, m15=None)
    assert source_h4 == "H4"
    assert geometry_h4


def test_v230_same_m1_tp_sl_ambiguity_is_stop_first_conservative():
    start = datetime(2026, 9, 25, 12, tzinfo=UTC)
    frame = pd.DataFrame(
        [
            {
                "timestamp": start,
                "open": 100.0,
                "high": 112.0,
                "low": 89.0,
                "close": 105.0,
            }
        ]
    )
    result = _exit_child(
        frame,
        direction="LONG",
        fill_at=start,
        entry=100.0,
        stop=90.0,
        target=110.0,
        end_at=start + timedelta(minutes=1),
    )
    assert result["outcome"] == "SL"
    assert result["pnl_r"] == -1.0


def test_v230_account_cap_rejects_eleventh_overlapping_child():
    start = datetime(2026, 9, 25, 12, tzinfo=UTC)
    records = []
    for i in range(11):
        records.append(
            {
                "signal_key": f"s{i}",
                "year": 2026,
                "direction": "LONG",
                "children": [
                    {
                        "signal_key": f"s{i}",
                        "slot": 1,
                        "direction": "LONG",
                        "fill_at": (start + timedelta(seconds=i)).isoformat(),
                        "exit_at": (start + timedelta(hours=1)).isoformat(),
                        "outcome": "TP",
                        "pnl_r": 1.0,
                        "pnl_usd": 1.0,
                    }
                ],
            }
        )
    rows = apply_account_cap(records, cap=10)
    assert sum(bool(row["account_cap_accepted"]) for row in rows) == 10
    assert sum(not bool(row["account_cap_accepted"]) for row in rows) == 1


def test_v230_workflow_covers_all_years_and_replay_has_no_turning_price_selector():
    workflow = (ROOT / ".github/workflows/research-xau-rizan-strategy-v230.yml").read_text()
    for year in range(2012, 2027):
        assert str(year) in workflow
    source = (ROOT / "src/fx_scanner/research_xau_rizan_strategy_v230.py").read_text()
    assert "turning_price" not in source
    assert "FROZEN_V2252" in (
        ROOT / "src/fx_scanner/research_xau_rizan_strategy_v230_year_runtime.py"
    ).read_text()

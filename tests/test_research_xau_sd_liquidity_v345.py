from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd

from fx_scanner.xau_sd_liquidity_engine_v342 import SDZone
from fx_scanner.research_xau_sd_liquidity_v345 import (
    aggregate_years,
    evaluate_first_touch,
)


def _zone() -> SDZone:
    return SDZone(
        zone_id="z1",
        timeframe="H1",
        direction="LONG",
        pattern="DBR",
        zone_class="STRUCTURAL_BOS",
        low=100.0,
        high=101.0,
        proximal=100.8,
        distal=100.0,
        origin_at=datetime(2026, 1, 1, 0, 0, tzinfo=UTC),
        available_at=datetime(2026, 1, 1, 1, 0, tzinfo=UTC),
        atr=2.0,
        base_bars=1,
        base_range_atr=0.5,
        departure_range_atr=1.4,
        departure_body_fraction=0.8,
        structural_bos=True,
        score_seed=80.0,
    )


def test_v345_distinguishes_liquidity_sweep_before_reversal():
    start = datetime(2026, 1, 1, 1, 0, tzinfo=UTC)
    rows = [
        # first touch
        (100.9, 101.1, 100.4, 100.7),
        # sweep below distal but close back above invalidation threshold 99.90
        (100.7, 100.9, 99.5, 100.3),
        # recover
        (100.3, 101.3, 100.2, 101.1),
        # reach target 101.8
        (101.1, 102.0, 101.0, 101.9),
    ]
    frame = pd.DataFrame(
        [
            {
                "timestamp": start + timedelta(minutes=i),
                "open": o,
                "high": h,
                "low": l,
                "close": c,
            }
            for i, (o, h, l, c) in enumerate(rows)
        ]
    )
    # Add enough future data to observe the full horizon contract.
    tail = pd.DataFrame(
        [
            {
                "timestamp": start + timedelta(minutes=4 + i),
                "open": 101.9,
                "high": 102.0,
                "low": 101.8,
                "close": 101.9,
            }
            for i in range(12 * 60 + 2)
        ]
    )
    frame = pd.concat([frame, tail], ignore_index=True)
    event = evaluate_first_touch(frame, zone=_zone())
    assert event is not None
    assert event["reaction_hit"] is True
    assert event["reversal_after_sweep"] is True
    assert event["outcome"] == "HOLD_050_AFTER_SWEEP"
    assert abs(event["sweep_extension_atr"] - 0.25) < 1e-9


def test_v345_aggregate_keeps_development_and_oos_separate():
    base = {
        "timeframe": "H1",
        "direction": "LONG",
        "pattern": "DBR",
        "zone_class": "STRUCTURAL_BOS",
        "structural_bos": True,
        "departure_range_atr": 1.4,
        "reaction_hit": True,
        "break_hit": False,
        "reversal_after_sweep": False,
        "outcome": "HOLD_050_DIRECT",
        "turning_depth": 0.2,
        "sweep_extension_atr": 0.0,
    }
    shards = [
        {
            "year": 2024,
            "zone_catalog": [],
            "episodes": [{**base, "touch_at": "2024-06-01T00:00:00+00:00"}],
        },
        {
            "year": 2025,
            "zone_catalog": [],
            "episodes": [{**base, "touch_at": "2025-06-01T00:00:00+00:00"}],
        },
    ]
    result = aggregate_years(shards)
    assert result["periods"]["development_2012_2024"]["summary"]["ALL"]["touches"] == 1
    assert result["periods"]["oos_2025_2026"]["summary"]["ALL"]["touches"] == 1
    assert result["execution_authority"] is False

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd

from fx_scanner.research_xau_zone_touch_decay_v352 import (
    _bucket,
    _summary,
    aggregate_years,
    evaluate_zone_touches,
)
from fx_scanner.xau_sd_liquidity_engine_v342 import SDZone


def _zone(direction: str = "LONG") -> SDZone:
    return SDZone(
        zone_id=f"z-{direction}",
        timeframe="H1",
        direction=direction,
        pattern="RBR" if direction == "LONG" else "RBD",
        zone_class="STRUCTURAL_BOS",
        low=100.0,
        high=101.0,
        proximal=100.8 if direction == "LONG" else 100.2,
        distal=100.0 if direction == "LONG" else 101.0,
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


def _frame(rows):
    start = datetime(2026, 1, 1, 1, 0, tzinfo=UTC)
    out = [
        {
            "timestamp": start + timedelta(minutes=i),
            "open": o,
            "high": h,
            "low": l,
            "close": c,
        }
        for i, (o, h, l, c) in enumerate(rows)
    ]
    last = rows[-1][-1]
    out.extend(
        {
            "timestamp": start + timedelta(minutes=len(rows) + i),
            "open": last,
            "high": last + 0.05,
            "low": last - 0.05,
            "close": last,
        }
        for i in range(12 * 60 + 10)
    )
    return pd.DataFrame(out)


def test_v352_bucket_semantics_zero_means_fresh_first_touch():
    assert _bucket(0) == "0"
    assert _bucket(1) == "1"
    assert _bucket(4) == "4"
    assert _bucket(5) == "5+"
    assert _bucket(8) == "5+"


def test_v352_first_touch_direct_reversal_is_zero_prior_touch():
    frame = _frame(
        [
            (101.2, 101.3, 100.7, 100.9),
            (100.9, 101.0, 100.4, 100.7),
            (100.7, 101.9, 100.6, 101.8),
        ]
    )
    rows = evaluate_zone_touches(frame, zone=_zone())
    assert rows
    first = rows[0]
    assert first["prior_touch_count"] == 0
    assert first["touch_bucket"] == "0"
    assert first["reaction_hit"] is True
    assert first["direct_reversal"] is True


def test_v352_sweep_reversal_is_separate_from_direct_reversal():
    frame = _frame(
        [
            (101.1, 101.2, 100.4, 100.8),
            (100.8, 100.9, 99.7, 100.3),
            (100.3, 102.0, 100.2, 101.9),
        ]
    )
    rows = evaluate_zone_touches(frame, zone=_zone())
    first = rows[0]
    assert first["reaction_hit"] is True
    assert first["sweep_seen"] is True
    assert first["reversal_after_sweep"] is True
    assert first["direct_reversal"] is False


def test_v352_retouch_before_target_is_not_a_reversal_for_prior_touch():
    frame = _frame(
        [
            (101.1, 101.2, 100.4, 100.8),  # first touch
            (100.8, 101.1, 100.7, 101.05), # exits above zone
            (101.05, 101.1, 100.8, 100.95),# re-touch before +0.5 ATR target
            (100.95, 102.0, 100.9, 101.9),
        ]
    )
    rows = evaluate_zone_touches(frame, zone=_zone())
    assert rows[0]["outcome"] == "RETOUCH_BEFORE_050"
    assert rows[0]["reaction_hit"] is False


def test_v352_summary_and_oos_are_separate():
    base = {
        "timeframe": "H4",
        "direction": "LONG",
        "touch_bucket": "0",
        "reaction_hit": True,
        "direct_reversal": True,
        "sweep_seen": False,
        "reversal_after_sweep": False,
        "break_hit": False,
        "retouch_before_reversal": False,
        "outcome": "REVERSAL_050_DIRECT",
        "turning_depth": 0.2,
        "sweep_extension_atr": 0.0,
    }
    agg = aggregate_years(
        [
            {"year": 2024, "episodes": [{**base, "touch_at": "2024-01-01T00:00:00+00:00"}]},
            {"year": 2025, "episodes": [{**base, "touch_at": "2025-01-01T00:00:00+00:00"}]},
        ]
    )
    assert agg["periods"]["development_2012_2024"]["summary"]["H4"]["ALL"]["0"]["episodes"] == 1
    assert agg["periods"]["oos_2025_2026"]["summary"]["H4"]["ALL"]["0"]["episodes"] == 1
    assert _summary([{**base}])["reversal_rate"] == 1.0

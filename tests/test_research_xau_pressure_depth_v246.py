from datetime import UTC, datetime, timedelta

import pandas as pd

from fx_scanner.research_xau_pressure_depth_v246 import (
    condition_depth_episodes,
    opposing_pressure_bucket,
    pressure_depth_report,
    pressure_features_before_touch,
)
from fx_scanner.research_xau_zone_reversal_depth_v225 import DepthEpisode


def _frame(direction: str = "DOWN"):
    start = datetime(2026, 1, 2, 0, 0, tzinfo=UTC)
    rows = []
    price = 4300.0
    for i in range(12):
        if direction == "DOWN":
            o = price
            c = price - 1.0
            h = o + 0.15
            l = c - 0.15
            price = c
        else:
            o = price
            c = price + 1.0
            h = c + 0.15
            l = o - 0.15
            price = c
        rows.append(
            {
                "timestamp": start + timedelta(minutes=i),
                "open": o,
                "high": h,
                "low": l,
                "close": c,
            }
        )
    return pd.DataFrame(rows)


def _episode(direction: str, touch_at: datetime) -> DepthEpisode:
    return DepthEpisode(
        zone_id="Z1",
        timeframe="H1",
        zone_class="IMBALANCE",
        pattern="RBR" if direction == "LONG" else "DBD",
        direction=direction,
        available_at=touch_at - timedelta(hours=1),
        touch_at=touch_at,
        outcome_at=touch_at + timedelta(minutes=30),
        zone_low=4280.0,
        zone_high=4290.0,
        proximal=4290.0 if direction == "LONG" else 4280.0,
        distal=4280.0 if direction == "LONG" else 4290.0,
        atr_points=10.0,
        zone_width=10.0,
        outcome="HOLD_050",
        reaction_hit=True,
        break_hit=False,
        max_depth_reached=0.6,
        turning_depth=0.6,
        turning_price=4284.0,
        minutes_to_outcome=30.0,
        departure_range_atr=1.2,
        departure_body_fraction=0.7,
        base_range_atr=0.8,
        structural_bos=False,
    )


def test_pressure_proxy_detects_seller_pressure():
    frame = _frame("DOWN")
    touch = frame.iloc[10]["timestamp"].to_pydatetime()
    result = pressure_features_before_touch(frame, touch_at=touch, atr_points=10.0)
    assert result is not None
    assert result["pressure_proxy_score"] < -30


def test_long_demand_reorients_seller_pressure_as_opposing():
    frame = _frame("DOWN")
    touch = frame.iloc[10]["timestamp"].to_pydatetime()
    rows = condition_depth_episodes(frame, (_episode("LONG", touch),))
    assert len(rows) == 1
    assert rows[0].opposing_pressure_score > 30
    assert rows[0].opposing_pressure_bucket in {"OPPOSING_MODERATE", "OPPOSING_STRONG"}


def test_short_supply_reorients_buyer_pressure_as_opposing():
    frame = _frame("UP")
    touch = frame.iloc[10]["timestamp"].to_pydatetime()
    rows = condition_depth_episodes(frame, (_episode("SHORT", touch),))
    assert len(rows) == 1
    assert rows[0].opposing_pressure_score > 30


def test_pressure_report_maps_turning_and_penetration_depth():
    frame = _frame("DOWN")
    touch = frame.iloc[10]["timestamp"].to_pydatetime()
    rows = condition_depth_episodes(frame, (_episode("LONG", touch),))
    report = pressure_depth_report(rows)
    bucket = rows[0].opposing_pressure_bucket
    summary = report["by_pressure_bucket"][bucket]
    assert summary["n"] == 1
    assert summary["turning_depth_median"] == 0.6
    assert summary["max_penetration_p90"] == 0.6


def test_bucket_boundaries_are_stable():
    assert opposing_pressure_bucket(-60) == "COUNTER_STRONG"
    assert opposing_pressure_bucket(0) == "BALANCED"
    assert opposing_pressure_bucket(20) == "OPPOSING_MODERATE"
    assert opposing_pressure_bucket(70) == "OPPOSING_STRONG"

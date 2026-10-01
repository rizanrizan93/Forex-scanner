from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pandas as pd

from fx_scanner.research_xau_rizan_axy_delta_v323 import (
    ARTIFACT_CONTRACT,
    DELTA_FRACTIONS,
    _anchor_for_episode,
    _resample_m5,
    _resolve_trade,
    evaluate_year,
)
from fx_scanner.research_xau_zone_reversal_depth_v225 import DepthEpisode


def _episode(direction: str = "LONG") -> DepthEpisode:
    if direction == "LONG":
        proximal, distal = 110.0, 100.0
        low, high = 100.0, 110.0
        turning = 104.0
    else:
        proximal, distal = 100.0, 110.0
        low, high = 100.0, 110.0
        turning = 106.0
    return DepthEpisode(
        zone_id=f"zone-{direction.lower()}",
        timeframe="H1",
        zone_class="STRUCTURAL",
        pattern="DBR" if direction == "LONG" else "RBD",
        direction=direction,
        available_at=datetime(2026, 1, 1, 0, 0, tzinfo=UTC),
        touch_at=datetime(2026, 1, 1, 0, 5, tzinfo=UTC),
        outcome_at=datetime(2026, 1, 1, 1, 0, tzinfo=UTC),
        zone_low=low,
        zone_high=high,
        proximal=proximal,
        distal=distal,
        atr_points=10.0,
        zone_width=10.0,
        outcome="HOLD_050",
        reaction_hit=True,
        break_hit=False,
        max_depth_reached=0.6,
        turning_depth=0.6,
        turning_price=turning,
        minutes_to_outcome=55.0,
        departure_range_atr=1.2,
        departure_body_fraction=0.7,
        base_range_atr=0.8,
        structural_bos=True,
    )


def _m1_long() -> pd.DataFrame:
    start = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    rows = []
    # Default quiet bars across the full H1 research horizon.
    for i in range(8 * 60 + 30):
        ts = start + timedelta(minutes=i)
        rows.append(
            {
                "timestamp": ts,
                "open": 115.0,
                "high": 115.5,
                "low": 114.5,
                "close": 115.0,
            }
        )

    def set_bar(i: int, o: float, h: float, l: float, c: float) -> None:
        rows[i].update(open=o, high=h, low=l, close=c)

    # Touch / first reclaim.
    for i in range(5, 10):
        set_bar(i, 109.0, 112.5, 108.0, 112.0)
    # Second close above proximal + >=0.75 ATR impulse.
    for i in range(10, 15):
        set_bar(i, 112.0, 119.0, 111.0, 118.0)
    # Post-impulse pullback sequence. M5 bar 20-24 becomes pivot A=113,
    # causally known only after bar 25-29 closes at 00:30.
    for i in range(15, 20):
        set_bar(i, 118.0, 119.0, 115.0, 117.0)
    for i in range(20, 25):
        set_bar(i, 117.0, 117.5, 113.0, 114.0)
    for i in range(25, 30):
        set_bar(i, 114.0, 117.0, 114.0, 116.0)
    # After A is known: retest A, then rally through X/Y/5Δ.
    set_bar(30, 116.0, 116.2, 113.0, 113.5)
    set_bar(31, 113.5, 114.5, 113.2, 114.2)
    set_bar(32, 114.2, 116.0, 114.0, 115.5)
    set_bar(33, 115.5, 118.5, 115.0, 118.0)
    set_bar(34, 118.0, 120.0, 117.5, 119.5)
    return pd.DataFrame(rows)


def test_v323_anchor_is_causal_and_uses_first_confirmed_post_impulse_pivot() -> None:
    price = _m1_long()
    m5 = _resample_m5(price)
    anchor = _anchor_for_episode(m5, _episode("LONG"))
    assert anchor is not None
    assert anchor["a"] == 113.0
    assert pd.Timestamp(anchor["confirmed_at"]) == pd.Timestamp(
        "2026-01-01T00:30:00Z"
    )


def test_v323_grid_includes_runtime_seed_and_produces_filled_target_candidate() -> None:
    assert 0.22 in DELTA_FRACTIONS
    report = evaluate_year(_m1_long(), [_episode("LONG")])
    assert report["artifact_contract"] == ARTIFACT_CONTRACT
    assert report["anchor_contract"]["no_future_turning_price_used_for_signal"] is True
    candidate = next(
        row for row in report["candidates"]
        if row["candidate_key"] == "D0.10|X|TP5"
    )
    assert candidate["episodes"] == 1
    assert candidate["anchors"] == 1
    assert candidate["fills"] == 1
    assert candidate["wins"] == 1
    assert candidate["losses"] == 0
    assert candidate["mean_entry_error_atr"] is not None


def test_v323_stop_first_on_same_m1_bar() -> None:
    frame = pd.DataFrame(
        [
            {
                "timestamp": pd.Timestamp("2026-01-01T00:00:00Z"),
                "open": 110.0,
                "high": 121.0,
                "low": 99.0,
                "close": 115.0,
            }
        ]
    )
    assert (
        _resolve_trade(
            frame,
            fill_index=0,
            direction="LONG",
            entry=110.0,
            sl=100.0,
            tp=120.0,
        )
        == "SL"
    )


def test_v323_filters_out_m15_parent_episodes() -> None:
    episode = replace(_episode("LONG"), timeframe="M15")
    report = evaluate_year(_m1_long(), [episode])
    assert report["episodes"] == 0
    assert all(row["episodes"] == 0 for row in report["candidates"])

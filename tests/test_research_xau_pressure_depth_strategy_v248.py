from datetime import UTC, datetime, timedelta

import pandas as pd

from fx_scanner.research_xau_pressure_depth_strategy_v248 import (
    ENTRY_MAPS,
    _price_at_depth,
    _stop_price,
    evaluate_trade,
)
from fx_scanner.research_xau_pressure_depth_v246 import PressureDepthEpisode
from fx_scanner.research_xau_zone_reversal_depth_v225 import DepthEpisode


def _episode(direction="LONG"):
    touch = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    return DepthEpisode(
        zone_id="z", timeframe="M15", zone_class="IMBALANCE", pattern="RBR",
        direction=direction, available_at=touch-timedelta(hours=1), touch_at=touch,
        outcome_at=touch+timedelta(minutes=10), zone_low=100, zone_high=110,
        proximal=109 if direction=="LONG" else 101,
        distal=100 if direction=="LONG" else 110,
        atr_points=10, zone_width=10, outcome="HOLD_050", reaction_hit=True,
        break_hit=False, max_depth_reached=0.5, turning_depth=0.5,
        turning_price=105, minutes_to_outcome=10, departure_range_atr=1.2,
        departure_body_fraction=0.7, base_range_atr=0.8, structural_bos=False,
    )


def _pressure(ep):
    return PressureDepthEpisode(
        zone_id=ep.zone_id, timeframe=ep.timeframe, direction=ep.direction,
        touch_at=ep.touch_at.isoformat(), outcome=ep.outcome,
        reaction_hit=True, break_hit=False, turning_depth=0.5,
        max_depth_reached=0.5, zone_width=10, atr_points=10,
        pressure_proxy_score=-50 if ep.direction=="LONG" else 50,
        opposing_pressure_score=50, opposing_pressure_bucket="OPPOSING_STRONG",
        approach_velocity_atr_per_minute=-0.1, mean_body_efficiency=-0.5,
        mean_close_location=-0.4, pre_touch_bars=8,
    )


def test_adaptive_map_waits_deeper_when_opposing_pressure_is_strong():
    assert ENTRY_MAPS["ADAPTIVE"]["OPPOSING_STRONG"] > ENTRY_MAPS["FIXED20"]["OPPOSING_STRONG"]
    assert ENTRY_MAPS["ADAPTIVE_DEEP"]["OPPOSING_STRONG"] > ENTRY_MAPS["ADAPTIVE"]["OPPOSING_STRONG"]


def test_depth_geometry_is_mirrored():
    assert _price_at_depth(_episode("LONG"), 0.4) == 106
    assert _price_at_depth(_episode("SHORT"), 0.4) == 104
    assert _stop_price(_episode("LONG")) == 99.5
    assert _stop_price(_episode("SHORT")) == 110.5


def test_trade_hits_target_after_deeper_fill():
    ep = _episode("LONG")
    touch = ep.touch_at
    frame = pd.DataFrame([
        {"timestamp": touch, "open":111, "high":111, "low":105.5, "close":106},
        {"timestamp": touch+timedelta(minutes=1), "open":106, "high":116, "low":105, "close":115},
    ])
    result = evaluate_trade(frame, episode=ep, pressure=_pressure(ep), entry_depth=0.4, rr=1.0)
    assert result.filled is True
    assert result.outcome == "TARGET"
    assert result.r_multiple == 1.0

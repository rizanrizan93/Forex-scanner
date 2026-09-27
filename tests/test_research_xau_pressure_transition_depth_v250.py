from datetime import UTC, datetime, timedelta

import pandas as pd

from fx_scanner.research_xau_pressure_transition_depth_v250 import _transition_state, transition_features_before_touch
from fx_scanner.research_xau_zone_reversal_depth_v225 import DepthEpisode


def _episode():
    touch = datetime(2026, 1, 1, 0, 12, tzinfo=UTC)
    return DepthEpisode(
        zone_id="z", timeframe="M15", zone_class="IMBALANCE", pattern="RBR",
        direction="LONG", available_at=touch-timedelta(hours=1), touch_at=touch,
        outcome_at=touch+timedelta(minutes=10), zone_low=100, zone_high=110,
        proximal=110, distal=100, atr_points=10, zone_width=10, outcome="HOLD_050",
        reaction_hit=True, break_hit=False, max_depth_reached=.5, turning_depth=.5,
        turning_price=105, minutes_to_outcome=10, departure_range_atr=1.2,
        departure_body_fraction=.7, base_range_atr=.8, structural_bos=False,
    )


def test_transition_state_recognizes_strong_fade():
    assert _transition_state(60, 30, 30) == "STRONG_FADE"
    assert _transition_state(20, 35, -15) == "REACCELERATION"


def test_transition_features_detect_seller_fade_into_long_demand():
    ep = _episode()
    rows = []
    price = 120.0
    for i in range(12):
        o = price
        drop = 1.0 if i < 6 else 0.15
        c = o - drop
        rows.append({
            "timestamp": ep.touch_at - timedelta(minutes=12-i),
            "open": o, "high": o + .05, "low": c - .05, "close": c,
        })
        price = c
    frame = pd.DataFrame(rows)
    features = transition_features_before_touch(frame, episode=ep)
    assert features is not None
    assert features["fade_delta"] > 0
    assert features["early_opposing_pressure"] > features["late_opposing_pressure"]
from datetime import datetime, timezone

import pandas as pd

from fx_scanner.research_xau_champion_onset_reaccel_v123 import (
    EXECUTION_INFLUENCE,
    NORMAL_SCORE_THRESHOLD,
    POLICY_EFFECT,
    PROMOTION_ELIGIBLE,
    ROUTES,
    build_reaccel_route_frame,
)


def test_v123_contract_is_shadow_only_and_frozen():
    assert POLICY_EFFECT == "SHADOW_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False
    assert ROUTES == ("DIRECTION_REACCEL", "COMPRESSED_REACCEL")
    assert NORMAL_SCORE_THRESHOLD == 0.50


def test_compressed_reaccel_starts_only_on_compressed_transition():
    z = timezone.utc
    frame = pd.DataFrame(
        [
            {"available_at": datetime(2025, 1, 1, tzinfo=z), "direction_state": "MIXED", "raw_state": "MIXED_OR_UNCLASSIFIED"},
            {"available_at": datetime(2025, 1, 2, tzinfo=z), "direction_state": "BULL", "raw_state": "BULL_COMPRESSED"},
            {"available_at": datetime(2025, 1, 3, tzinfo=z), "direction_state": "BULL", "raw_state": "BULL_NORMAL"},
            {"available_at": datetime(2025, 1, 4, tzinfo=z), "direction_state": "MIXED", "raw_state": "MIXED_OR_UNCLASSIFIED"},
            {"available_at": datetime(2025, 1, 5, tzinfo=z), "direction_state": "BULL", "raw_state": "BULL_NORMAL"},
            {"available_at": datetime(2025, 1, 6, tzinfo=z), "direction_state": "MIXED", "raw_state": "MIXED_OR_UNCLASSIFIED"},
            {"available_at": datetime(2025, 1, 7, tzinfo=z), "direction_state": "BEAR", "raw_state": "BEAR_COMPRESSED"},
        ]
    )
    routed, epochs = build_reaccel_route_frame(frame, route_id="COMPRESSED_REACCEL")
    assert list(routed["active_compressed_reaccel"]) == [None, "LONG", "LONG", None, None, None, "SHORT"]
    assert len(epochs) == 2
    assert epochs[0]["side"] == "LONG"
    assert epochs[0]["start"].startswith("2025-01-02")
    assert epochs[0]["end_exclusive"].startswith("2025-01-04")
    assert epochs[1]["side"] == "SHORT"


def test_direction_reaccel_is_symmetric():
    z = timezone.utc
    frame = pd.DataFrame(
        [
            {"available_at": datetime(2025, 1, 1, tzinfo=z), "direction_state": "MIXED", "raw_state": "MIXED_OR_UNCLASSIFIED"},
            {"available_at": datetime(2025, 1, 2, tzinfo=z), "direction_state": "BULL", "raw_state": "BULL_NORMAL"},
            {"available_at": datetime(2025, 1, 3, tzinfo=z), "direction_state": "BEAR", "raw_state": "BEAR_NORMAL"},
        ]
    )
    routed, epochs = build_reaccel_route_frame(frame, route_id="DIRECTION_REACCEL")
    assert list(routed["active_direction_reaccel"]) == [None, "LONG", "SHORT"]
    assert [x["side"] for x in epochs] == ["LONG", "SHORT"]

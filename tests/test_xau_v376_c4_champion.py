from __future__ import annotations

import pytest

from fx_scanner import xau_sd_liquidity_engine_v342 as eng
from fx_scanner import xau_dual_engine_dashboard_v344 as dash


def _zone(zone_id: str, low: float, high: float, direction: str = "LONG") -> dict:
    return {
        "zone_id": zone_id,
        "low": low,
        "high": high,
        "direction": direction,
    }


def test_c4_champion_is_frozen_and_replay_prior_is_explicit() -> None:
    assert eng.CHAMPION_ID == "V376_C4_NEXT_ZONE_PATH"
    assert eng.CHAMPION_STATUS == "FROZEN"
    assert eng.CHAMPION_REPLAY_EPISODES == 1485
    assert eng.CHAMPION_REACTION_050_REPLAY_PRIOR == pytest.approx(0.8006734006734006)


def test_c4_path_rank_follows_geometric_encounter_order() -> None:
    near = _zone("near", 90.0, 95.0)
    far = _zone("far", 80.0, 85.0)
    source = [near, far]

    near_state = eng._path_state(near, source, price_now=100.0)
    far_state = eng._path_state(far, source, price_now=100.0)

    assert near_state["relation"] == "BELOW_PRICE"
    assert near_state["path_rank"] == 1
    assert near_state["bonus"] == 9.0
    assert far_state["path_rank"] == 2
    assert far_state["blockers"] == 1
    assert far_state["bonus"] == 3.0


def test_c4_wrong_side_zone_is_penalized() -> None:
    wrong_side = _zone("wrong", 105.0, 110.0)
    state = eng._path_state(wrong_side, [wrong_side], price_now=100.0)

    assert state["relation"] == "WRONG_SIDE"
    assert state["path_rank"] is None
    assert state["bonus"] == -14.0


def test_dashboard_compact_labels_expose_path_rank_and_micro_tf() -> None:
    zone = {
        "timeframe": "H1",
        "direction": "LONG",
        "low": 4100.0,
        "high": 4110.0,
        "next_zone_path": {"path_rank": 1},
    }
    assert "path #1" in dash._zone_text(zone)
    assert dash._micro_text({"timeframe": "M5", "label": "CONFIRMED"}) == "M5 • CONFIRMED"

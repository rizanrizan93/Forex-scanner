from __future__ import annotations

from datetime import UTC, datetime

from fx_scanner.demo_xau_v351_executor import _candidate


def _heartbeat(*, guide_state="CONFIRMED_GUIDANCE", live=False, roadblock=None, roadblock_blocked=False, room_blocked=False):
    observed = datetime(2026, 10, 2, 8, 0, tzinfo=UTC)
    evaluation = {
        "contract": "XAU_RIZAN_SD_LIQUIDITY_V342_7_DEMO_EXECUTION_V352",
        "execution_authority": True,
        "execution_scope": "DEMO_ONLY",
        "live_execution_enabled": live,
        "expected_reversal_direction": "SHORT",
        "main_reversal_zone": {"zone_id": "parent-h4"},
        "structural_destination": {"zone_id": "dest-h4", "price": 90.0},
        "nearest_roadblock": roadblock or {},
        "structural_room": {"blocked": room_blocked, "state": "STRUCTURAL_ROOM_OK" if not room_blocked else "COMPRESSED_HTF_CORRIDOR"},
        "roadblock_room": {"blocked": roadblock_blocked, "state": "NO_ROADBLOCK_BEFORE_DESTINATION" if not roadblock_blocked else "ROADBLOCK_ROOM_TOO_SMALL"},
        "micro_confirmation": {
            "confirmed": True,
            "reclaim_at": "2026-10-02T07:59:30+00:00",
        },
        "entry_guide": {
            "state": guide_state,
            "direction": "SHORT",
            "entry_low": 99.0,
            "entry_high": 101.0,
            "entry_reference": 100.0,
            "invalidation": 105.0,
        },
        "news_zone": {
            "effective_entry_state": guide_state,
        },
    }
    return {
        "healthy": True,
        "observed_at": observed.isoformat(),
        "details": {"evaluation": evaluation},
    }


def test_v352_confirmed_short_candidate_uses_h4_destination():
    hb = _heartbeat()
    candidate, reason = _candidate(
        heartbeat=hb,
        bid=100.0,
        ask=100.1,
        now=datetime(2026, 10, 2, 8, 0, 30, tzinfo=UTC),
    )
    assert reason == "ELIGIBLE"
    assert candidate is not None
    assert candidate["direction"] == "SHORT"
    assert candidate["entry"] == 100.0
    assert candidate["stop_loss"] == 105.0
    assert candidate["take_profit"] == 90.0
    assert candidate["target_source"] == "H4_DESTINATION"
    assert candidate["rr"] == 2.0


def test_v352_nearest_roadblock_becomes_first_tp_when_rr_is_valid():
    hb = _heartbeat(
        roadblock={
            "zone_id": "h1-demand-roadblock",
            "near_edge": 92.0,
            "low": 90.0,
            "high": 92.0,
        }
    )
    candidate, reason = _candidate(
        heartbeat=hb,
        bid=100.0,
        ask=100.1,
        now=datetime(2026, 10, 2, 8, 0, 30, tzinfo=UTC),
    )
    assert reason == "ELIGIBLE"
    assert candidate is not None
    assert candidate["take_profit"] == 92.0
    assert candidate["target_source"] == "NEAREST_ROADBLOCK"
    assert candidate["rr"] == 1.6


def test_v352_structural_room_block_prevents_order():
    hb = _heartbeat(room_blocked=True)
    candidate, reason = _candidate(
        heartbeat=hb,
        bid=100.0,
        ask=100.1,
        now=datetime(2026, 10, 2, 8, 0, 30, tzinfo=UTC),
    )
    assert candidate is None
    assert reason.startswith("ENTRY_GATE:") or reason.startswith("STRUCTURAL_ROOM_BLOCK:")


def test_v352_live_flag_is_hard_forbidden():
    hb = _heartbeat(live=True)
    candidate, reason = _candidate(
        heartbeat=hb,
        bid=100.0,
        ask=100.1,
        now=datetime(2026, 10, 2, 8, 0, 30, tzinfo=UTC),
    )
    assert candidate is None
    assert reason == "LIVE_EXECUTION_FLAG_FORBIDDEN"


def test_v352_no_chase_outside_retest_band():
    hb = _heartbeat()
    candidate, reason = _candidate(
        heartbeat=hb,
        bid=97.0,
        ask=97.1,
        now=datetime(2026, 10, 2, 8, 0, 30, tzinfo=UTC),
    )
    assert candidate is None
    assert reason == "WAIT_ENTRY_RETEST_NO_CHASE"

from __future__ import annotations

from datetime import UTC, datetime

from fx_scanner.demo_xau_v351_executor import _candidate, _evidence_ledger, _margin_room_ok


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
    assert reason == "WAIT_ENTRY_RETEST_OR_FRESH_CONFIRMATION"


def test_v354_fresh_confirmation_can_enter_without_waiting_for_deep_retest():
    hb = _heartbeat()
    evaluation = hb["details"]["evaluation"]
    evaluation["structural_destination"]["price"] = 88.0
    evaluation["entry_guide"]["invalidation"] = 101.5
    evaluation["micro_confirmation"].update(
        {
            "confirmation_close": 97.2,
            "local_atr": 2.0,
            "reclaim_at": "2026-10-02T08:00:00+00:00",
        }
    )
    candidate, reason = _candidate(
        heartbeat=hb,
        bid=97.0,
        ask=97.1,
        now=datetime(2026, 10, 2, 8, 1, 0, tzinfo=UTC),
    )
    assert reason == "ELIGIBLE"
    assert candidate is not None
    assert candidate["entry_mode"] == "FRESH_CONFIRMATION_ENTRY"
    assert candidate["entry"] == 97.0
    assert candidate["rr"] >= 1.50


def test_v354_stale_confirmation_does_not_chase():
    hb = _heartbeat()
    evaluation = hb["details"]["evaluation"]
    evaluation["structural_destination"]["price"] = 88.0
    evaluation["entry_guide"]["invalidation"] = 101.5
    evaluation["micro_confirmation"].update(
        {
            "confirmation_close": 97.2,
            "local_atr": 2.0,
            "reclaim_at": "2026-10-02T07:50:00+00:00",
        }
    )
    candidate, reason = _candidate(
        heartbeat=hb,
        bid=97.0,
        ask=97.1,
        now=datetime(2026, 10, 2, 8, 0, 30, tzinfo=UTC),
    )
    assert candidate is None
    assert reason == "WAIT_ENTRY_RETEST_OR_FRESH_CONFIRMATION"



class _Account:
    def __init__(self, *, equity, margin=None, margin_free=None):
        self.equity = equity
        self.margin = margin
        self.margin_free = margin_free


class _Gateway:
    def __init__(self, account):
        self.account = account

    def account_snapshot(self):
        return self.account


def test_v352_margin_guard_derives_used_margin_from_margin_free():
    ok, reason, usage = _margin_room_ok(
        _Gateway(_Account(equity=100.0, margin=None, margin_free=80.0))
    )
    assert ok is True
    assert reason == "MARGIN_ROOM_OK:DERIVED_FROM_MARGIN_FREE"
    assert abs(float(usage) - 0.20) < 1e-9


def test_v352_margin_guard_blocks_at_fifty_percent():
    ok, reason, usage = _margin_room_ok(
        _Gateway(_Account(equity=100.0, margin=None, margin_free=50.0))
    )
    assert ok is False
    assert reason == "MARGIN_USAGE_AT_OR_ABOVE_50PCT:DERIVED_FROM_MARGIN_FREE"
    assert abs(float(usage) - 0.50) < 1e-9


def test_v352_margin_guard_fails_closed_when_margin_data_missing():
    ok, reason, usage = _margin_room_ok(
        _Gateway(_Account(equity=100.0, margin=None, margin_free=None))
    )
    assert ok is False
    assert reason == "ACCOUNT_MARGIN_UNAVAILABLE"
    assert usage is None

def test_v354_evidence_ledger_carries_full_decision_path():
    hb = _heartbeat()
    evaluation = hb["details"]["evaluation"]
    evaluation["main_reversal_zone"].update(
        {
            "timeframe": "H4",
            "hierarchy_role": "MAIN_REVERSAL_ZONE",
            "direction": "SHORT",
            "low": 99.0,
            "high": 105.0,
            "condition": "TESTED",
        }
    )
    evaluation["refinement_zone"] = {
        "zone_id": "refine-h1",
        "timeframe": "H1",
        "hierarchy_role": "H1_REFINEMENT",
        "direction": "SHORT",
        "low": 99.5,
        "high": 101.5,
        "condition": "TESTED",
        "parent_zone_id": "parent-h4",
    }
    evaluation["liquidity_map"] = {
        "side": "ABOVE_SUPPLY",
        "low": 99.0,
        "high": 106.0,
        "warning": "LIQUIDITY_SWEEP_POSSIBLE_BEFORE_REVERSAL",
        "extension_atr": 0.25,
    }
    evaluation["micro_confirmation"].update(
        {
            "stage": "REVERSAL_CONFIRMED",
            "touched": True,
            "sweep_seen": True,
            "mss_confirmed": True,
            "displacement_confirmed": True,
            "entry_low": 99.0,
            "entry_high": 101.0,
            "entry_reference": 100.0,
            "invalidation": 105.0,
        }
    )
    evaluation["news_zone"].update(
        {
            "risk_state": "CLEAR",
            "overshoot_risk": "HIGH",
            "focal_event": {
                "event_id": "nfp-1",
                "category": "NFP",
                "impact": "HIGH",
                "scheduled_at": "2026-10-02T12:30:00+00:00",
                "scheduled_at_wib": "2026-10-02T19:30:00+07:00",
                "source_tier": "OFFICIAL",
            },
        }
    )
    evaluation["structural_room"].update(
        {"distance_parent_atr": 0.8, "planned_rr": 2.0}
    )

    candidate, reason = _candidate(
        heartbeat=hb,
        bid=100.0,
        ask=100.1,
        now=datetime(2026, 10, 2, 8, 0, 30, tzinfo=UTC),
    )
    assert reason == "ELIGIBLE"
    assert candidate is not None

    ledger = _evidence_ledger(hb, candidate)
    assert ledger["schema"] == "XAU_RIZAN_DEMO_EVIDENCE_LEDGER_V354_1"
    assert ledger["parent_h4"]["zone_id"] == "parent-h4"
    assert ledger["h1_refinement"]["zone_id"] == "refine-h1"
    assert ledger["liquidity"]["sweep_seen"] is True
    assert ledger["roadblock_room"]["blocked"] is False
    assert ledger["structural_room"]["planned_rr"] == 2.0
    assert ledger["news"]["focal_event"]["category"] == "NFP"
    assert ledger["micro_confirmation"]["mss_confirmed"] is True
    assert ledger["order_plan"]["signal_id"] == candidate["signal_id"]
    assert ledger["order_plan"]["sl"] == 105.0
    assert ledger["order_plan"]["tp"] == 90.0



def test_v364_early_confirmed_setup_can_send_bounded_demo_probe():
    hb = _heartbeat(guide_state="EARLY_CONFIRMED_GUIDANCE")
    evaluation = hb["details"]["evaluation"]
    evaluation["structural_destination"]["price"] = 88.0
    evaluation["micro_confirmation"].update(
        {
            "confirmed": False,
            "early_confirmed": True,
            "confirmation_close": 98.8,
            "local_atr": 1.0,
            "reclaim_at": "2026-10-02T07:59:30+00:00",
        }
    )
    candidate, reason = _candidate(
        heartbeat=hb,
        bid=98.7,
        ask=98.8,
        now=datetime(2026, 10, 2, 8, 0, 30, tzinfo=UTC),
    )
    assert reason == "ELIGIBLE"
    assert candidate is not None
    assert candidate["confirmation_tier"] == "EARLY"
    assert candidate["entry_mode"] == "EARLY_CONFIRMATION_DEMO_PROBE"
    assert candidate["rr"] >= 1.50


def test_v364_early_lane_still_fails_closed_when_news_tier_does_not_match():
    hb = _heartbeat(guide_state="EARLY_CONFIRMED_GUIDANCE")
    evaluation = hb["details"]["evaluation"]
    evaluation["micro_confirmation"].update(
        {
            "confirmed": False,
            "early_confirmed": True,
        }
    )
    evaluation["news_zone"]["effective_entry_state"] = "CONFIRMED_GUIDANCE"
    candidate, reason = _candidate(
        heartbeat=hb,
        bid=100.0,
        ask=100.1,
        now=datetime(2026, 10, 2, 8, 0, 30, tzinfo=UTC),
    )
    assert candidate is None
    assert reason.startswith("NEWS_GATE_TIER_MISMATCH:")

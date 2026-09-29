from datetime import UTC, datetime, timedelta

from fx_scanner.xau_pressure_transition_v249 import evaluate_pressure_transition


def _hb(score, delta, *, age=30, healthy=True, state="BALANCED_OR_CONTESTED"):
    now = datetime(2026, 9, 28, 4, 0, tzinfo=UTC)
    return now, {
        "observed_at": (now - timedelta(seconds=age)).isoformat(),
        "healthy": healthy,
        "details": {
            "analysis": {
                "state": state,
                "dom_pressure_score": score,
                "last_imbalance": (score - 50.0) / 100.0,
                "cross_run": {
                    "pressure_score_change": delta,
                    "previous_observed_at": (
                        now - timedelta(seconds=age + 60)
                    ).isoformat(),
                },
            }
        },
    }


def test_long_strong_seller_reacceleration_blocks():
    now, hb = _hb(25.0, -5.0, state="ASK_DOMINANT")
    result = evaluate_pressure_transition(direction="LONG", dom_heartbeat=hb, now=now)
    assert result["state"] == "OPPOSING_REACCELERATION"
    assert result["hard_block"] is True
    assert result["pre_touch_entry_allowed"] is False
    assert result["confirmation_entry_allowed"] is False


def test_long_seller_fading_allows_m5_before_pretouch():
    now, hb = _hb(25.0, 8.0, state="ASK_DOMINANT")
    result = evaluate_pressure_transition(direction="LONG", dom_heartbeat=hb, now=now)
    assert result["state"] == "OPPOSING_FADING_EARLY"
    assert result["pre_touch_entry_allowed"] is False
    assert result["confirmation_entry_allowed"] is True


def test_long_balanced_absorption_allows_entry():
    now, hb = _hb(48.0, 4.0)
    result = evaluate_pressure_transition(direction="LONG", dom_heartbeat=hb, now=now)
    assert result["state"] == "BALANCED_ABSORPTION"
    assert result["pre_touch_entry_allowed"] is True
    assert result["confirmation_entry_allowed"] is True


def test_short_buyer_fading_is_mirrored():
    now, hb = _hb(75.0, -8.0, state="BID_DOMINANT")
    result = evaluate_pressure_transition(direction="SHORT", dom_heartbeat=hb, now=now)
    assert result["state"] == "OPPOSING_FADING_EARLY"
    assert result["confirmation_entry_allowed"] is True


def test_stale_dom_fails_closed():
    now, hb = _hb(50.0, 5.0, age=300)
    result = evaluate_pressure_transition(direction="LONG", dom_heartbeat=hb, now=now)
    assert result["state"] == "DOM_STALE"
    assert result["hard_block"] is True

def test_old_previous_sample_waits_for_second_fresh_comparison():
    now, hb = _hb(50.0, 5.0, age=30)
    hb["details"]["analysis"]["cross_run"]["previous_observed_at"] = (
        now - timedelta(minutes=10)
    ).isoformat()
    result = evaluate_pressure_transition(direction="LONG", dom_heartbeat=hb, now=now)
    assert result["state"] == "WAIT_SECOND_SAMPLE"
    assert result["hard_block"] is True


def test_v271_fresh_neutral_single_sample_allows_demo_calibration_only():
    now, hb = _hb(50.0, 5.0, age=20)
    hb["details"]["analysis"]["cross_run"]["previous_observed_at"] = (
        now - timedelta(minutes=10)
    ).isoformat()
    result = evaluate_pressure_transition(direction="SHORT", dom_heartbeat=hb, now=now)
    assert result["state"] == "WAIT_SECOND_SAMPLE"
    assert result["current_sample_fresh"] is True
    assert result["hard_block"] is True
    assert result["pre_touch_entry_allowed"] is False
    assert result["confirmation_entry_allowed"] is False
    assert result["calibration_entry_allowed"] is True
    assert (
        result["calibration_pressure_reason"]
        == "FRESH_SINGLE_SAMPLE_NEUTRAL_OR_SUPPORTIVE"
    )


def test_v271_fresh_materially_opposing_single_sample_blocks_demo_calibration():
    now, hb = _hb(60.0, 5.0, age=20, state="BID_DOMINANT")
    hb["details"]["analysis"]["cross_run"]["previous_observed_at"] = (
        now - timedelta(minutes=10)
    ).isoformat()
    result = evaluate_pressure_transition(direction="SHORT", dom_heartbeat=hb, now=now)
    assert result["state"] == "WAIT_SECOND_SAMPLE"
    assert result["opposing_pressure"] == 20.0
    assert result["hard_block"] is True
    assert result["calibration_entry_allowed"] is False
    assert (
        result["calibration_pressure_reason"]
        == "FRESH_SINGLE_SAMPLE_MATERIALLY_OPPOSING"
    )


def test_v271_stale_current_sample_never_gets_calibration_bypass():
    now, hb = _hb(50.0, 5.0, age=300)
    result = evaluate_pressure_transition(direction="SHORT", dom_heartbeat=hb, now=now)
    assert result["state"] == "DOM_STALE"
    assert result["current_sample_fresh"] is False
    assert result["calibration_entry_allowed"] is False

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
                "cross_run": {"pressure_score_change": delta},
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
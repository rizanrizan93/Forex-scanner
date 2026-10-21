"""Regression tests for the dashboard-only strict reversal display gate."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from fx_scanner.manual_reversal_dashboard import confirmed_rebound_plan


def sample():
    return {
        "phase": "KONFIRMASI_STRUKTUR",
        "rejection_m15_at": "2026-10-21T01:15:00+00:00",
        "confirmation_m5_at": "2026-10-21T01:20:00+00:00",
        "anchor": {
            "eligible": True, "structural_bos": True, "major_conflict": False,
            "lifecycle": "RETESTED", "risk_state": "NORMAL", "touch_count": 1,
        },
        "candidate_a": {
            "model": "CANDIDATE_A_TP1R_WATCH", "state": "WATCH",
            "first_touch_at": "2026-10-21T01:00:00+00:00",
            "zone_age_at_first_touch_minutes": 180,
            "confirmation_lag_minutes": 20,
            "entry_reference": 4120.0, "sl_reference": 4100.0,
            "tp_1r_reference": 4140.0,
        },
    }


def test_confirmed_fresh_bos_reaction_accepted():
    assert confirmed_rebound_plan(sample())


def test_unconfirmed_wait_and_bos_missing_hidden():
    p = sample()
    p["candidate_a"]["state"] = "WAIT"
    assert not confirmed_rebound_plan(p)
    p = sample()
    p["anchor"]["structural_bos"] = False
    assert not confirmed_rebound_plan(p)


def test_repeated_zone_and_break_risk_hidden():
    p = sample()
    p["anchor"]["touch_count"] = 5
    p["anchor"]["lifecycle"] = "DEGRADED"
    p["anchor"]["risk_state"] = "REPEATED_TESTS"
    assert not confirmed_rebound_plan(p)
    p = sample()
    p["anchor"]["risk_state"] = "PENDING_PARENT_CLOSE"
    assert not confirmed_rebound_plan(p)


def test_age_lag_conflict_and_stale_confirmation_hidden():
    for key, value in [("zone_age_at_first_touch_minutes", 721),
                       ("confirmation_lag_minutes", 31)]:
        p = sample()
        p["candidate_a"][key] = value
        assert not confirmed_rebound_plan(p)
    p = sample()
    p["anchor"]["major_conflict"] = True
    assert not confirmed_rebound_plan(p)
    p = sample()
    p["phase"] = "KONFIRMASI_LAMA"
    assert not confirmed_rebound_plan(p)


def test_missing_broker_reference_hidden():
    p = sample()
    p["candidate_a"]["tp_1r_reference"] = None
    assert not confirmed_rebound_plan(p)

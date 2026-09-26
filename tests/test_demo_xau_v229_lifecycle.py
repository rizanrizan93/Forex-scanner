from copy import deepcopy
from datetime import UTC, datetime, timedelta
import unittest

from fx_scanner.demo_xau_v229_lifecycle import atlas_reason, micro_reason, parent_status, pretouch_allowed
from fx_scanner.demo_xau_v229_ladder_plan import build_parent_ladder_plan

NOW = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)
PARENT_AT = NOW - timedelta(minutes=20)
SOURCE_AT = NOW - timedelta(hours=2)


def fixture():
    zone = {"zone_id": "h4", "direction": "LONG", "timeframe": "H4", "low": 98.0,
            "high": 104.0, "atr_points": 4.0,
            "lifecycle": {"active": True, "touch_count": 0, "freshness": "FRESH"}}
    precision = {"zone_id": "h1", "timeframe": "H1", "available_at": SOURCE_AT.isoformat()}
    plan = {"h4_zone_id": "h4", "direction": "LONG", "sl": 97.4,
            "source_layer": "H1_NESTED_LOCATOR", "h4_zone_snapshot": deepcopy(zone),
            "precision_source_snapshot": precision}
    signal = {"state": "COOLDOWN", "observed_at": PARENT_AT.isoformat(),
              "expires_at": (NOW + timedelta(hours=1)).isoformat()}
    atlas = {"zones": [zone]}
    micro = {"state": "M5_REFINEMENT_CONFIRMED_SHADOW", "direction": "LONG",
             "source_zone_id": "h1", "source_timeframe": "H1",
             "source_available_at": SOURCE_AT.isoformat(),
             "sweep": {"at": (PARENT_AT + timedelta(minutes=5)).isoformat()},
             "reclaim_at": (PARENT_AT + timedelta(minutes=10)).isoformat(),
             "mss_at": (PARENT_AT + timedelta(minutes=10)).isoformat(),
             "displacement_at": (PARENT_AT + timedelta(minutes=15)).isoformat(),
             "candidate_entry_pocket": {"low": 99.0, "high": 100.0},
             "refined_entry_pocket": {"low": 99.5, "high": 100.5}}
    return plan, signal, atlas, micro


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.plan, self.signal, self.atlas, self.micro = fixture()

    def status(self):
        return parent_status(self.plan, self.signal, self.atlas, now=NOW, live_price=101.0)

    def reason(self, slot=3):
        return micro_reason(self.plan, self.micro, slot=slot, parent_at=PARENT_AT, evaluation_at=NOW)

    def test_first_touch_does_not_retire_frozen_parent(self):
        zone = self.atlas["zones"][0]
        zone["lifecycle"].update(touch_count=1, freshness="FIRST_TEST")
        self.assertEqual(self.status()[0], "ACTIVE")
        self.assertFalse(pretouch_allowed(self.plan, self.atlas))
        self.assertIsNone(self.reason(3))
        self.assertIsNone(self.reason(4))

    def test_unchanged_parent_survives_current_candidate_handoff(self):
        self.atlas["new_focus_zone_id"] = "other-fresh-h4"
        self.assertEqual(self.status()[0], "ACTIVE")

    def test_new_pretouch_submission_requires_untouched_parent(self):
        self.assertTrue(pretouch_allowed(self.plan, self.atlas))
        self.atlas["zones"][0]["lifecycle"]["touch_count"] = 1
        self.assertFalse(pretouch_allowed(self.plan, self.atlas))

    def test_parent_break_cancels(self):
        self.atlas["zones"][0]["lifecycle"]["active"] = False
        self.assertEqual(self.status(), ("CANCEL", "PARENT_ZONE_INVALIDATED"))

    def test_expiry_cancels_even_with_no_atlas_zone(self):
        self.signal["expires_at"] = NOW.isoformat()
        self.atlas["zones"] = []
        self.assertEqual(self.status(), ("CANCEL", "PARENT_EXPIRED"))

    def test_missing_zone_waits_instead_of_inventing_invalidation(self):
        self.atlas["zones"] = []
        self.assertEqual(self.status()[0], "WAIT")

    def test_duplicate_zone_invalidation_wins(self):
        broken = deepcopy(self.atlas["zones"][0])
        broken["lifecycle"]["active"] = False
        self.atlas["path_map"] = {"source_zone": broken}
        self.assertEqual(self.status()[0], "CANCEL")

    def test_frozen_geometry_change_waits(self):
        self.atlas["zones"][0]["low"] = 97.0
        self.assertEqual(self.status()[0], "WAIT")

    def test_stop_breach_cancels_long_and_short(self):
        self.assertEqual(parent_status(self.plan, self.signal, self.atlas,
                                       now=NOW, live_price=97.0)[0], "CANCEL")
        self.plan.update(direction="SHORT", sl=105.0)
        self.assertEqual(parent_status(self.plan, self.signal, self.atlas,
                                       now=NOW, live_price=106.0)[0], "CANCEL")

    def test_h4_only_is_a_separate_watch_cohort(self):
        self.plan["source_layer"] = "H4_HISTORICAL_HOTSPOT"
        self.assertEqual(self.status(), ("CANCEL", "H4_ONLY_WATCH_COHORT"))

    def test_legacy_parent_without_snapshot_cannot_continue(self):
        del self.plan["h4_zone_snapshot"]
        self.assertEqual(self.status()[0], "WAIT")

    def test_invalid_micro_flags_do_not_authorize(self):
        self.micro.update(state="SOURCE_INVALIDATED_NO_REFINEMENT", reclaim_confirmed=True,
                          mss_confirmed=True, displacement_confirmed=True)
        self.assertIsNotNone(self.reason(3))
        self.assertIsNotNone(self.reason(4))

    def test_micro_must_belong_to_frozen_precision_source(self):
        self.micro["source_zone_id"] = "unrelated-h1"
        self.assertEqual(self.reason(), "M5_PARENT_SOURCE_MISMATCH")

    def test_old_sweep_cannot_be_reused_for_new_parent(self):
        self.micro["sweep"]["at"] = (PARENT_AT - timedelta(minutes=5)).isoformat()
        self.assertEqual(self.reason(), "M5_SWEEP_OUTSIDE_PARENT_EPISODE")

    def test_missing_future_and_pre_sweep_confirmation_fail(self):
        for value in (None, (NOW + timedelta(minutes=5)).isoformat(), PARENT_AT.isoformat()):
            with self.subTest(value=value):
                self.micro["mss_at"] = value
                self.assertIsNotNone(self.reason())

    def test_slot_three_can_precede_displacement(self):
        self.micro["state"] = "M5_MSS_WAIT_DISPLACEMENT"
        self.assertIsNone(self.reason(3))
        self.assertIsNotNone(self.reason(4))

    def test_micro_source_availability_must_match_capture(self):
        self.micro["source_available_at"] = NOW.isoformat()
        self.assertIsNotNone(self.reason())

    def test_invalid_pocket_fails(self):
        self.micro["candidate_entry_pocket"] = {"low": 100.0, "high": 99.0}
        self.assertIsNotNone(self.reason())

    def test_atlas_freshness_accepts_only_timed_healthy_context(self):
        for healthy, age, expected in ((True, 10, None), (False, 10, True),
                                       (True, 601, True), (True, -5, True)):
            heartbeat = {"healthy": healthy, "observed_at": (NOW - timedelta(seconds=age)).isoformat()}
            reason = atlas_reason(heartbeat, now=NOW)
            self.assertEqual(reason is None, expected is None)

    def test_parent_creation_rejects_h4_only_but_keeps_nested(self):
        zone = self.atlas["zones"][0]
        v226 = {"focus_direction": "LONG", "long": {"h4": {"zone": zone},
                "h1": {"zone": self.plan["precision_source_snapshot"]}},
                "depth_entry_candidate": {"source_layer": "H1_NESTED_LOCATOR",
                    "calibrated_fresh_first_touch": True,
                    "display_status": "PREPARE_ONLY_FRESH_FIRST_TOUCH",
                    "entry_low": 100.0, "entry_high": 102.0},
                "four_order_ladder": {"slots": [{"slot": i, "reference_price": 101.0}
                                                   for i in range(1, 5)]}}
        target = {"zone_id": "supply", "timeframe": "H4", "direction": "SHORT",
                  "low": 120.0, "high": 122.0, "lifecycle": {"active": True}}
        atlas = {"zones": [target]}
        plan = build_parent_ladder_plan(v226_evaluation=v226, atlas_evaluation=atlas, live_price=103.0)
        self.assertIsNotNone(plan)
        self.assertEqual(plan["h4_zone_snapshot"], zone)
        self.assertEqual(plan["precision_source_snapshot"]["zone_id"], "h1")
        v226["depth_entry_candidate"]["source_layer"] = "H4_HISTORICAL_HOTSPOT"
        self.assertIsNone(build_parent_ladder_plan(v226_evaluation=v226, atlas_evaluation=atlas, live_price=103.0))


if __name__ == "__main__":
    unittest.main()

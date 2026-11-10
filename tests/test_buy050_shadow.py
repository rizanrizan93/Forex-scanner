"""BUY050 native-source shadow: fail-closed UI projection tests."""
import unittest
from datetime import datetime, timedelta, timezone

from fx_scanner.cbot_buy050_shadow_dashboard import PROFILE, evaluate_shadow, verified_live_symbols


T0 = datetime(2026, 11, 9, 12, 0, 0, tzinfo=timezone.utc)


def sample():
    return {
        "contract": "RIZAN_BUY050_SHADOW_V1", "strategy": "P3_BUY050",
        "profile_sha256": PROFILE, "source_core": "BUY050_NATIVE_CSHARP",
        "as_of": T0.isoformat(), "read_only": True,
        "execution_authority": False, "execution_influence": False,
        "symbols": [
            {
                "symbol": symbol, "status": "SETUP_SHADOW", "reason": "Technical only",
                "bar_at": T0.isoformat(), "source_core": "BUY050_NATIVE_CSHARP",
                "execution_authority": False, "execution_influence": False,
                "candidate": {
                    "at": T0.isoformat(), "side": "BUY", "origin": "INCUMBENT",
                    "entry": 100.0, "sl": 98.0, "tp": 124.0,
                    "target_r": 12.0, "valid_until": (T0 + timedelta(seconds=5 if symbol == "BTCUSD" else 60)).isoformat(),
                    "blockers": ["CANDIDATE_NOT_BROKER_EXECUTED", "NATIVE_TERMINAL_GATES_NOT_FULLY_OBSERVED"],
                    "confidence": "TECHNICAL_GEOMETRY_ONLY",
                },
            }
            for symbol in ("XAUUSD", "EURUSD", "BTCUSD")
        ],
    }


class ShadowViewTests(unittest.TestCase):
    @staticmethod
    def primary_live():
        return {
            "contract": "RIZAN_BUY050_READONLY_V1",
            "strategy": "P3_BUY050",
            "source_release": "BUY050_RUNTIMEGUARD_20261108",
            "account_suffix": "7903",
            "observed_at": T0.isoformat(),
            "read_only": True,
            "execution_authority": False,
            "service_active": True,
            "bridge": {"observed_at": T0.isoformat(), "connected": 3,
                       "profile_ok": True, "macro_snapshot_present": True,
                        "btc_feed_status": "READY"},
            "symbols": [
                {"symbol": symbol, "checkpoint_present": True, "identity_ok": True,
                 "lease_active": True, "checkpoint_basket": False,
                 "pending_intent": False, "quarantined": False, "fault": False}
                for symbol in ("XAUUSD", "EURUSD", "BTCUSD")
            ],
        }

    def test_shadow_geometry_requires_independent_live_identity(self):
        p = self.primary_live()
        self.assertTrue(all(verified_live_symbols(p, now=T0).values()))
        p["symbols"][2]["unrecognized_checkpoint"] = True
        states = verified_live_symbols(p, now=T0)
        self.assertFalse(states["BTCUSD"])
        self.assertTrue(states["XAUUSD"])
        p["symbols"][0]["lease_active"] = False
        self.assertFalse(verified_live_symbols(p, now=T0)["XAUUSD"])

    def test_btc_bridge_feed_unknown_disables_shadow_confirmation(self):
        p = self.primary_live()
        p["bridge"].pop("btc_feed_status")
        states = verified_live_symbols(p, now=T0)
        self.assertFalse(states["BTCUSD"])
        self.assertTrue(states["XAUUSD"])
        p["bridge"]["btc_feed_status"] = "UNAVAILABLE"
        self.assertFalse(verified_live_symbols(p, now=T0)["BTCUSD"])

    def test_outdated_or_missing_primary_never_verifies_shadow(self):
        p = self.primary_live()
        self.assertFalse(any(verified_live_symbols(p, now=T0 + timedelta(minutes=16)).values()))
        self.assertFalse(any(verified_live_symbols(None, now=T0).values()))

    def test_bridge_health_is_required_for_shadow(self):
        p = self.primary_live()
        p["bridge"]["observed_at"] = (T0 - timedelta(minutes=3)).isoformat()
        self.assertFalse(any(verified_live_symbols(p, now=T0).values()))

    def test_technical_levels_must_expire(self):
        s = sample()
        self.assertIsNotNone(evaluate_shadow(s, now=T0 + timedelta(seconds=2))["symbols"]["BTCUSD"]["candidate"])
        self.assertIsNone(evaluate_shadow(s, now=T0 + timedelta(seconds=6))["symbols"]["BTCUSD"]["candidate"])
        self.assertIsNone(evaluate_shadow(s, now=T0 + timedelta(seconds=60))["symbols"]["XAUUSD"]["candidate"])

    def test_stale_snapshot_hides_all_geometry(self):
        view = evaluate_shadow(sample(), now=T0 + timedelta(minutes=20))
        self.assertFalse(view["fresh"])
        self.assertTrue(all(row["candidate"] is None for row in view["symbols"].values()))

    def test_tampered_profile_is_rejected(self):
        s = sample()
        s["profile_sha256"] = "WRONG"
        with self.assertRaises(ValueError):
            evaluate_shadow(s, now=T0)

    def test_foreign_execution_authority_rejected(self):
        s = sample()
        s["symbols"][1]["execution_authority"] = True
        with self.assertRaises(ValueError):
            evaluate_shadow(s, now=T0)

    def test_geometry_never_accepts_inverted_sl_or_wrong_rr(self):
        s = sample()
        s["symbols"][0]["candidate"]["sl"] = 101.0
        s["symbols"][1]["candidate"]["tp"] = 106.0
        v = evaluate_shadow(s, now=T0 + timedelta(seconds=1))
        self.assertIsNone(v["symbols"]["XAUUSD"]["candidate"])
        self.assertIsNone(v["symbols"]["EURUSD"]["candidate"])

    def test_signal_must_have_explicit_execution_block(self):
        s = sample()
        s["symbols"][0]["candidate"]["blockers"] = []
        self.assertIsNone(evaluate_shadow(s, now=T0)["symbols"]["XAUUSD"]["candidate"])

    def test_fresh_publication_cannot_label_stale_bars_no_signal(self):
        s = sample()
        s["symbols"][0].update(status="NO_SIGNAL", candidate=None,
                                bar_at=(T0 - timedelta(minutes=5)).isoformat())
        s["symbols"][2].update(status="NO_SIGNAL", candidate=None,
                                bar_at=(T0 - timedelta(hours=2)).isoformat())
        evaluated = evaluate_shadow(s, now=T0 + timedelta(seconds=1))
        self.assertEqual(evaluated["symbols"]["XAUUSD"]["status"], "DATA_TERLAMBAT")
        self.assertEqual(evaluated["symbols"]["BTCUSD"]["status"], "DATA_TERLAMBAT")
        self.assertIsNone(evaluated["symbols"]["BTCUSD"]["candidate"])
        self.assertEqual(evaluated["symbols"]["EURUSD"]["status"], "SETUP_SHADOW")


if __name__ == "__main__":
    unittest.main()

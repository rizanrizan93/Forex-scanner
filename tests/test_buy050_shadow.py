"""BUY050 native-source shadow: fail-closed UI projection tests."""
import unittest
from datetime import datetime, timedelta, timezone

from fx_scanner.cbot_buy050_shadow_dashboard import PROFILE, evaluate_shadow


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


if __name__ == "__main__":
    unittest.main()

"""Contract tests for BUY050 cBot dashboard (no broker or network access)."""
import unittest
from datetime import datetime, timedelta, timezone

from fx_scanner.cbot_buy050_dashboard import evaluate_snapshot
from scripts.read_buy050_dashboard import checkpoint_symbol, PROFILE


NOW = datetime(2026, 11, 8, 14, 0, tzinfo=timezone.utc)


def sample():
    return {
        "contract": "RIZAN_BUY050_READONLY_V1",
        "strategy": "P3_BUY050",
        "source_release": "BUY050_RUNTIMEGUARD_20261108",
        "account_suffix": "7903",
        "observed_at": NOW.isoformat(),
        "read_only": True,
        "execution_authority": False,
        "service_active": True,
        "bridge": {
            "observed_at": NOW.isoformat(),
            "connected": 3,
            "profile_ok": True,
            "macro_snapshot_present": True,
        },
        "symbols": [
            {
                "symbol": s, "checkpoint_present": True, "identity_ok": True,
                "lease_active": True, "checkpoint_basket": False,
                "pending_intent": False, "quarantined": False, "fault": False,
                "last_signal_at": None,
            }
            for s in ("XAUUSD", "EURUSD", "BTCUSD")
        ],
    }


class Buy050DashboardTests(unittest.TestCase):
    def test_fresh_readonly_observation_does_not_claim_trade(self):
        view = evaluate_snapshot(sample(), now=NOW + timedelta(seconds=5))
        self.assertTrue(view["bridge_ready"])
        self.assertEqual(set(view["statuses"].values()), {"TERPANTAU"})
        self.assertFalse(any("entry" in row or "sl" in row or "tp" in row
                             for row in view["payload"]["symbols"]))

    def test_stale_snapshot_never_shows_ready(self):
        view = evaluate_snapshot(sample(), now=NOW + timedelta(minutes=16))
        self.assertFalse(view["fresh"])
        self.assertEqual(set(view["statuses"].values()), {"DATA_TERLAMBAT"})

    def test_stale_bridge_health_blocks_all(self):
        p = sample()
        p["bridge"]["observed_at"] = (NOW - timedelta(minutes=7)).isoformat()
        view = evaluate_snapshot(p, now=NOW)
        self.assertFalse(view["bridge_ready"])
        self.assertEqual(set(view["statuses"].values()), {"BELUM_TERHUBUNG"})

    def test_fault_and_quarantine_not_ready(self):
        p = sample()
        p["symbols"][0]["quarantined"] = True
        p["symbols"][2]["fault"] = True
        view = evaluate_snapshot(p, now=NOW)
        self.assertEqual(view["statuses"]["XAUUSD"], "BLOKIR_NATIVE")
        self.assertEqual(view["statuses"]["BTCUSD"], "BLOKIR_NATIVE")

    def test_wrong_identity_fails_closed(self):
        p = sample()
        p["symbols"][1]["identity_ok"] = False
        view = evaluate_snapshot(p, now=NOW)
        self.assertEqual(view["statuses"]["EURUSD"], "IDENTITAS_BERMASALAH")
        p["source_release"] = "V1.3.0"
        with self.assertRaises(ValueError):
            evaluate_snapshot(p, now=NOW)

    def test_replaced_algo_checkpoint_is_not_misreported_as_connected(self):
        p = sample()
        p["symbols"][0]["unrecognized_checkpoint"] = True
        view = evaluate_snapshot(p, now=NOW)
        self.assertEqual(view["statuses"]["XAUUSD"], "ALGO_PERLU_VERIFIKASI")
        self.assertEqual(view["statuses"]["EURUSD"], "TERPANTAU")

    def test_healthy_bridge_does_not_override_missing_checkpoint(self):
        p = sample()
        p["symbols"][2]["checkpoint_present"] = False
        self.assertEqual(
            evaluate_snapshot(p, now=NOW)["statuses"]["BTCUSD"],
            "IDENTITAS_BERMASALAH",
        )

    def test_contract_requires_all_three_symbols(self):
        p = sample()
        p["symbols"].pop()
        with self.assertRaises(ValueError):
            evaluate_snapshot(p, now=NOW)

    def test_lease_expired_not_claimed_connected(self):
        p = sample()
        p["symbols"][2]["lease_active"] = False
        self.assertEqual(evaluate_snapshot(p, now=NOW)["statuses"]["BTCUSD"], "BELUM_TERHUBUNG")

    def test_explicitly_old_lease_cannot_claim_live_readiness(self):
        p = sample()
        p["symbols"][0]["lease_touched_at"] = (NOW - timedelta(minutes=4)).isoformat()
        p["symbols"][1]["lease_touched_at"] = (NOW - timedelta(seconds=20)).isoformat()
        view = evaluate_snapshot(p, now=NOW)
        self.assertEqual(view["statuses"]["XAUUSD"], "LEASE_TERLAMBAT")
        self.assertEqual(view["lease_freshness"]["XAUUSD"], False)
        self.assertEqual(view["statuses"]["EURUSD"], "TERPANTAU")
        self.assertEqual(view["lease_freshness"]["EURUSD"], True)
        self.assertIsNone(view["lease_freshness"]["BTCUSD"])

    def test_explicitly_future_lease_is_unverified(self):
        p = sample()
        p["symbols"][2]["lease_touched_at"] = (NOW + timedelta(minutes=5)).isoformat()
        view = evaluate_snapshot(p, now=NOW)
        self.assertEqual(view["statuses"]["BTCUSD"], "LEASE_TERLAMBAT")

    def test_reader_identifies_exact_frozen_keys(self):
        x = checkpoint_symbol("TPX_13bfa137:1237903:XAUUSD")
        e = checkpoint_symbol("TPE_13bfa137:1237903:EURUSD")
        b = checkpoint_symbol("TPBTC:" + PROFILE + ":1237903:BTCUSD")
        self.assertEqual((x[0], e[0], b[0]), ("XAUUSD", "EURUSD", "BTCUSD"))
        self.assertIsNone(checkpoint_symbol("RZXRC1:1237903:XAUUSD"))
        self.assertIsNone(checkpoint_symbol("TPX_13bfa137:1237899:XAUUSD"))
        self.assertIsNone(checkpoint_symbol("TPBTC:wrong:1237903:BTCUSD"))


if __name__ == "__main__":
    unittest.main()

"""Regression tests for P3 read-only heartbeat presentation."""
import unittest
from datetime import UTC, datetime

from fx_scanner.runtime_telemetry_labels import annotate_heartbeat_rows


class RuntimeTelemetryLabelsTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 24, 12, 0, 0, tzinfo=UTC)

    def test_old_unhealthy_bridge_is_archive_not_current_live_failure(self):
        raw = {"worker_name": "cbot_bridge_xauusd",
               "observed_at": "2026-10-11T12:38:45Z", "healthy": False}
        output = annotate_heartbeat_rows([raw], now=self.now)[0]
        self.assertEqual(output["telemetry_interpretation"],
                         "ARSIP / BELUM TERVERIFIKASI LIVE")
        self.assertEqual(output["telemetry_origin"],
                         "ARSIP BRIDGE DB (bukan verifikasi LIVE)")
        self.assertFalse(output["healthy"])
        self.assertNotIn("telemetry_origin", raw)

    def test_recent_bridge_still_not_proof_of_websocket(self):
        row = {"worker_name": "cbot_bridge_eurusd",
               "observed_at": "2026-10-24T11:59:00Z", "healthy": True}
        classified = annotate_heartbeat_rows((row,), now=self.now)[0]
        self.assertEqual(classified["telemetry_interpretation"],
                         "RECORD BARU / KONEKSI LIVE BELUM TERVERIFIKASI")
        self.assertEqual(classified["telemetry_age_minutes"], 1.0)

    def test_old_worker_is_historical_and_bad_timestamp_is_invalid(self):
        rows = [{"worker_name": "research_worker",
                 "observed_at": "2026-10-01T00:00:00Z", "healthy": True},
                {"worker_name": "cbot_bridge_btcusd",
                 "observed_at": "unknown", "healthy": True}]
        classified = annotate_heartbeat_rows(rows, now=self.now)
        self.assertEqual(classified[0]["telemetry_interpretation"],
                         "DATA HISTORIS (bukan status kini)")
        self.assertEqual(classified[1]["telemetry_interpretation"],
                         "WAKTU TIDAK VALID")
        self.assertIsNone(classified[1]["telemetry_age_minutes"])

    def test_future_timestamp_rejected(self):
        row = {"worker_name": "cbot_bridge_xauusd",
               "observed_at": "2026-10-24T13:00:00Z"}
        self.assertEqual(annotate_heartbeat_rows([row], now=self.now)[0]
                         ["telemetry_interpretation"], "WAKTU TIDAK VALID")


if __name__ == "__main__":
    unittest.main()

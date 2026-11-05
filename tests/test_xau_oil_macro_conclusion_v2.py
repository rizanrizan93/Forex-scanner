"""Unit tests for independent, non-trading Oil conclusions."""
from __future__ import annotations

import sys
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from fx_scanner.xau_oil_macro_context import assess_oil_macro


NOW = datetime(2026, 11, 5, 12, 40, tzinfo=UTC)


def quote(pct, *, source="Yahoo Finance · kemungkinan tertunda",
          observed=None, basis="penutupan sebelumnya", value=90.0):
    return {
        "value": value, "pct": pct, "fresh": True, "source": source,
        "basis": basis,
        "observed": (observed or (NOW - timedelta(minutes=20))).isoformat(),
    }


class OilContextTests(unittest.TestCase):
    def test_rising_oil_is_only_conditional_bearish_via_inflation(self):
        r = assess_oil_macro({"WTI": quote(1.0), "Brent": quote(1.85)}, NOW)
        self.assertEqual(r["status"], "INTRADAY")
        self.assertEqual(r["trend"], "NAIK")
        self.assertEqual(r["xau_inflation_bias"], "BEARISH BERSYARAT")
        self.assertFalse(r["score_influence"])
        self.assertIn("geopolitik", r["safe_haven_path"].lower())

    def test_falling_oil_is_only_conditional_bullish_via_inflation(self):
        r = assess_oil_macro({"WTI": quote(-1.0), "Brent": quote(-1.85)}, NOW)
        self.assertEqual(r["trend"], "TURUN")
        self.assertEqual(r["xau_inflation_bias"], "BULLISH BERSYARAT")

    def test_mixed_or_small_change_not_directional(self):
        r = assess_oil_macro({"WTI": quote(0.11), "Brent": quote(-0.8)}, NOW)
        self.assertEqual(r["trend"], "MIXED/FLAT")
        self.assertEqual(r["xau_inflation_bias"], "NETRAL")

    def test_stale_and_future_data_fail_closed(self):
        for at in (NOW - timedelta(hours=3), NOW + timedelta(minutes=10)):
            r = assess_oil_macro({"WTI": quote(1, observed=at), "Brent": quote(1)}, NOW)
            self.assertEqual(r["status"], "BELUM LENGKAP")
            self.assertEqual(r["trend"], "UNKNOWN")

    def test_fred_daily_not_mislabeled_intraday(self):
        at = datetime(2026, 11, 4, tzinfo=UTC)
        source = "FRED (spot harian)"
        r = assess_oil_macro({
            "WTI": quote(-1, source=source, observed=at, basis="observasi sebelumnya"),
            "Brent": quote(-2, source=source, observed=at, basis="observasi sebelumnya"),
        }, NOW)
        self.assertEqual(r["status"], "HARIAN")
        self.assertEqual(r["trend"], "TURUN")

    def test_mixed_cadence_or_basis_is_not_comparable(self):
        r = assess_oil_macro({
            "WTI": quote(1), "Brent": quote(
                2, source="FRED (spot harian)",
                observed=datetime(2026, 11, 4, tzinfo=UTC),
                basis="observasi sebelumnya"
            )
        }, NOW)
        self.assertEqual(r["status"], "TIDAK SEBANDING")
        self.assertEqual(r["trend"], "UNKNOWN")

    def test_missing_quote_is_unavailable(self):
        r = assess_oil_macro({"WTI": quote(1)}, NOW)
        self.assertEqual(r["status"], "BELUM LENGKAP")


if __name__ == "__main__":
    unittest.main()

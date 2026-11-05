"""Regression for Macro panel availability and Oil fallback behavior."""
from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta

from fx_scanner.xau_macro_risk_monitor import _market_or_fred, _yield_row


class MacroPanelResilienceTests(unittest.TestCase):
    def test_missing_macro_worker_payload_is_not_a_crash(self):
        self.assertEqual(_yield_row(None, None, "US2Y"), {})

    def test_stale_cached_futures_quote_falls_back_to_daily_fred(self):
        now = datetime.now(UTC)
        feeds = {
            "market": {
                "CL=F": {
                    "value": 95.0, "pct": 2.0,
                    "observed": (now - timedelta(minutes=15)).isoformat(),
                    "fresh": True,  # stale cached flag must not be trusted
                    "source": "CNBC Quote Cache · futures exchange-delayed",
                    "basis": "penutupan sebelumnya",
                }
            },
            "fred": {
                "DCOILWTICO": [
                    ((now - timedelta(days=2)).date().isoformat(), 90.0),
                    ((now - timedelta(days=1)).date().isoformat(), 92.0),
                ]
            },
        }
        quote = _market_or_fred("CL=F", "DCOILWTICO", feeds)
        self.assertEqual(quote["source"], "FRED (spot harian)")
        self.assertAlmostEqual(quote["pct"], 100 * (92.0 / 90.0 - 1))
        self.assertEqual(quote["basis"], "observasi sebelumnya")

    def test_fresh_futures_quote_keeps_intraday_priority(self):
        now = datetime.now(UTC)
        source = {"value": 95.0, "pct": 1.2,
                  "observed": (now - timedelta(seconds=40)).isoformat(),
                  "fresh": True,
                  "source": "CNBC Quote Cache · futures exchange-delayed",
                  "basis": "penutupan sebelumnya"}
        feeds = {"market": {"CL=F": source}, "fred": {}}
        self.assertIs(_market_or_fred("CL=F", "DCOILWTICO", feeds), source)

    def test_zero_fred_reference_never_divides_by_zero(self):
        now = datetime.now(UTC)
        source = {"value": 95.0, "pct": 1.2,
                  "observed": (now - timedelta(minutes=10)).isoformat(),
                  "fresh": False}
        feeds = {"market": {"CL=F": source},
                 "fred": {"DCOILWTICO": [
                     ((now - timedelta(days=2)).date().isoformat(), 0.0),
                     ((now - timedelta(days=1)).date().isoformat(), 90.0),
                 ]}}
        self.assertIs(_market_or_fred("CL=F", "DCOILWTICO", feeds), source)


if __name__ == "__main__":
    unittest.main()

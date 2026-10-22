"""Fail-closed tests for read-only XAU macro synthesis."""
from __future__ import annotations

import sys
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from fx_scanner.xau_macro_gold_consensus import analyze_gold_macro


NOW = datetime(2026, 10, 22, 12, 0, tzinfo=UTC)


def fresh_yields(real=-3, us2=-2, us10=-2, observed=None):
    at = (observed or NOW - timedelta(days=1)).isoformat()
    def item(delta):
        return {
            "delta": delta, "current": 4.0, "observed_at": at,
            "provider": "FEDERAL_RESERVE_H15", "freshness": "FRESH",
        }
    return {
        "REAL_YIELD_10Y": item(real),
        "US2Y": item(us2),
        "US10Y": item(us10),
    }


def fresh_dxy(change=-0.18, observed=None):
    return {
        "pct": change, "fresh": True,
        "source": "YAHOO_FINANCE_ICE_DXY_PROXY",
        "observed": (observed or NOW - timedelta(minutes=10)).isoformat(),
        "basis": "reference",
    }


class GoldMacroConsensusTests(unittest.TestCase):
    def test_bullish_alignment(self):
        result = analyze_gold_macro(
            yields=fresh_yields(), dxy=fresh_dxy(), now=NOW
        )
        self.assertEqual(result["bias"], "BULLISH XAU")
        self.assertGreater(result["score"], 50)
        self.assertEqual(result["coverage_pct"], 100)
        self.assertIs(result["execution_authority"], False)

    def test_bearish_alignment(self):
        result = analyze_gold_macro(
            yields=fresh_yields(real=3, us2=2, us10=2),
            dxy=fresh_dxy(change=0.20), now=NOW
        )
        self.assertEqual(result["bias"], "BEARISH XAU")
        self.assertLess(result["score"], -50)

    def test_conflict_not_forced_to_trade(self):
        result = analyze_gold_macro(
            yields=fresh_yields(real=-3, us2=2, us10=-3),
            dxy=fresh_dxy(change=0.10), now=NOW
        )
        self.assertEqual(result["state"], "CONFLICT")
        self.assertEqual(result["bias"], "NETRAL / MIXED")
        self.assertIn("KONFLIK", result["strength"])

    def test_stale_dxy_blocks_direction(self):
        result = analyze_gold_macro(
            yields=fresh_yields(), dxy=fresh_dxy(
                observed=NOW - timedelta(hours=5)
            ), now=NOW
        )
        self.assertEqual(result["bias"], "DATA TIDAK CUKUP")
        self.assertIsNone(result["score"])
        self.assertEqual(result["state"], "WAIT_DATA")

    def test_only_one_yield_blocks_direction(self):
        yields = fresh_yields()
        yields["US2Y"]["freshness"] = "STALE"
        yields["US10Y"]["freshness"] = "STALE"
        result = analyze_gold_macro(
            yields=yields, dxy=fresh_dxy(), now=NOW
        )
        self.assertEqual(result["state"], "WAIT_DATA")

    def test_inflation_oil_and_metals_are_context_only(self):
        base = analyze_gold_macro(
            yields=fresh_yields(), dxy=fresh_dxy(), now=NOW
        )
        contextual = analyze_gold_macro(
            yields=fresh_yields(), dxy=fresh_dxy(),
            pce_yoy=5.0, cpi_yoy=5.6,
            oil={
                "WTI": {"fresh": True, "pct": 5},
                "Brent": {"fresh": True, "pct": 6},
            },
            metals={
                "Gold": {"fresh": True, "pct": -1},
                "Silver": {"fresh": True, "pct": -2},
            },
            fed_repricing={"state": "HAWKISH_REPRICING_PROXY", "delta_bps": 5},
            now=NOW,
        )
        self.assertEqual(base["score"], contextual["score"])
        self.assertEqual(base["bias"], contextual["bias"])
        self.assertTrue(any("Fed repricing" in x for x in contextual["context"]))

    def test_freshness_label_is_not_enough_if_future_timestamp(self):
        future = NOW + timedelta(days=2)
        result = analyze_gold_macro(
            yields=fresh_yields(observed=future),
            dxy=fresh_dxy(), now=NOW
        )
        self.assertEqual(result["state"], "WAIT_DATA")


if __name__ == "__main__":
    unittest.main()

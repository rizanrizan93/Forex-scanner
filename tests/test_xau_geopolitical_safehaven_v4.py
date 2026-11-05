"""Geopolitical reporting and cross-asset safe-haven risk regression."""
from __future__ import annotations
import sys
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fx_scanner.xau_geopolitical_safehaven import assess_geopolitical_safehaven
from fx_scanner.xau_macro_gold_consensus import analyze_gold_macro

NOW = datetime(2026, 11, 5, 13, 0, tzinfo=UTC)

def news(domain, title="Iran missile strike reported", *, hours=1):
    return {
        "url": f"https://{domain}/world/example",
        "title": title,
        "observed": (NOW - timedelta(hours=hours)).isoformat(),
    }

def quote(pct, *, minutes=5, fresh=True):
    return {"pct": pct, "value": 110, "fresh": fresh,
            "source": "Yahoo Finance · kemungkinan tertunda",
            "basis": "penutupan sebelumnya",
            "observed": (NOW - timedelta(minutes=minutes)).isoformat()}

def markets(vix=5, jpy=-0.25, chf=-0.1):
    return {"^VIX": quote(vix), "JPY=X": quote(jpy), "CHF=X": quote(chf)}

def core_inputs():
    at = (NOW - timedelta(days=1)).isoformat()
    return {
        "yields": {k: {"delta": 2, "observed_at": at, "freshness": "FRESH",
                       "provider": "FEDERAL_RESERVE_H15"}
                   for k in ("REAL_YIELD_10Y", "US2Y", "US10Y")},
        "dxy": {"pct": 0, "fresh": True, "observed": (NOW - timedelta(minutes=5)).isoformat()},
    }

class GeoSafeHavenTests(unittest.TestCase):
    def test_corroborated_geopolitical_plus_safe_haven_raise_score(self):
        articles = [news("reuters.com"), news("apnews.com")]
        r = assess_geopolitical_safehaven(
            articles=articles, markets=markets(), now=NOW)
        self.assertEqual(r["geopolitical_vote"], 1)
        self.assertEqual(r["safehaven_vote"], 1)
        self.assertEqual(r["total_weight"], 0.1)
        result = analyze_gold_macro(**core_inputs(), geopolitical_articles=articles,
                 haven_markets=markets(), now=NOW)
        self.assertEqual(result["geo_weight_pct"], 5)
        self.assertEqual(result["haven_weight_pct"], 5)
        self.assertEqual(result["score"], -40)  # legacy -55*0.9 + 10 = -39.5
        self.assertFalse(result["execution_authority"])

    def test_no_news_cannot_create_geopolitical_score(self):
        r = assess_geopolitical_safehaven(
            articles=[], markets=markets(), now=NOW, news_error="TimeoutError")
        self.assertIsNone(r["geopolitical_vote"])
        self.assertEqual(r["safehaven_vote"], 1)
        self.assertEqual(r["geo_weight"], 0)
        self.assertEqual(r["haven_weight"], 0.05)

    def test_single_news_source_does_not_score_geopolitics(self):
        r = assess_geopolitical_safehaven(
            articles=[news("reuters.com")], markets=markets(), now=NOW)
        self.assertIsNone(r["geopolitical_vote"])

    def test_fake_domain_and_stale_news_rejected(self):
        r = assess_geopolitical_safehaven(
            articles=[news("fake-reuters.com"), news("apnews.com", hours=20)],
            markets=markets(), now=NOW)
        self.assertIsNone(r["geopolitical_vote"])

    def test_different_regions_cannot_corroborate_each_other(self):
        r = assess_geopolitical_safehaven(
            articles=[news("reuters.com"), news("apnews.com", "Ukraine missile attack")],
            markets=markets(), now=NOW)
        self.assertIsNone(r["geopolitical_vote"])

    def test_unconfirmed_hypothetical_headlines_not_scored(self):
        r = assess_geopolitical_safehaven(
            articles=[
                news("reuters.com", "Iran could face missile strike"),
                news("apnews.com", "Iran warns of missile strike"),
            ], markets=markets(), now=NOW)
        self.assertIsNone(r["geopolitical_vote"])

    def test_oil_alone_never_proves_geopolitics(self):
        result = analyze_gold_macro(**core_inputs(),
                oil={"WTI": {"fresh": True, "pct": 8},
                     "Brent": {"fresh": True, "pct": 7}}, now=NOW)
        self.assertEqual(result["geo_weight_pct"], 0)
        self.assertEqual(result["haven_weight_pct"], 0)

    def test_vix_without_haven_currency_is_not_safehaven_confirmation(self):
        r = assess_geopolitical_safehaven(
            articles=[], markets=markets(vix=7, jpy=0.1, chf=0.1), now=NOW)
        self.assertIsNone(r["safehaven_vote"])

    def test_risk_on_can_pull_score_down_but_not_imply_geopolitics(self):
        r = assess_geopolitical_safehaven(
            articles=[], markets=markets(vix=-5, jpy=0.3, chf=0.4), now=NOW)
        self.assertEqual(r["safehaven_vote"], -1)
        self.assertIsNone(r["geopolitical_vote"])

    def test_stale_vix_and_quotes_cannot_score(self):
        m = markets()
        m["^VIX"] = quote(9, minutes=120)
        r = assess_geopolitical_safehaven(
            articles=[news("reuters.com"), news("apnews.com")],
            markets=m, now=NOW)
        self.assertIsNone(r["safehaven_vote"])
        # A single fresh FX currency may still give corroboration to an
        # independently cross-published geopolitical story.
        self.assertEqual(r["geopolitical_vote"], 1)

if __name__ == "__main__":
    unittest.main()

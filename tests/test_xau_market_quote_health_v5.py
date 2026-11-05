"""Time-aware, fail-closed tests for delayed macro market quotes."""
from __future__ import annotations
import sys, unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1] / "src"))
from fx_scanner.xau_market_quote_health import quote_freshness
from fx_scanner.xau_macro_gold_consensus import analyze_gold_macro
from fx_scanner.xau_geopolitical_safehaven import assess_geopolitical_safehaven

NOW=datetime(2026,11,6,2,33,tzinfo=UTC)
def quote(minutes,pct=1):
    return {"observed":(NOW-timedelta(minutes=minutes)).isoformat(),
            "fresh":True,"value":101.56,"pct":pct,
            "source":"Yahoo Finance · kemungkinan tertunda","basis":"penutupan sebelumnya"}
def yields():
    at=(NOW-timedelta(days=1)).isoformat()
    return {x:{"delta":2,"observed_at":at,"freshness":"FRESH","provider":"FRED"}
            for x in ("US2Y","US10Y","REAL_YIELD_10Y")}
class QuoteTimestampTests(unittest.TestCase):
    def test_screenshot_quote_is_delayed(self):
        h=quote_freshness(quote(10.7),now=NOW)
        self.assertEqual(h["status"],"DELAYED")
        self.assertEqual(h["age_minutes"],10.7)
        self.assertFalse(h["eligible"])
    def test_five_minute_gate(self):
        self.assertTrue(quote_freshness(quote(5),now=NOW)["eligible"])
        self.assertFalse(quote_freshness(quote(5.1),now=NOW)["eligible"])
    def test_daily_is_context(self):
        d=quote(1440);d["source"]="FRED (spot harian)"
        self.assertEqual(quote_freshness(d,now=NOW)["status"],"HARIAN — BUKAN LIVE")
    def test_stale_dxy_must_not_move_macro(self):
        r=analyze_gold_macro(yields=yields(),dxy=quote(10.7),now=NOW)
        self.assertIsNone(r["score"])
        self.assertEqual(r["state"],"WAIT_DATA")
    def test_stale_vix_jpy_chf_must_not_vote(self):
        m={"^VIX":quote(10.7,7),"JPY=X":quote(10.7,-.3),"CHF=X":quote(10.7,-.3)}
        r=assess_geopolitical_safehaven(articles=[],markets=m,now=NOW)
        self.assertIsNone(r["safehaven_vote"])
        self.assertEqual(r["haven_weight"],0)
    def test_future_timestamp_invalid(self):
        self.assertEqual(quote_freshness(quote(-1),now=NOW)["status"],"INVALID_TIMESTAMP")
if __name__=="__main__":
    unittest.main()

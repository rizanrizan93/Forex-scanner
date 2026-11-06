"""Official FRED fallback and separate daily regime must never imply live data."""
from __future__ import annotations
import sys
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from fx_scanner.xau_macro_daily_regime import (
    assess_daily_regime, fred_daily_yield_row
)
NOW = datetime(2026,11,6,0,3,tzinfo=UTC)

def rows():
    return {symbol:{
        "freshness":"FRESH",
        "delta": 2.0,
        "observed_at":(NOW-timedelta(days=1)).isoformat(),
        "provider":"FEDERAL_RESERVE_H15",
    } for symbol in ("REAL_YIELD_10Y","US2Y","US10Y")}

def close(hours=4):
    return {
        "value":101.56, "pct":-0.10, "observed":(NOW-timedelta(hours=hours)).isoformat(),
        "source":"CNBC Quote Cache · market quote",
        "basis":"penutupan sebelumnya", "fresh":False,
    }

class DailyRegimeTests(unittest.TestCase):
    def test_closed_session_can_use_last_dxy_and_official_treasury(self):
        r=assess_daily_regime(yields=rows(),dxy_last=close(4),now=NOW)
        self.assertEqual(r["status"],"REGIME_HARIAN_TERSEDIA")
        self.assertEqual(r["bias"],"BEARISH REGIME")
        self.assertEqual(r["score"],-10)
        self.assertEqual(r["coverage_pct"],100)
        self.assertFalse(r["execution_authority"])

    def test_yields_from_fred_are_real_daily_not_live(self):
        obs=[("2026-11-03",4.5),("2026-11-04",4.6),("2026-11-05",4.62)]
        row=fred_daily_yield_row("US10Y",obs,now=NOW)
        self.assertEqual(row["provider"],"FRED_OFFICIAL_DAILY")
        self.assertEqual(row["delta"],2.0)
        self.assertIn("2026-11-05",row["observed_at"])

    def test_fred_missing_or_too_old_is_not_accepted(self):
        self.assertIsNone(fred_daily_yield_row("US10Y",[],now=NOW))
        self.assertIsNone(fred_daily_yield_row(
            "US10Y",[("2026-10-20",4.6),("2026-10-25",4.7)],now=NOW))

    def test_daily_regime_not_guaranteed_when_sources_disappear(self):
        r=assess_daily_regime(yields={},dxy_last={},now=NOW)
        self.assertEqual(r["status"],"WAIT_DAILY_DATA")
        self.assertIsNone(r["score"])
        self.assertEqual(r["coverage_pct"],0)

    def test_old_dxy_cannot_be_laundered_as_daily(self):
        r=assess_daily_regime(yields=rows(),dxy_last=close(125),now=NOW)
        self.assertIsNone(r["score"])
        self.assertEqual(r["coverage_pct"],55)

    def test_unknown_dxy_source_is_not_counted(self):
        r=assess_daily_regime(yields=rows(),dxy_last={
            **close(4),"source":"Unknown synthetic",
        },now=NOW)
        self.assertIsNone(r["score"])

    def test_daily_rejects_unaligned_observations(self):
        r=assess_daily_regime(yields=rows(),dxy_last=close(90),now=NOW)
        self.assertIsNone(r["score"])

    def test_at_least_two_valid_yields_required(self):
        y=rows()
        y["US2Y"]["freshness"]="STALE"
        y["US10Y"]["freshness"]="STALE"
        r=assess_daily_regime(yields=y,dxy_last=close(4),now=NOW)
        self.assertIsNone(r["score"])
        self.assertEqual(r["status"],"WAIT_DAILY_DATA")

    def test_crossing_midnight_without_market_updates_does_not_change_score(self):
        a=assess_daily_regime(yields=rows(),dxy_last=close(4),now=NOW)
        b=assess_daily_regime(yields=rows(),dxy_last=close(4),
                              now=NOW+timedelta(minutes=15))
        self.assertEqual(a["score"],b["score"])

if __name__ == "__main__":
    unittest.main()

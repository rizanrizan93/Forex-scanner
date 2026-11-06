"""Focused regression for adaptive, quality-gated Oil score weighting."""
from __future__ import annotations
import sys
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from fx_scanner.xau_macro_gold_consensus import analyze_gold_macro

NOW = datetime(2026, 11, 5, 12, 45, tzinfo=UTC)

def yields(delta=2):
    observed = (NOW - timedelta(days=1)).isoformat()
    return {key: {"delta": delta, "observed_at": observed,
                  "freshness": "FRESH", "provider": "FRED"}
            for key in ("REAL_YIELD_10Y", "US2Y", "US10Y")}

def dxy(pct=0):
    return {"pct": pct, "observed": (NOW - timedelta(minutes=5)).isoformat(),
            "fresh": True, "source": "Yahoo", "basis": "previous"}

def quote(pct, *, daily=False, hours_ago=2/60, basis=None):
    return {
        "pct": pct, "value": 90,
        "source": "FRED (spot harian)" if daily else "Yahoo Finance · kemungkinan tertunda",
        "observed": (NOW - timedelta(hours=hours_ago)).isoformat(),
        "fresh": True,
        "basis": basis or ("observasi sebelumnya" if daily else "penutupan sebelumnya"),
    }

def oil(pct, **kwargs):
    return {"WTI": quote(pct, **kwargs), "Brent": quote(pct, **kwargs)}

class WeightedOilScoreTests(unittest.TestCase):
    def test_missing_oil_keeps_previous_minus_55_score(self):
        result = analyze_gold_macro(yields=yields(2), dxy=dxy(0), now=NOW)
        self.assertEqual(result["score"], -55)
        self.assertEqual(result["oil_weight_pct"], 0)
        self.assertIsNone(result["score_breakdown"]["Oil"])


    def test_six_minute_oil_quote_must_not_shift_macro_score(self):
        result = analyze_gold_macro(yields=yields(2), dxy=dxy(0),
                                    oil=oil(2, hours_ago=6/60), now=NOW)
        self.assertEqual(result["score"], -55)
        self.assertEqual(result["oil_weight_pct"], 0)
        self.assertEqual(result["oil_assessment"]["quotes"]["WTI"]["status"], "DELAYED")

    def test_cnbc_delayed_futures_no_longer_contribute_to_spot_only_macro(self):
        raw = {
            "value": 91.36, "pct": 1.5, "fresh": False,
            "source": "CNBC Quote Cache · futures exchange-delayed",
            "basis": "penutupan sebelumnya", "instrument_type": "FUTURES",
            "provider_realtime": False,
            "observed": (NOW - timedelta(minutes=10)).isoformat(),
        }
        r = analyze_gold_macro(yields=yields(), dxy=dxy(),
                               oil={"WTI": raw, "Brent": dict(raw)}, now=NOW)
        self.assertEqual(r["oil_assessment"]["status"], "FUTURES_DELAYED")
        self.assertEqual(r["oil_weight_pct"], 0)
        self.assertIsNone(r["score_breakdown"]["Oil"])
        self.assertEqual(r["score"], -55)
        self.assertFalse(r["oil_score_counted"])
        self.assertFalse(r["execution_authority"])

    def test_source_derived_dia_spot_momentum_caps_oil_at_five_percent(self):
        spot = {
            "value": 91, "pct": 1.0,
            "source": "DIA RWA · spot minyak indikatif",
            "basis": "perubahan spot 10–20 menit",
            "instrument_type": "SPOT", "fresh": True,
            "observed": (NOW - timedelta(minutes=1)).isoformat(),
        }
        r = analyze_gold_macro(yields=yields(), dxy=dxy(),
                               oil={"WTI": spot, "Brent": dict(spot)}, now=NOW)
        self.assertEqual(r["oil_assessment"]["status"], "SPOT_MOMENTUM")
        self.assertEqual(r["oil_weight_pct"], 5)
        self.assertEqual(r["score_breakdown"]["Oil"], -5)
        self.assertFalse(r["execution_authority"])

    def test_delayed_futures_beyond_fifteen_minutes_never_affect_score(self):
        raw = {
            "value": 91.36, "pct": 1.5, "fresh": False,
            "source": "CNBC Quote Cache · futures exchange-delayed",
            "basis": "penutupan sebelumnya", "instrument_type": "FUTURES",
            "provider_realtime": False,
            "observed": (NOW - timedelta(minutes=16)).isoformat(),
        }
        r = analyze_gold_macro(yields=yields(), dxy=dxy(),
                               oil={"WTI": raw, "Brent": dict(raw)}, now=NOW)
        self.assertEqual(r["oil_weight_pct"], 0)
        self.assertEqual(r["score"], -55)

    def test_delayed_futures_requires_vendor_delay_flag(self):
        raw = {
            "value": 91.36, "pct": 1.5, "fresh": False,
            "source": "CNBC Quote Cache · futures exchange-delayed",
            "basis": "penutupan sebelumnya", "instrument_type": "FUTURES",
            "observed": (NOW - timedelta(minutes=10)).isoformat(),
        }
        r = analyze_gold_macro(yields=yields(), dxy=dxy(),
                               oil={"WTI": raw, "Brent": dict(raw)}, now=NOW)
        self.assertEqual(r["oil_weight_pct"], 0)

    def test_delayed_futures_requires_aligned_observation_times(self):
        raw = {
            "value": 91.36, "pct": 1.5, "fresh": False,
            "source": "CNBC Quote Cache · futures exchange-delayed",
            "basis": "penutupan sebelumnya", "instrument_type": "FUTURES",
            "provider_realtime": False,
            "observed": (NOW - timedelta(minutes=10)).isoformat(),
        }
        brent = dict(raw)
        brent["observed"] = (NOW - timedelta(minutes=7)).isoformat()
        r = analyze_gold_macro(yields=yields(), dxy=dxy(),
                               oil={"WTI": raw, "Brent": brent}, now=NOW)
        self.assertEqual(r["oil_assessment"]["status"], "TIDAK SEBANDING")
        self.assertEqual(r["oil_weight_pct"], 0)

    def test_one_minute_oil_quote_can_shift_macro_score(self):
        result = analyze_gold_macro(yields=yields(2), dxy=dxy(0),
                                    oil=oil(2, hours_ago=1/60), now=NOW)
        self.assertEqual(result["oil_weight_pct"], 15)
        self.assertEqual(result["score"], -62)
    def test_rising_oil_makes_score_more_bearish(self):
        result = analyze_gold_macro(yields=yields(2), dxy=dxy(0),
                                    oil=oil(1), now=NOW)
        self.assertEqual(result["core_score"], -55)
        self.assertEqual(result["score"], -62)  # -46.75 - 15 => -61.75
        self.assertEqual(result["oil_weight_pct"], 15)
        self.assertTrue(result["oil_score_counted"])
        self.assertIn("Oil WTI+Brent (inflasi)",
                      [x["name"] for x in result["bearish"]])

    def test_falling_oil_offsets_bearish_yields(self):
        result = analyze_gold_macro(yields=yields(2), dxy=dxy(0),
                                    oil=oil(-1), now=NOW)
        self.assertEqual(result["core_score"], -55)
        self.assertEqual(result["score"], -32)  # -46.75 + 15 => -31.75
        self.assertEqual(result["state"], "OIL_CONFLICT")
        self.assertIn("KONFLIK", result["strength"])

    def test_mixed_oil_is_neutral_vote_not_opinionated(self):
        result = analyze_gold_macro(yields=yields(2), dxy=dxy(0),
            oil={"WTI": quote(1), "Brent": quote(-1)}, now=NOW)
        self.assertEqual(result["oil_weight_pct"], 15)
        self.assertEqual(result["score"], -47)
        self.assertEqual(result["score_breakdown"]["Oil"], 0)

    def test_valid_daily_oil_has_reduced_weight(self):
        result = analyze_gold_macro(yields=yields(2), dxy=dxy(0),
                                    oil=oil(2, daily=True, hours_ago=24),
                                    now=NOW)
        self.assertEqual(result["oil_weight_pct"], 8)
        self.assertEqual(result["score"], -59)  # -.92*55 - 8 = -58.6

    def test_old_daily_and_stale_futures_cannot_shift_score(self):
        for candidate in (oil(2, daily=True, hours_ago=72),
                          oil(2, hours_ago=3)):
            result = analyze_gold_macro(yields=yields(2), dxy=dxy(0),
                                        oil=candidate, now=NOW)
            self.assertEqual(result["score"], -55)
            self.assertEqual(result["oil_weight_pct"], 0)

    def test_bad_basis_cannot_shift_score(self):
        bad = {"WTI": quote(1, basis="yesterday"),
               "Brent": quote(1, basis="last-week")}
        result = analyze_gold_macro(yields=yields(2), dxy=dxy(0),
                                    oil=bad, now=NOW)
        self.assertEqual(result["score"], -55)
        self.assertFalse(result["oil_score_counted"])

    def test_oil_never_overrides_missing_core(self):
        bad_dxy = dxy(0)
        bad_dxy["observed"] = (NOW - timedelta(hours=3)).isoformat()
        result = analyze_gold_macro(yields=yields(2), dxy=bad_dxy,
                                    oil=oil(2), now=NOW)
        self.assertIsNone(result["score"])
        self.assertEqual(result["state"], "WAIT_DATA")
        self.assertFalse(result["execution_authority"])

    def test_non_oil_inflation_fed_metals_do_not_get_extra_weight(self):
        clean = analyze_gold_macro(yields=yields(2), dxy=dxy(0),
                                   oil=oil(1), now=NOW)
        contextual = analyze_gold_macro(yields=yields(2), dxy=dxy(0),
            oil=oil(1), pce_yoy=4, cpi_yoy=4,
            fed_repricing={"state": "HAWKISH", "delta_bps": 8},
            metals={"Gold": {"fresh": True, "pct": 2},
                    "Silver": {"fresh": True, "pct": -2}}, now=NOW)
        self.assertEqual(clean["score"], contextual["score"])
        self.assertEqual(clean["model"], "EXPLAINABLE_HEURISTIC_V3_OIL_GEO_HAVEN_NOT_CALIBRATED")

if __name__ == "__main__":
    unittest.main()

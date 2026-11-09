"""Regression: a valid zero-point WTI+Brent vote is not a missing feed."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from fx_scanner.xau_macro_gold_consensus import explain_oil_component


def sample(*, trend="NAIK", score=-60, points=-15.0, counted=True, weight=15):
    oil = {
        "trend": trend,
        "status": "INTRADAY",
        "score_reason": "Spot DIA valid.",
        "wti": {"pct": 0.81},
        "brent": {"pct": 0.42},
    }
    return {
        "score": score,
        "oil_score_counted": counted,
        "oil_weight_pct": weight,
        "score_breakdown": {"Oil": points},
        "oil_assessment": oil,
    }


class OilCombinedVerdictTests(unittest.TestCase):
    def test_rising_energy_explicitly_bearish_conditional(self):
        out = explain_oil_component(sample())
        self.assertTrue(out["counted"])
        self.assertIn("BEARISH XAU BERSYARAT", out["headline"])
        self.assertIn("WTI +0.81%", out["detail"])
        self.assertIn("Brent +0.42%", out["detail"])
        self.assertIn("kontribusi -15.0 poin", out["detail"])

    def test_falling_energy_explicitly_bullish_conditional(self):
        out = explain_oil_component(sample(trend="TURUN", points=15.0))
        self.assertIn("BULLISH XAU BERSYARAT", out["headline"])

    def test_valid_zero_point_is_neutral_not_missing(self):
        out = explain_oil_component(sample(
            trend="MIXED/FLAT", points=0.0, weight=5,
        ))
        self.assertTrue(out["counted"])
        self.assertIn("NETRAL", out["headline"])
        self.assertIn("kontribusi +0.0 poin", out["detail"])
        self.assertIn("bobot 5%", out["detail"])

    def test_missing_or_incomplete_oil_not_fake_neutral(self):
        out = explain_oil_component(sample(
            counted=False, weight=0, points=None,
        ))
        self.assertFalse(out["counted"])
        self.assertIn("BELUM VALID", out["headline"])
        self.assertNotIn("NETRAL", out["headline"])

    def test_macro_wait_data_disables_oil_score_even_with_quote(self):
        out = explain_oil_component(sample(score=None, counted=False, points=None))
        self.assertFalse(out["counted"])
        self.assertIn("BELUM MASUK INDEKS", out["headline"])


if __name__ == "__main__":
    unittest.main()

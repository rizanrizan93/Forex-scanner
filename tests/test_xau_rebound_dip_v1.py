"""Read-only tactical XAU scenario regression tests."""
import unittest
from datetime import UTC, datetime, timedelta

from fx_scanner.xau_rebound_dip_v1 import evaluate_rebound_dip, macro_vote


NOW = datetime(2026, 11, 17, 2, 7, tzinfo=UTC)


def _series(count, minutes, end, first, step):
    rows = []
    for i in range(count):
        close = first + step * i
        rows.append({
            "closed_at": (end - timedelta(minutes=minutes * (count - 1 - i))).isoformat(),
            "open": close + .2,
            "high": close + 1.1,
            "low": close - 1.1,
            "close": close,
        })
    return rows


def _feed():
    return {
        "contract": "RIZAN_XAU_CLOSED_CANDLES_READONLY_V1",
        "symbol": "XAUUSD",
        "account_suffix": "7903",
        "source": "CTRADER_MARKET_DATA_READ_ONLY",
        "execution_authority": False,
        "execution_influence": False,
        "as_of": (NOW - timedelta(seconds=30)).isoformat(),
        "bars": {
            "H1": _series(220, 60, datetime(2026, 11, 17, 2, 0, tzinfo=UTC), 4010, -.5),
            "M15": _series(80, 15, datetime(2026, 11, 17, 2, 0, tzinfo=UTC), 3940, -.65),
            "M5": _series(40, 5, datetime(2026, 11, 17, 2, 5, tzinfo=UTC), 3867, -.12),
        },
    }


class ReboundDipTests(unittest.TestCase):
    def test_macro_direction_and_expired_actual(self):
        evaluation = {"attribution_quality": {
            "quality_state": "ALIGNED_CONTEXT_ONLY",
            "quality_screened_bias": "BEARISH_XAU",
            "event_quality": {
                "state": "VERIFIED_COOL",
                "event_time": (NOW - timedelta(hours=3)).isoformat(),
            },
        }}
        result = macro_vote(evaluation, {"usd_direction": "UP_WATCH"},
                            {"state": "CONCORDANT_PROXY", "yield_direction": "UP"}, NOW)
        self.assertEqual(result["direction"], "SELL")
        self.assertEqual(result["net_votes"], 4)

    def test_unverified_macro_is_not_fabricated(self):
        self.assertEqual(macro_vote({}, {}, {}, NOW)["direction"], "WAIT_DATA")

    def test_missing_market_data_waits_not_orders(self):
        report = evaluate_rebound_dip({}, {}, {}, {}, {}, {}, now=NOW)
        self.assertEqual(report["preferred"], "WAIT_DATA")
        self.assertFalse(report["order_enabled"])
        self.assertEqual(report["SELL"]["state"], "WAIT_DATA")

    def test_bearish_h1_plus_valid_macro_prefers_sell_watch(self):
        evaluation = {"attribution_quality": {
            "quality_state": "ALIGNED_CONTEXT_ONLY",
            "quality_screened_bias": "BEARISH_XAU",
        }}
        report = evaluate_rebound_dip(
            _feed(), {"errors": [], "SELL": {"items": []}, "BUY": {"items": []}},
            {}, {"usd_direction": "UP_WATCH"},
            {"state": "CONCORDANT_PROXY", "yield_direction": "UP"},
            evaluation, now=NOW
        )
        self.assertEqual(report["preferred"], "SELL_ON_REBOUND")
        self.assertTrue(report["SELL"]["zones"])
        self.assertFalse(report["order_enabled"])
        self.assertNotEqual(report["SELL"]["state"], "TRIGGER_SHADOW_VERIFY_RISK")


if __name__ == "__main__":
    unittest.main()

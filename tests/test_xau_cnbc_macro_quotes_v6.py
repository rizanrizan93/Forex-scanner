"""Isolated tests for fast public macro quote parser (network-free)."""
from __future__ import annotations
import sys
import unittest
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"src"))
from fx_scanner.xau_cnbc_macro_quotes import (
    CNBC_SYMBOLS, parse_cnbc_quotes, parse_goldapi_spot,
)
NOW=datetime(2026,11,5,20,15,tzinfo=UTC)

def row(sym, price, pct, minutes=1, realtime="true"):
    at=NOW-timedelta(minutes=minutes)
    return {"symbol":sym,"last":price,"change_pct":pct,
            "last_time":at.isoformat(),"realTime":realtime}

class CNBCMacroSourceTests(unittest.TestCase):
    def test_verified_batch_has_live_dxy_vix_jpy_chf_spot(self):
        payload={"FormattedQuoteResult":{"FormattedQuote":[
            row(".DXY","101.565","-0.02%"),
            row(".VIX","26.44","+56.77%"),
            row("JPY=","157.80","-0.3977%"),
            row("CHF=","0.8163","-0.08%"),
            row("XAU=","4,104.46","+1.15%"),
            row("XAG=","52.16","+0.04%"),
            row("@GC.1","4,120.40","+1.2%",minutes=10,realtime="false"),
            row("@CL.1","90.70","+2.5%",minutes=10,realtime="false"),
        ]}}
        r=parse_cnbc_quotes(payload,now=NOW)
        for symbol in ("DX-Y.NYB","^VIX","JPY=X","CHF=X","XAU_SPOT","XAG_SPOT"):
            self.assertTrue(r[symbol]["fresh"],symbol)
        self.assertAlmostEqual(r["XAU_SPOT"]["value"],4104.46)
        self.assertEqual(r["XAU_SPOT"]["instrument_type"],"SPOT")
        self.assertFalse(r["GC=F"]["fresh"])
        self.assertEqual(r["GC=F"]["instrument_type"],"FUTURES")
        self.assertFalse(r["CL=F"]["fresh"])
        self.assertAlmostEqual(r["DX-Y.NYB"]["pct"],-.02)

    def test_exchange_delayed_flag_stops_false_realtime_even_if_recent(self):
        r=parse_cnbc_quotes({"FormattedQuoteResult":{"FormattedQuote":[
            row("@GC.1","4120","+0.5%",minutes=1,realtime="false")]}},now=NOW)
        self.assertFalse(r["GC=F"]["fresh"])

    def test_old_dxy_cannot_count_as_live_even_with_true_flag(self):
        r=parse_cnbc_quotes({"FormattedQuoteResult":{"FormattedQuote":[
            row(".DXY","101.5","+0.01%",minutes=11)]}},now=NOW)
        self.assertFalse(r["DX-Y.NYB"]["fresh"])

    def test_future_timestamp_and_fake_symbol_not_accepted(self):
        r=parse_cnbc_quotes({"FormattedQuoteResult":{"FormattedQuote":[
            row(".DXY","101.5","+0.01%",minutes=-1),
            row("FAKE","100","+3%")]}},now=NOW)
        self.assertEqual(r,{})

    def test_spot_fallback_has_no_fabricated_daily_pct(self):
        result=parse_goldapi_spot({
            "price":4106.21,"updatedAt":(NOW-timedelta(seconds=30)).isoformat(),
        },symbol="XAU",now=NOW)
        self.assertTrue(result["fresh"])
        self.assertIsNone(result["pct"])
        self.assertEqual(result["instrument_type"],"SPOT")

    def test_spot_fallback_stale_and_negative_price_are_not_live(self):
        p={"price":52.2,"updatedAt":(NOW-timedelta(minutes=11)).isoformat()}
        self.assertFalse(parse_goldapi_spot(p,symbol="XAG",now=NOW)["fresh"])
        self.assertIsNone(parse_goldapi_spot({"price":-1,"updatedAt":NOW.isoformat()},
                                             symbol="XAG",now=NOW))
        self.assertIsNone(parse_goldapi_spot(p,symbol="GC=F",now=NOW))

    def test_parser_handles_cnbc_est_timestamps(self):
        # CNBC production uses e.g. 15:14:00.000-0500.
        item={"symbol":".DXY","last":"101.6","change_pct":"+0.01%",
              "last_time":"2026-11-05T15:14:00.000-0500","realTime":"true"}
        r=parse_cnbc_quotes({"FormattedQuoteResult":{"FormattedQuote":[item]}},now=NOW)
        self.assertTrue(r["DX-Y.NYB"]["fresh"])
        self.assertEqual(r["DX-Y.NYB"]["observed"],"2026-11-05T20:14:00+00:00")
if __name__=="__main__":
    unittest.main()

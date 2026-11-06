"""Regression tests: macro spot/geo feeds are informational and fail closed."""
from datetime import UTC, datetime, timedelta

from fx_scanner.xau_macro_spot_news_v2 import parse_dia_spot, _parse_rss
from fx_scanner.xau_oil_macro_context import assess_oil_macro, oil_quote_status
from fx_scanner.xau_geopolitical_safehaven import assess_geopolitical_safehaven


NOW = datetime(2026, 11, 6, 15, 0, tzinfo=UTC)


def _oil(symbol, *, at=NOW, prior=90):
    return parse_dia_spot({
        "Price": 91, "PriceYesterday": prior, "Time": at.isoformat(),
        "MarketOpen": True,
    }, symbol=symbol, now=NOW)


def test_dia_spot_pair_scores_only_on_fresh_comparable_quotes():
    wti = _oil("WTI")
    brent = _oil("Brent")
    result = assess_oil_macro({"WTI": wti, "Brent": brent}, NOW)
    assert wti["instrument_type"] == "SPOT"
    assert wti["pct"] > 1
    assert result["status"] == "INTRADAY"
    assert result["trend"] == "NAIK"
    assert oil_quote_status(wti, NOW)["status"] == "SPOT_FRESH_5M"


def test_stale_or_missing_baseline_never_becomes_intraday_oil_vote():
    old = _oil("WTI", at=NOW - timedelta(minutes=20))
    assert old["fresh"] is False
    fresh_no_base = parse_dia_spot(
        {"Price": 91, "Time": NOW.isoformat()}, symbol="Brent", now=NOW
    )
    assert fresh_no_base["pct"] is None
    assert oil_quote_status(fresh_no_base, NOW)["status"] == "SPOT_NO_BASELINE"
    result = assess_oil_macro({"WTI": old, "Brent": fresh_no_base}, NOW)
    assert result["status"] == "BELUM LENGKAP"
    assert result["score_influence"] is False


def test_rss_timestamp_and_corrob_market_required_for_geopolitical_vote():
    pubdate = "Fri, 06 Nov 2026 14:55:00 GMT"
    rss = (f"<rss><channel><item><title>Iran missile strike reported</title>"
           f"<link>https://www.bbc.com/news/example</link>"
           f"<pubDate>{pubdate}</pubDate></item></channel></rss>")
    articles = _parse_rss(rss.encode(), NOW)
    articles.append({
        "title": "Iran missile strike reported in capital",
        "url": "https://www.aljazeera.com/news/2026/11/6/example",
        "observed": NOW.isoformat(),
    })
    markets = {
        "^VIX": {"value": 25, "pct": 4.2, "fresh": True,
                 "observed": NOW.isoformat(), "source": "Yahoo Finance",
                 "basis": "penutupan sebelumnya"},
        "JPY=X": {"value": 148, "pct": -0.3, "fresh": True,
                  "observed": NOW.isoformat(), "source": "Yahoo Finance",
                  "basis": "penutupan sebelumnya"},
    }
    report = assess_geopolitical_safehaven(
        articles=articles, markets=markets, now=NOW
    )
    assert report["geo_weight"] == 0.05
    assert report["haven_weight"] == 0.05
    empty_market = assess_geopolitical_safehaven(
        articles=articles, markets={}, now=NOW
    )
    assert empty_market["geo_weight"] == 0
    assert empty_market["haven_weight"] == 0

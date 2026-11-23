"""Network-free regression: US10Y cash freshness and safe secondary proxy."""
from datetime import UTC, datetime, timedelta

from fx_scanner.xau_us10y_source_recovery import (
    CASH_MAX_AGE_SECONDS, PROXY_MAX_AGE_SECONDS, cash_quote_status,
    parse_yahoo_proxy,
)

NOW = datetime(2026, 11, 23, 1, 20, tzinfo=UTC)


def _chart(symbol, values, minutes=(10, 5)):
    times = [int((NOW - timedelta(minutes=m)).timestamp()) for m in minutes]
    return {"chart": {"error": None, "result": [{
        "meta": {"symbol": symbol, "regularMarketTime": int(NOW.timestamp())},
        "timestamp": times,
        "indicators": {"quote": [{"close": values}]},
    }]}}


def test_stale_cash_is_never_made_fresh_by_dashboard_cache_refresh():
    at = NOW - timedelta(seconds=CASH_MAX_AGE_SECONDS + 20)
    quote = {"current": 4.95, "current_at": at.isoformat(), "realtime": True,
             "fresh": True, "age_seconds": 1}  # stale cached fields
    status = cash_quote_status(quote, now=NOW)
    assert not status["fresh"]
    assert status["age_seconds"] == CASH_MAX_AGE_SECONDS + 20


def test_cnbc_non_realtime_flag_blocks_false_live_status():
    quote = {"current": 4.95, "current_at": (NOW - timedelta(seconds=10)).isoformat(),
             "realtime": False}
    assert cash_quote_status(quote, now=NOW)["reason"] == "vendor did not confirm realtime"


def test_future_vendor_timestamp_is_not_accepted_as_live():
    quote = {"current": 4.95, "current_at": (NOW + timedelta(minutes=5)).isoformat(),
             "realtime": True}
    assert not cash_quote_status(quote, now=NOW)["fresh"]


def test_verified_cash_quote_is_eligible():
    quote = {"current": 4.95, "current_at": (NOW - timedelta(seconds=30)).isoformat(),
             "realtime": "true"}
    assert cash_quote_status(quote, now=NOW)["fresh"]


def test_tnx_intraday_secondary_is_not_cash_live():
    proxy = parse_yahoo_proxy(_chart("^TNX", [4.90, 4.95]), symbol="^TNX", now=NOW)
    assert proxy["eligible"]
    assert proxy["direction"] == "YIELD NAIK"
    assert proxy["unit"] == "%"
    assert not proxy["is_cash_yield"]


def test_zn_futures_inverse_yield_direction_and_unit():
    proxy = parse_yahoo_proxy(_chart("ZN=F", [110.00, 110.25]), symbol="ZN=F", now=NOW)
    assert proxy["eligible"]
    assert proxy["direction"] == "YIELD CENDERUNG TURUN"
    assert proxy["unit"] == "poin futures"
    assert not proxy["is_cash_yield"]


def test_stale_proxy_is_never_reused_as_current_context():
    proxy = parse_yahoo_proxy(
        _chart("ZN=F", [110.0, 111.0], minutes=(120, 60)),
        symbol="ZN=F", now=NOW)
    assert proxy["age_seconds"] > PROXY_MAX_AGE_SECONDS
    assert not proxy["eligible"]
    assert proxy["delta"] is None
    assert "STALE" in proxy["direction"]


def test_missing_chart_and_invalid_symbol_fail_closed():
    assert parse_yahoo_proxy({"chart": {"result": []}}, symbol="^TNX", now=NOW) is None
    try:
        parse_yahoo_proxy(_chart("^TNX", [4.9, 5.0]), symbol="INVALID", now=NOW)
    except ValueError:
        pass
    else:
        assert False, "unsupported market proxy accepted"


def test_no_fabricated_direction_from_single_candle():
    proxy = parse_yahoo_proxy(
        _chart("ZN=F", [110.0], minutes=(5,)), symbol="ZN=F", now=NOW)
    assert proxy["eligible"]
    assert proxy["direction"] == "BELUM ADA DUA BAR"

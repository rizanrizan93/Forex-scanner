"""Regression: lagging GitHub raw CDN may never mask a fresh broker snapshot."""
from datetime import UTC, datetime, timedelta
from unittest.mock import patch
import pytest

from fx_scanner import xau_m15_market_feed as feed

NOW = datetime(2026, 11, 9, 2, 49, 59, tzinfo=UTC)


def good():
    return {
        "contract": "RIZAN_XAU_M15_BROKER_READONLY_V1",
        "symbol": "XAUUSD", "source": "CTRADER_MARKET_DATA_READ_ONLY",
        "account_suffix": "7903", "as_of": (NOW-timedelta(seconds=10)).isoformat(),
        "price_observed_at": (NOW-timedelta(seconds=59)).isoformat(),
        "price": 4126.11,
        "latest_closed_m15": {"close": 4129.65,
                              "closed_at": NOW.replace(minute=45, second=0, microsecond=0).isoformat()},
        "timeframe_fresh": {"M15": True},
        "execution_authority": False,
        "execution_influence": False,
    }


def test_valid_raw_requires_no_api_fallback():
    with patch.object(feed, "read_json", return_value=good()) as read:
        assert feed.fetch_fast_m15(now=NOW)["price"] == 4126.11
    assert read.call_count == 1


def test_old_raw_uses_verified_api_copy_for_same_candle():
    stale = good()
    stale["as_of"] = (NOW-timedelta(minutes=8)).isoformat()
    with patch.object(feed, "read_json", side_effect=[stale, good()]) as read:
        result = feed.fetch_fast_m15(now=NOW)
    assert result["price_observed_at"] == good()["price_observed_at"]
    assert read.call_count == 2
    assert read.call_args_list[1].kwargs["api"] is True


def test_stale_both_endpoints_still_fail_closed():
    stale = good()
    stale["price_observed_at"] = (NOW-timedelta(minutes=6)).isoformat()
    with patch.object(feed, "read_json", side_effect=[stale, stale]):
        with pytest.raises(ValueError, match="UNAVAILABLE_OR_STALE"):
            feed.fetch_fast_m15(now=NOW)


def test_legacy_reversal_contract_never_substitutes_for_broker_feed():
    stale = good()
    stale["contract"] = "RIZAN_XAU_MANUAL_REVERSAL_MAP_V2"
    with patch.object(feed, "read_json", side_effect=[stale, stale]):
        with pytest.raises(ValueError, match="UNAVAILABLE_OR_STALE"):
            feed.fetch_fast_m15(now=NOW)

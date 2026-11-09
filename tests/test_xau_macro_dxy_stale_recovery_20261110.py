"""Regression: 41% Macro coverage when CNBC DXY exists but is not live.

Only independently fresh vendor timestamps can restore a directional vote.
No synthetic price, no stale feed re-labeling, no trading authority.
"""
from datetime import UTC, datetime, timedelta

from fx_scanner.xau_macro_risk_monitor import (
    _stale_dxy_needs_fallback, _select_vendor_quote,
)
from fx_scanner.xau_macro_gold_consensus import analyze_gold_macro

NOW = datetime(2026, 11, 10, 0, 0, tzinfo=UTC)


def dxy(*, age_minutes=2, fresh=True, source="Yahoo Finance"):
    return {
        "value": 101.7,
        "pct": -0.18,
        "observed": (NOW - timedelta(minutes=age_minutes)).isoformat(),
        "fresh": fresh,
        "source": source,
        "basis": "penutupan sebelumnya",
    }


def yields():
    # Daily Treasury is valid for regime but not necessarily for CPI spike.
    at = (NOW - timedelta(days=1)).isoformat()
    return {
        name: {
            "delta": -2.0,
            "current": 4.0,
            "observed_at": at,
            "freshness": "FRESH",
            "provider": "FRED_OFFICIAL_DAILY",
        }
        for name in ("REAL_YIELD_10Y", "US2Y", "US10Y")
    }


def test_41_percent_coverage_is_dxy_missing_not_entire_feed_down():
    old = dxy(age_minutes=19, fresh=False, source="CNBC Quote Cache")
    assert _stale_dxy_needs_fallback({"DX-Y.NYB": old}, now=NOW)
    before = analyze_gold_macro(yields=yields(), dxy=old, now=NOW)
    assert before["coverage_pct"] == 41
    assert before["state"] == "WAIT_DATA"
    assert before["score"] is None
    assert "DXY" in " ".join(before["missing"])


def test_fresh_yahoo_dxy_restores_only_validated_macro_direction():
    old = dxy(age_minutes=19, fresh=False, source="CNBC Quote Cache")
    chosen, recovered = _select_vendor_quote(old, dxy(), now=NOW)
    assert recovered is True
    assert chosen["source"] == "Yahoo Finance"
    assert _stale_dxy_needs_fallback({"DX-Y.NYB": chosen}, now=NOW) is False
    after = analyze_gold_macro(yields=yields(), dxy=chosen, now=NOW)
    assert after["coverage_pct"] == 75
    assert after["state"] != "WAIT_DATA"
    assert after["execution_authority"] is False
    assert after["execution_influence"] is False


def test_delayed_yahoo_and_bad_vendor_flags_cannot_bypass_freshness():
    old = dxy(age_minutes=19, fresh=False, source="CNBC Quote Cache")
    for invalid in (
        dxy(age_minutes=20, fresh=True),
        dxy(age_minutes=1, fresh=False),
        dxy(age_minutes=-2, fresh=True),
    ):
        chosen, recovered = _select_vendor_quote(old, invalid, now=NOW)
        assert not recovered
        assert chosen == old
    after = analyze_gold_macro(yields=yields(), dxy=chosen, now=NOW)
    assert after["state"] == "WAIT_DATA"


def test_missing_vendor_quote_is_never_claimed_live():
    q, recovered = _select_vendor_quote(None, dxy(age_minutes=12), now=NOW)
    assert recovered is False
    assert q is not None
    empty, recovered = _select_vendor_quote(None, None, now=NOW)
    assert empty is None and recovered is False

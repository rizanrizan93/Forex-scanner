from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from fx_scanner.usd_lead_bund_2y_v1 import (
    BUND_SERIES, fetch_bundesbank_2y,
    pair_with_treasury_2y, parse_bundesbank_daily_csv,
)


NOW = datetime(2026, 11, 16, 3, 0, tzinfo=UTC)


def treasury():
    return {
        "provider": "US_TREASURY_DAILY_XML",
        "freshness": "FRESH", "release_state": "CURRENT_PUBLISHED",
        "current": 4.9, "previous": 4.86, "delta": 4,
        "observed_at": "2026-11-13T00:00:00+00:00",
        "previous_observed_at": "2026-11-12T00:00:00+00:00",
    }


def bund():
    return {
        "series": BUND_SERIES,
        "source": "DEUTSCHE_BUNDESBANK_DAILY_CSV",
        "daily": {"2026-11-12": 1.99, "2026-11-13": 2.0},
        "execution_authority": False, "execution_influence": False,
    }


def test_parse_sdmx_csv_header_with_metadata():
    data = (b"# Bundesbank release\n"
            b"KEY,TIME_PERIOD,OBS_VALUE,OBS_STATUS\n"
            b"BBSSY,2026-11-12,1.99,A\n"
            b"BBSSY,2026-11-13,2.00,A\n")
    x = parse_bundesbank_daily_csv(data)
    assert x["2026-11-13"] == 2.0
    assert x["2026-11-12"] == 1.99


def test_parse_semicolon_decimal_comma():
    data = (
        b"TIME_PERIOD;OBS_VALUE\n"
        b"2026-11-12;\"1,99\"\n"
        b"2026-11-13;\"2,02\"\n"
    )
    x = parse_bundesbank_daily_csv(data)
    assert x == {"2026-11-12": 1.99, "2026-11-13": 2.02}


def test_malformed_or_html_provider_fails_closed():
    with pytest.raises(ValueError):
        parse_bundesbank_daily_csv(b"<html>Forbidden</html>")
    with pytest.raises(ValueError):
        parse_bundesbank_daily_csv(b"TIME_PERIOD,VALUE\n2026-11-13,2.0")


def test_matching_trading_dates_can_be_compared():
    x = pair_with_treasury_2y(bund(), treasury(), now=NOW)
    assert x and x["us2y_current"] == 4.9
    assert x["de2y_current"] == 2.0
    assert x["execution_authority"] is False


def test_mismatched_days_not_synthetically_filled():
    bad = bund()
    bad["daily"].pop("2026-11-12")
    assert pair_with_treasury_2y(bad, treasury(), now=NOW) is None


def test_cannot_use_unpublished_treasury():
    t = treasury()
    t["release_state"] = "RELEASE_PENDING"
    assert pair_with_treasury_2y(bund(), t, now=NOW) is None


def test_old_daily_yield_is_not_treated_as_live():
    assert pair_with_treasury_2y(
        bund(), treasury(), now=NOW + timedelta(days=10)) is None


def test_bundesbank_fetch_uses_original_dates_not_retrieval_time():
    class FakeResponse:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def read(self, n):
            return (b"TIME_PERIOD,OBS_VALUE\n"
                    b"2026-11-12,1.99\n"
                    b"2026-11-13,2.00\n")
    calls = []
    def fake_open(req, *, timeout):
        calls.append((req.full_url, timeout))
        return FakeResponse()
    out = fetch_bundesbank_2y(now=NOW, opener=fake_open)
    assert out["daily"]["2026-11-13"] == 2.0
    assert "startPeriod=" in calls[0][0]
    assert out["retrieved_at"] == NOW.isoformat()

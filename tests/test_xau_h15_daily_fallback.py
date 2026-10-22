from datetime import UTC, datetime

import pytest

from fx_scanner.xau_h15_daily_fallback import (
    fetch_h15_daily_rows,
    parse_h15_daily_rows,
)
from fx_scanner.xau_yield_regime_view_v372 import classify_daily_us10y

SAMPLE = b"""Federal Reserve Board of Governors, H.15 Selected Interest Rates
Unique Identifier,H15/H15/RIFLGFCY02_N.B,H15/H15/RIFLGFCY10_N.B,H15/H15/RIFLGFCY10_XII_N.B
Time Period,RIFLGFCY02_N.B,RIFLGFCY10_N.B,RIFLGFCY10_XII_N.B
2026-10-16,4.74,5.09,2.74
2026-10-19,4.77,5.15,2.80
2026-10-20,4.79,5.12,2.77
2026-10-21,ND,ND,ND
"""
NOW = datetime(2026, 10, 22, 1, tzinfo=UTC)


def test_h15_recovers_yield_bps_from_last_two_valid_business_days():
    out = parse_h15_daily_rows(SAMPLE, now=NOW)
    assert out["US10Y"]["current"] == 5.12
    assert out["US10Y"]["previous"] == 5.15
    assert out["US10Y"]["delta"] == pytest.approx(-3)
    assert out["US2Y"]["delta"] == pytest.approx(2)
    assert out["REAL_YIELD_10Y"]["delta"] == pytest.approx(-3)
    assert out["US10Y"]["provider"] == "FEDERAL_RESERVE_H15"
    assert out["US10Y"]["execution_authority"] is False
    assert classify_daily_us10y({"components": {"US10Y": out["US10Y"]}})["gold_bias"] == "BULLISH_XAU"


def test_h15_stale_does_not_produce_directional_daily_bias():
    out = parse_h15_daily_rows(SAMPLE, now=datetime(2026, 11, 2, tzinfo=UTC))
    assert out["US10Y"]["freshness"] == "STALE"
    assert classify_daily_us10y({"components": {"US10Y": out["US10Y"]}})["gold_bias"] == "UNAVAILABLE"


def test_h15_rejects_maintenance_page_and_unsupported_columns():
    with pytest.raises(ValueError):
        parse_h15_daily_rows(b"<html>site maintenance</html>", now=NOW)
    with pytest.raises(ValueError):
        parse_h15_daily_rows(b"Time Period,OTHER\n2026-10-20,5.12\n", now=NOW)


def test_h15_does_not_invent_missing_previous_observation():
    raw = b"Time Period,RIFLGFCY10_N.B\n2026-10-20,5.12\n"
    assert "US10Y" not in parse_h15_daily_rows(raw, now=NOW)


def test_h15_rejects_future_observations():
    raw = (
        b"Time Period,RIFLGFCY10_N.B\n"
        b"2026-10-19,5.15\n2026-10-20,5.12\n2026-10-30,9.99\n"
    )
    assert parse_h15_daily_rows(raw, now=NOW)["US10Y"]["current"] == 5.12


class FakeTransport:
    def get(self, url, *, allowed_host, headers):
        assert allowed_host == "www.federalreserve.gov"
        assert "filetype=csv" in url

        class Response:
            status_code = 200
            body = SAMPLE

        return Response()


def test_h15_download_uses_fixed_official_host():
    result = fetch_h15_daily_rows(transport=FakeTransport(), now=NOW)
    assert result["US10Y"]["delta"] == -3

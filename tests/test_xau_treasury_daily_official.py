from datetime import UTC, datetime

import pytest

from fx_scanner.xau_treasury_daily_official import (
    fetch_treasury_daily_rows, parse_treasury_xml, treasury_xml_url,
)
from fx_scanner.xau_official_yield_selection import select_official_yield_rows

NOW = datetime(2026, 11, 13, 0, 15, tzinfo=UTC)


def xml(rows, fields):
    parts = [
        '<?xml version="1.0" encoding="utf-8"?>',
        '<feed xmlns="http://www.w3.org/2005/Atom" '
        'xmlns:d="http://schemas.microsoft.com/ado/2007/08/dataservices" '
        'xmlns:m="http://schemas.microsoft.com/ado/2007/08/dataservices/metadata">'
    ]
    for day, values in rows:
        parts += ['<entry><content><m:properties>',
                  f'<d:NEW_DATE>{day}T00:00:00</d:NEW_DATE>']
        parts += [f'<d:{field}>{values.get(field, "")}</d:{field}>' for field in fields]
        parts += ['</m:properties></content></entry>']
    parts.append('</feed>')
    return ''.join(parts).encode()


NOMINAL = xml([
    ("2026-11-09", {"BC_2YEAR": "4.56", "BC_10YEAR": "4.88"}),
    ("2026-11-10", {"BC_2YEAR": "4.73", "BC_10YEAR": "4.98"}),
    ("2026-11-11", {"BC_2YEAR": "", "BC_10YEAR": ""}),
    ("2026-11-12", {"BC_2YEAR": "4.86", "BC_10YEAR": "5.10"}),
    ("2026-11-13", {"BC_2YEAR": "99", "BC_10YEAR": "99"}),
], ["BC_2YEAR", "BC_10YEAR"])
REAL = xml([
    ("2026-11-09", {"TC_10YEAR": "2.66"}),
    ("2026-11-10", {"TC_10YEAR": "2.78"}),
    ("2026-11-12", {"TC_10YEAR": "2.86"}),
], ["TC_10YEAR"])


class Transport:
    def __init__(self, nominal=NOMINAL, real=REAL):
        self.nominal, self.real = nominal, real
        self.urls = []

    def get(self, url, *, allowed_host, headers):
        self.urls.append(url)
        assert allowed_host == "home.treasury.gov"
        assert "field_tdr_date_value_month=202611" in url
        assert headers["Accept"].startswith("application/atom+xml")

        class Response:
            status_code = 200

        res = Response()
        res.body = (self.real if "data=daily_treasury_real_yield_curve" in url
                    else self.nominal)
        return res


def test_direct_treasury_fetch_three_daily_rates_and_valid_bps():
    transport = Transport()
    out = fetch_treasury_daily_rows(transport=transport, now=NOW)
    assert len(transport.urls) == 2
    assert {k: v["provider"] for k, v in out.items()} == {
        "US2Y": "US_TREASURY_DAILY_XML",
        "US10Y": "US_TREASURY_DAILY_XML",
        "REAL_YIELD_10Y": "US_TREASURY_DAILY_XML",
    }
    assert out["US2Y"]["current"] == 4.86
    assert out["US2Y"]["previous"] == 4.73
    assert out["US2Y"]["delta"] == pytest.approx(13)
    assert out["US10Y"]["delta"] == pytest.approx(12)
    assert out["REAL_YIELD_10Y"]["delta"] == pytest.approx(8)
    assert out["US10Y"]["observed_at"].startswith("2026-11-12")
    assert out["US10Y"]["previous_observed_at"].startswith("2026-11-10")
    assert out["US10Y"]["execution_authority"] is False


def test_treasury_only_overrides_valid_older_fred_daily():
    official = fetch_treasury_daily_rows(transport=Transport(), now=NOW)
    fred = {
        name: {
            **row, "provider": "FEDERAL_RESERVE_FRED",
            "observed_at": "2026-11-10T00:00:00+00:00",
            "previous_observed_at": "2026-11-09T00:00:00+00:00",
            "previous": 4.56 if name == "US2Y" else 4.88 if name == "US10Y" else 2.66,
            "current": 4.73 if name == "US2Y" else 4.98 if name == "US10Y" else 2.78,
            "delta": 17 if name == "US2Y" else 10 if name == "US10Y" else 12,
        }
        for name, row in official.items()
    }
    selected, diagnostics = select_official_yield_rows(
        fred, {}, now=NOW, treasury_rows=official
    )
    assert all(row["provider"] == "US_TREASURY_DAILY_XML" for row in selected.values())
    assert diagnostics["treasury_primary_used"] == [
        "US2Y", "US10Y", "REAL_YIELD_10Y"
    ]
    assert all(state == "CURRENT_PUBLISHED"
               for state in diagnostics["release_states"].values())


def test_invalid_treasury_delta_does_not_override_fred():
    official = fetch_treasury_daily_rows(transport=Transport(), now=NOW)
    forged = dict(official["US10Y"], delta=999)
    chosen, diagnostics = select_official_yield_rows(
        {"US10Y": {
            **official["US10Y"], "provider": "FEDERAL_RESERVE_FRED",
            "delta": 12,
        }}, {}, now=NOW, treasury_rows={"US10Y": forged},
    )
    assert chosen["US10Y"]["provider"] == "FEDERAL_RESERVE_FRED"
    assert not diagnostics["treasury_primary_used"]


def test_real_negative_yield_is_valid_not_synthetic():
    parsed = parse_treasury_xml(
        xml([("2026-11-10", {"TC_10YEAR": "-0.42"})], ["TC_10YEAR"]),
        dataset="daily_treasury_real_yield_curve", now=NOW,
    )
    assert list(parsed["REAL_YIELD_10Y"].values()) == [-0.42]


def test_future_observation_and_empty_rows_not_imputed():
    out = parse_treasury_xml(
        NOMINAL, dataset="daily_treasury_yield_curve", now=NOW,
    )
    assert len(out["US2Y"]) == 3
    assert not any(d.day in {11, 13} for d in out["US2Y"])


def test_html_error_page_rejected():
    with pytest.raises(ValueError):
        parse_treasury_xml(b"<html>maintenance</html>",
                           dataset="daily_treasury_yield_curve", now=NOW)


def test_url_allowlist_and_invalid_month():
    assert treasury_xml_url("daily_treasury_real_yield_curve", "202611").startswith(
        "https://home.treasury.gov/"
    )
    with pytest.raises(ValueError):
        treasury_xml_url("daily_treasury_yield_curve", "202613")
    with pytest.raises(ValueError):
        treasury_xml_url("daily_treasury_bill_rates", "202611")


def test_real_feed_network_failure_keeps_nominal_rows():
    from fx_scanner.providers.transport import HttpTransportError

    class PartialTransport(Transport):
        def get(self, url, *, allowed_host, headers):
            if "data=daily_treasury_real_yield_curve" in url:
                raise HttpTransportError("HTTP_503")
            return super().get(url, allowed_host=allowed_host, headers=headers)

    output = fetch_treasury_daily_rows(transport=PartialTransport(), now=NOW)
    assert sorted(output) == ["US10Y", "US2Y"]
    assert output["US10Y"]["observed_at"].startswith("2026-11-12")

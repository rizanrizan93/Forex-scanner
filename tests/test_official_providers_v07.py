from datetime import datetime, timezone

import pytest

from fx_scanner.providers.official import (
    BankOfCanadaValetProvider,
    BankOfEnglandIadbProvider,
    EcbDataPortalProvider,
    FredCsvProvider,
    RbaCashRateProvider,
)
from fx_scanner.providers.semantics import ProviderStatus
from fx_scanner.providers.transport import HttpResponse, HttpTransportError, UrllibHttpTransport

UTC = timezone.utc
NOW = datetime(2026, 8, 30, 10, tzinfo=UTC)


class FakeTransport:
    def __init__(self, body: bytes, *, status=200):
        self.body = body
        self.status = status
        self.calls = []

    def get(self, url, *, allowed_host, headers=None):
        self.calls.append((url, allowed_host, dict(headers or {})))
        return HttpResponse(self.status, self.body, {}, url)


def test_ecb_csv_provider_reads_last_two_observations_and_month_periods():
    body = (
        b"KEY,TIME_PERIOD,OBS_VALUE\n"
        b"A,2026-07,1.15\n"
        b"A,2026-08,1.20\n"
    )
    transport = FakeTransport(body)
    provider = EcbDataPortalProvider(
        transport,
        clock=lambda: datetime(2026, 8, 31, 0, tzinfo=UTC),
    )
    result = provider.fetch_numeric("TEST/M.SERIES", max_age_seconds=86400)
    assert result.status == ProviderStatus.AVAILABLE
    assert result.value.value == pytest.approx(1.20)
    assert result.value.previous_value == pytest.approx(1.15)
    assert result.value.observed_at == datetime(2026, 8, 31, tzinfo=UTC)
    assert "lastNObservations=2" in transport.calls[0][0]


def test_ecb_quarter_period_is_parsed_to_quarter_end():
    body = b"TIME_PERIOD,OBS_VALUE\n2026-Q1,2.0\n2026-Q2,2.5\n"
    provider = EcbDataPortalProvider(
        FakeTransport(body),
        clock=lambda: datetime(2026, 7, 1, tzinfo=UTC),
    )
    result = provider.fetch_numeric("TEST/Q.SERIES", max_age_seconds=86400)
    assert result.value.observed_at == datetime(2026, 6, 30, tzinfo=UTC)


def test_boc_valet_provider_reads_policy_series():
    body = b'''{
      "observations": [
        {"d": "2026-07-14", "V39079": {"v": "2.25"}},
        {"d": "2026-07-15", "V39079": {"v": "2.25"}}
      ]
    }'''
    provider = BankOfCanadaValetProvider(
        FakeTransport(body),
        clock=lambda: datetime(2026, 7, 16, tzinfo=UTC),
    )
    result = provider.fetch_numeric("V39079", max_age_seconds=172800)
    assert result.status == ProviderStatus.AVAILABLE
    assert result.value.value == pytest.approx(2.25)
    assert result.value.previous_value == pytest.approx(2.25)


def test_provider_returns_missing_not_zero_when_response_has_no_observation():
    provider = BankOfCanadaValetProvider(
        FakeTransport(b'{"observations": []}'),
        clock=lambda: NOW,
    )
    result = provider.fetch_numeric("V39079")
    assert result.status == ProviderStatus.MISSING
    assert result.value is None


def test_http_transport_blocks_non_https_and_wrong_host_before_network():
    transport = UrllibHttpTransport()
    with pytest.raises(HttpTransportError, match="HTTPS"):
        transport.get("http://example.com/x", allowed_host="example.com")
    with pytest.raises(HttpTransportError, match="host mismatch"):
        transport.get("https://evil.example/x", allowed_host="example.com")


def test_official_numeric_providers_reject_multi_series_requests():
    ecb = EcbDataPortalProvider(FakeTransport(b""))
    result = ecb.fetch_numeric("EXR/D.USD+JPY.EUR.SP00.A")
    assert result.status == ProviderStatus.INVALID
    assert result.value is None

    boc = BankOfCanadaValetProvider(FakeTransport(b""))
    result = boc.fetch_numeric("V39079,V39078")
    assert result.status == ProviderStatus.INVALID
    assert result.value is None


def test_fred_csv_provider_reads_exact_series_history():
    body = (
        b"observation_date,IORB\n"
        b"2026-08-27,3.65\n"
        b"2026-08-28,3.65\n"
    )
    transport = FakeTransport(body)
    provider = FredCsvProvider(
        transport,
        clock=lambda: datetime(2026, 8, 30, 0, tzinfo=UTC),
    )
    result = provider.fetch_numeric("IORB", max_age_seconds=259200)
    assert result.status == ProviderStatus.AVAILABLE
    assert result.value.value == pytest.approx(3.65)
    assert result.value.previous_value == pytest.approx(3.65)
    assert result.value.observed_at == datetime(2026, 8, 28, tzinfo=UTC)
    assert "id=IORB" in transport.calls[0][0]


def test_fred_provider_rejects_non_exact_series():
    provider = FredCsvProvider(FakeTransport(b""))
    result = provider.fetch_numeric("IORB,OTHER")
    assert result.status == ProviderStatus.INVALID
    assert result.value is None


def test_rba_cash_rate_provider_parses_official_decision_table():
    body = b"""
    <html><body><table>
      <tr><th>Effective Date</th><th>Change</th><th>Cash rate target %</th></tr>
      <tr><td>12 Aug 2026</td><td>0.00</td><td>4.35</td></tr>
      <tr><td>17 Jun 2026</td><td>0.00</td><td>4.35</td></tr>
      <tr><td>6 May 2026</td><td>+0.25</td><td>4.35</td></tr>
    </table></body></html>
    """
    provider = RbaCashRateProvider(
        FakeTransport(body),
        clock=lambda: datetime(2026, 8, 30, tzinfo=UTC),
    )
    result = provider.fetch_numeric("CASH_RATE_TARGET", max_age_seconds=3888000)
    assert result.status == ProviderStatus.AVAILABLE
    assert result.value.value == pytest.approx(4.35)
    assert result.value.previous_value == pytest.approx(4.35)
    assert result.value.observed_at == datetime(2026, 8, 12, tzinfo=UTC)


def test_rba_cash_rate_provider_fails_closed_if_table_contract_disappears():
    provider = RbaCashRateProvider(
        FakeTransport(b"<html><body>No decision table</body></html>"),
        clock=lambda: NOW,
    )
    result = provider.fetch_numeric("CASH_RATE_TARGET")
    assert result.status == ProviderStatus.MISSING
    assert result.value is None


def test_rba_cash_rate_provider_rejects_unknown_series():
    provider = RbaCashRateProvider(FakeTransport(b""))
    result = provider.fetch_numeric("OTHER")
    assert result.status == ProviderStatus.INVALID



def test_boe_iadb_provider_reads_daily_official_bank_rate():
    body = (
        b"DATE,IUDBEDR\n"
        b"27 Aug 2026,3.75\n"
        b"28 Aug 2026,3.75\n"
    )
    transport = FakeTransport(body)
    provider = BankOfEnglandIadbProvider(
        transport,
        clock=lambda: datetime(2026, 9, 2, 0, tzinfo=UTC),
    )
    result = provider.fetch_numeric("IUDBEDR", max_age_seconds=2592000)

    assert result.status == ProviderStatus.AVAILABLE
    assert result.value.value == pytest.approx(3.75)
    assert result.value.previous_value == pytest.approx(3.75)
    assert result.value.observed_at == datetime(2026, 8, 28, tzinfo=UTC)
    url = transport.calls[0][0]
    assert "SeriesCodes=IUDBEDR" in url
    assert "CSVF=TN" in url
    assert transport.calls[0][1] == "www.bankofengland.co.uk"


def test_boe_iadb_provider_rejects_html_error_as_provider_error():
    provider = BankOfEnglandIadbProvider(
        FakeTransport(b"<html><body>error</body></html>"),
        clock=lambda: datetime(2026, 9, 2, 0, tzinfo=UTC),
    )
    result = provider.fetch_numeric("IUDBEDR")
    assert result.status == ProviderStatus.ERROR
    assert result.value is None

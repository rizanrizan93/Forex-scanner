from datetime import datetime, timezone

import pytest

from fx_scanner.providers.official import BankOfCanadaValetProvider, EcbDataPortalProvider
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

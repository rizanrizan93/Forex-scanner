"""Local, deterministic tests for new read-only Pre-News forecast vendors."""
from datetime import UTC, datetime, timedelta
import json
from types import SimpleNamespace

import pytest

from fx_scanner.exceptions import DataContractError
from fx_scanner.pre_news_additional_providers import (
    ShowMyTradesCalendarProvider, HeliousCalendarProvider,
    TradingEconomicsCalendarProvider,
)

NOW = datetime(2026, 11, 8, 14, 50, tzinfo=UTC)


class FakeTransport:
    def __init__(self, payload, status=200):
        self.payload, self.status, self.urls = payload, status, []

    def get(self, url, **kwargs):
        self.urls.append((url, kwargs))
        return SimpleNamespace(status_code=self.status, body=json.dumps(self.payload).encode())


def test_showmytrades_parses_realistic_json_and_skips_tentative():
    body = {
        "generated_at": (NOW - timedelta(minutes=20)).isoformat(),
        "events": [
            {"currency": "USD", "time": "2026-11-10T13:30:00Z", "title": "CPI (YoY)",
             "status": "scheduled", "confidence": "sources_agree", "impact": "high",
             "forecast": "3.2%", "previous": "3.1%", "actual": ""},
            {"currency": "USD", "time": "2026-11-10T13:30:00Z", "title": "Core CPI (MoM)",
             "status": "tentative", "impact": "high", "forecast": "0.3%"},
        ],
    }
    transport = FakeTransport(body)
    snapshot = ShowMyTradesCalendarProvider(transport).fetch(now=NOW)
    assert len(snapshot.events) == 1
    e = snapshot.events[0]
    assert e.source == "SHOWMYTRADES"
    assert e.forecast == 3.2 and e.previous == 3.1
    assert "days=7" in transport.urls[0][0]


def test_showmytrades_rejects_stale_generation_and_disagreement():
    body = {"generated_at": (NOW-timedelta(hours=2)).isoformat(), "events": [
        {"currency": "USD", "time": "2026-11-10T13:30:00Z",
         "title": "CPI (MoM)", "forecast": "0.3%"},
    ]}
    with pytest.raises(DataContractError, match="stale"):
        ShowMyTradesCalendarProvider(FakeTransport(body)).fetch(now=NOW)

    body["generated_at"] = NOW.isoformat()
    body["events"][0]["confidence"] = "sources_disagree"
    with pytest.raises(DataContractError, match="no usable"):
        ShowMyTradesCalendarProvider(FakeTransport(body)).fetch(now=NOW)


def test_helious_nested_data_keeps_only_us_economic_releases():
    body = {"summary": "test", "data": {"events": [
        {"datetime_utc": "2026-11-10T13:30:00+00:00", "title": "CPI (YoY)",
         "country": "US", "type": "economic", "impact": "High",
         "forecast": "3.2%", "previous": "3.1%", "actual": None,
         "status": "scheduled"},
        {"datetime_utc": "2026-11-10T13:30:00+00:00", "title": "Company Earnings",
         "country": "US", "type": "earnings", "forecast": "5.2"},
        {"datetime_utc": "2026-11-10T13:30:00+00:00", "title": "EU Inflation",
         "country": "EU", "type": "economic", "forecast": "2.0%"},
    ]}}
    snapshot = HeliousCalendarProvider(FakeTransport(body)).fetch(now=NOW)
    assert len(snapshot.events) == 1
    assert snapshot.events[0].forecast == 3.2
    assert snapshot.events[0].source == "HELIOUS"


def test_trading_economics_auth_is_mandatory_and_parses_subscription_data():
    with pytest.raises(ValueError, match="subscription"):
        TradingEconomicsCalendarProvider(FakeTransport([]), api_key="")
    transport = FakeTransport([
        {"Country": "United States", "Date": "2026-11-10T13:30:00",
         "Event": "CPI (YoY)", "Forecast": "3.2%", "Previous": "3.1%",
         "Importance": 3},
    ])
    # Trading Economics API may emit naive Date timestamps; these must be
    # rejected rather than silently assuming a timezone.
    with pytest.raises(DataContractError, match="no usable"):
        TradingEconomicsCalendarProvider(transport, api_key="test-key").fetch(now=NOW)
    transport.payload[0]["Date"] = "2026-11-10T13:30:00+00:00"
    snap = TradingEconomicsCalendarProvider(transport, api_key="test-key").fetch(now=NOW)
    assert snap.events[0].forecast == 3.2
    assert "test-key" in transport.urls[-1][0]
    assert transport.urls[-1][1]["allowed_host"] == "api.tradingeconomics.com"

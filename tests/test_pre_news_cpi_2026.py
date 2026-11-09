"""CPI October 2026 BLS release exception and independent provider checks."""
from copy import deepcopy
from datetime import UTC, datetime

from fx_scanner.pre_news_expectation import evaluate_pre_news
from fx_scanner.demo_xau_event_risk_v193 import (
    _RetryingSecondaryTransport, _provider_failure,
)
from fx_scanner.providers.transport import HttpTransportError
from test_pre_news_expectation import snapshot

RELEASE_AT = datetime(2026, 11, 10, 13, 30, tzinfo=UTC)
NOW = datetime(2026, 11, 9, 14, 35, tzinfo=UTC)


def _event(component, forecast, previous, sources):
    return {
        "title": component.replace("_", " "),
        "event_component": component,
        "category": "CPI",
        "scheduled_at": RELEASE_AT.isoformat(),
        "forecast": forecast,
        "previous": previous,
        "source_agreement": "MULTI_SOURCE_AGREE",
        "forecast_quotes": [
            {"source": source, "forecast": forecast, "previous": previous}
            for source in sources
        ],
    }


def test_october_2026_unpublished_cpi_yoy_is_excluded_from_mixed_votes():
    data = snapshot(-1)
    risk = data["heartbeats"][0]["details"]["risk"]
    data["heartbeats"][0]["observed_at"] = NOW.isoformat()
    risk["focal_event"] = None
    vendors = ["FOREX_FACTORY_WEEKLY", "SHOWMYTRADES"]
    risk["upcoming_events"] = [
        _event("CPI_MOM", 0.3, 0.6, vendors),
        _event("CORE_CPI_MOM", 0.2, 0.3, vendors),
        _event("CPI_YOY", 3.9, 3.7, ["SHOWMYTRADES"]),
        _event("CORE_CPI_YOY", 2.8, 2.6, ["SHOWMYTRADES"]),
    ]
    result = evaluate_pre_news(data, now=NOW)
    assert set(result["unpublished_components"]) == {"CPI_YOY", "CORE_CPI_YOY"}
    assert {row["event_component"] for row in result["event_cluster"]} == {
        "CPI_MOM", "CORE_CPI_MOM"
    }
    assert result["news_conclusion"].startswith("COOL RISK")
    assert result["forecast_quorum_met"] is False
    assert result["execution_authority"] is False
    assert result["execution_influence"] is False


def test_oct_2026_only_and_three_source_quorum_remains_strict():
    data = snapshot(-1)
    risk = data["heartbeats"][0]["details"]["risk"]
    data["heartbeats"][0]["observed_at"] = NOW.isoformat()
    risk["focal_event"] = None
    vendors = ["FOREX_FACTORY_WEEKLY", "SHOWMYTRADES", "HELIOUS"]
    risk["upcoming_events"] = [
        _event("CPI_MOM", 0.3, 0.6, vendors),
        _event("CORE_CPI_MOM", 0.2, 0.3, vendors),
        _event("CPI_YOY", 3.9, 3.7, ["SHOWMYTRADES"]),
    ]
    result = evaluate_pre_news(data, now=NOW)
    assert result["forecast_quorum_met"] is True
    assert len(result["event_cluster"]) == 2

    later = deepcopy(data)
    later_at = datetime(2026, 12, 10, 13, 30, tzinfo=UTC)
    for item in later["heartbeats"][0]["details"]["risk"]["upcoming_events"]:
        item["scheduled_at"] = later_at.isoformat()
    result_later = evaluate_pre_news(later, now=NOW)
    assert result_later["unpublished_components"] == []
    assert len(result_later["event_cluster"]) == 3


def test_secondary_retry_only_for_transient_failure():
    class Fake:
        def __init__(self, err):
            self.calls = 0
            self.err = err

        def get(self, url, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise HttpTransportError(self.err)
            return "OK"

    t = Fake("HTTP_503")
    assert _RetryingSecondaryTransport(t, delay_seconds=0).get(
        "https://example.com", allowed_host="example.com") == "OK"
    assert t.calls == 2

    blocked = Fake("HTTP_403")
    try:
        _RetryingSecondaryTransport(blocked, delay_seconds=0).get(
            "https://example.com", allowed_host="example.com")
    except HttpTransportError:
        pass
    else:
        raise AssertionError("HTTP_403 must never be retried")
    assert blocked.calls == 1
    assert _provider_failure(HttpTransportError("HTTP_403")) == (
        "ERROR:HttpTransportError:HTTP_403"
    )
    assert "secret" not in _provider_failure(
        HttpTransportError("HTTP_429:secret"))

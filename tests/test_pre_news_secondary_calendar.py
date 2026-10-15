from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from fx_scanner.demo_xau_event_risk_v192 import RiskEvent
from fx_scanner.demo_xau_event_risk_v193 import (
    _align_secondary_events,
    _enrich_risk,
    _fuse_events,
)
from fx_scanner.pre_news_secondary_calendar import (
    InvestingCalendarProvider,
    MyfxbookCalendarProvider,
)
from fx_scanner.pre_news_source_fusion import canonical_event_key
from fx_scanner.providers.news import EventImpact


NOW = datetime(2026, 10, 15, 11, 50, tzinfo=UTC)
RELEASE = datetime(2026, 10, 15, 12, 30, tzinfo=UTC)


class FakeTransport:
    def __init__(self, body: str, status: int = 200):
        self.body = body.encode()
        self.status = status
        self.urls: list[str] = []

    def get(self, url, **kwargs):
        self.urls.append(url)
        return SimpleNamespace(status_code=self.status, body=self.body)


def test_myfxbook_csv_adapter_reads_consensus_and_previous():
    body = (
        "Date,Time,Name,Currency,Impact,Previous,Consensus,Actual\n"
        "15-10-2026,12:30,Core Producer Price Index (PPI) MoM,USD,High,0.2%,0.3%,\n"
    )
    transport = FakeTransport(body)
    snapshot = MyfxbookCalendarProvider(transport).fetch(now=NOW)
    event = snapshot.events[0]
    assert event.source == "MYFXBOOK"
    assert event.scheduled_at == RELEASE
    assert event.impact == EventImpact.HIGH
    assert event.forecast == 0.3
    assert event.previous == 0.2
    assert "filter=0-1-2-3_USD" in transport.urls[0]


def test_investing_html_adapter_reads_component_without_antibot_bypass():
    html = """
    <table id="economicCalendarData"><tbody>
      <tr id="eventRowId_1" class="js-event-item" data-event-datetime="2026/10/15 12:30:00">
        <td class="flagCur">USD</td>
        <td class="sentiment" title="High Volatility Expected">
          <i class="grayFullBullishIcon"></i><i class="grayFullBullishIcon"></i><i class="grayFullBullishIcon"></i>
        </td>
        <td class="event">Core PPI (MoM) (Sep)</td>
        <td class="act"></td><td class="fore">0.3%</td><td class="prev">0.2%</td>
      </tr>
    </tbody></table>
    """
    snapshot = InvestingCalendarProvider(FakeTransport(html)).fetch(now=NOW)
    event = snapshot.events[0]
    assert event.source == "INVESTING_COM"
    assert event.scheduled_at == RELEASE
    assert event.impact == EventImpact.HIGH
    assert canonical_event_key(event.title) == "CORE_PPI_MOM"
    assert event.forecast == 0.3
    assert event.previous == 0.2


def _risk_event(source: str, title: str, forecast: float, previous: float, *, hour: int = 12):
    tier = "DISCOVERY_UNVERIFIED" if source == "FOREX_FACTORY_WEEKLY" else "SECONDARY_CONSENSUS"
    return RiskEvent(
        event_id=source + title,
        title=title,
        scheduled_at=datetime(2026, 10, 15, hour, 30, tzinfo=UTC),
        impact="HIGH",
        category="CPI" if "CPI" in title.upper() else "PPI",
        source=source,
        source_tier=tier,
        source_url="https://example.com/calendar",
        forecast=forecast,
        previous=previous,
    )


def test_four_simultaneous_cpi_components_remain_four_components():
    titles = ["Core CPI (MoM)", "Core CPI (YoY)", "CPI (MoM)", "CPI (YoY)"]
    events = []
    for title in titles:
        events.append(_risk_event("FOREX_FACTORY_WEEKLY", title, 0.3, 0.2))
        events.append(_risk_event("MYFXBOOK", title.replace("CPI", "Inflation Rate"), 0.3, 0.2))
    aligned = _align_secondary_events(events)
    fused, metadata = _fuse_events(aligned)
    assert len(fused) == 4
    assert len(metadata) == 4
    assert all(item.source == "MULTI_SOURCE_FUSION" for item in fused)
    assert all(item.source_tier == "SECONDARY_CONSENSUS_FUSED" for item in fused)


def test_source_conflict_is_exposed_and_direction_abstains():
    events = [
        _risk_event("FOREX_FACTORY_WEEKLY", "Core PPI (MoM)", 0.3, 0.2),
        _risk_event("MYFXBOOK", "Core Producer Price Index (PPI) MoM", 0.6, 0.2),
    ]
    fused, metadata = _fuse_events(_align_secondary_events(events))
    raw_risk = {
        "focal_event": fused[0].as_dict(),
        "latest_released_event": None,
        "upcoming_events": [fused[0].as_dict()],
    }
    risk = _enrich_risk(raw_risk, metadata)
    focal = risk["focal_event"]
    assert focal["source_agreement"] == "SOURCE_CONFLICT"
    assert "CONSENSUS_CONFLICT" in focal["conflicts"]
    assert focal["gold_bias"] == "NEUTRAL_SOURCE_CONFLICT"
    assert focal["gold_bias_basis"] == "SOURCE_CONFLICT"


def test_secondary_clock_can_align_to_trusted_matching_component_only():
    trusted = _risk_event("FOREX_FACTORY_WEEKLY", "CPI (MoM)", 0.6, 0.4, hour=12)
    secondary = _risk_event("MYFXBOOK", "Inflation Rate MoM", 0.6, 0.4, hour=8)
    unrelated = _risk_event("MYFXBOOK", "Core Inflation Rate YoY", 3.5, 3.4, hour=8)
    aligned = _align_secondary_events([trusted, secondary, unrelated], max_hours=14)
    matched = next(item for item in aligned if item.title == "Inflation Rate MoM")
    untouched = next(item for item in aligned if item.title == "Core Inflation Rate YoY")
    assert matched.scheduled_at == trusted.scheduled_at
    assert untouched.scheduled_at.hour == 8

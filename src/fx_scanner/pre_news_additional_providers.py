"""Additional, read-only US consensus calendar adapters for the Pre-News panel.

No broker dependencies, order authority, scraping bypasses, or hardcoded API keys.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from typing import Any
from urllib.parse import urlencode

from .exceptions import DataContractError
from .pre_news_secondary_calendar import _event_id, _impact
from .providers.news import EconomicCalendarSnapshot, EconomicEvent, EventImpact, _parse_calendar_number


def _json_response(transport: Any, url: str, host: str) -> Any:
    response = transport.get(
        url,
        allowed_host=host,
        headers={"Accept": "application/json"},
    )
    if int(response.status_code) != 200:
        raise DataContractError(f"calendar source returned HTTP {response.status_code}")
    try:
        return json.loads(response.body)
    except (UnicodeDecodeError, ValueError, TypeError) as exc:
        raise DataContractError("calendar returned invalid JSON") from exc


def _utc(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt.astimezone(UTC) if dt.tzinfo else None
    except (ValueError, TypeError, OverflowError):
        return None


def _not_stale(value: Any, now: datetime, *, max_age_minutes: float) -> bool:
    at = _utc(value)
    if at is None:
        return False
    seconds = (now - at).total_seconds()
    return 0 <= seconds <= max_age_minutes * 60


class ShowMyTradesCalendarProvider:
    """Keyless, provider-cached calendar. Do not count tentative releases."""

    def __init__(
        self, transport: Any, *,
        url: str = "https://showmytrades.com/api/public/calendar/v1",
        allowed_host: str = "showmytrades.com",
    ) -> None:
        self.transport, self.url, self.allowed_host = transport, url, allowed_host

    def fetch(self, *, now: datetime | None = None) -> EconomicCalendarSnapshot:
        current = (now or datetime.now(UTC)).astimezone(UTC)
        query = urlencode({"currency": "USD", "impact": "high,medium", "days": 7})
        source_url = self.url + ("&" if "?" in self.url else "?") + query
        data = _json_response(self.transport, source_url, self.allowed_host)
        if not isinstance(data, dict) or not isinstance(data.get("events"), list):
            raise DataContractError("ShowMyTrades calendar schema invalid")
        if not _not_stale(data.get("generated_at"), current, max_age_minutes=90):
            raise DataContractError("ShowMyTrades calendar generated_at stale")
        events: list[EconomicEvent] = []
        for raw in data["events"]:
            if not isinstance(raw, dict) or str(raw.get("currency") or "").upper() != "USD":
                continue
            if str(raw.get("status") or "").lower() in {"cancelled", "tentative"}:
                continue
            if str(raw.get("confidence") or "").lower() == "sources_disagree":
                continue
            at = _utc(raw.get("time"))
            title = str(raw.get("title") or "").strip()
            if at is None or not title:
                continue
            events.append(EconomicEvent(
                event_id=_event_id("SHOWMYTRADES", title, "USD", at),
                title=title, currency="USD", scheduled_at=at,
                impact=_impact(str(raw.get("impact") or "")),
                source="SHOWMYTRADES", source_url=self.url,
                actual=_parse_calendar_number(raw.get("actual")),
                forecast=_parse_calendar_number(raw.get("forecast")),
                previous=_parse_calendar_number(raw.get("previous")),
            ))
        if not events:
            raise DataContractError("ShowMyTrades calendar contains no usable USD events")
        return EconomicCalendarSnapshot(
            tuple(sorted(events, key=lambda event: (event.scheduled_at, event.event_id))),
            current, "SHOWMYTRADES", self.url,
        )


class HeliousCalendarProvider:
    """Keyless calendar; free data may be delayed ~60 minutes."""

    def __init__(
        self, transport: Any, *,
        url: str = "https://api.helious.io/v1/calendar",
        allowed_host: str = "api.helious.io",
    ) -> None:
        self.transport, self.url, self.allowed_host = transport, url, allowed_host

    def fetch(self, *, now: datetime | None = None) -> EconomicCalendarSnapshot:
        current = (now or datetime.now(UTC)).astimezone(UTC)
        source_url = self.url + ("&" if "?" in self.url else "?") + urlencode({
            "country": "US", "days_back": 1, "days_ahead": 7,
        })
        data = _json_response(self.transport, source_url, self.allowed_host)
        if not isinstance(data, dict) or not isinstance(data.get("data"), dict):
            raise DataContractError("Helious calendar schema invalid")
        raw_events = data["data"].get("events")
        if not isinstance(raw_events, list):
            raise DataContractError("Helious calendar event list missing")
        events: list[EconomicEvent] = []
        for raw in raw_events:
            if not isinstance(raw, dict):
                continue
            if str(raw.get("country") or "").upper() not in {"US", "USA", "UNITED STATES"}:
                continue
            # Earnings and Treasury auctions are not directly comparable to
            # the economic releases in Forex Factory / Myfxbook.
            kind = str(raw.get("type") or "economic").strip().lower()
            if kind != "economic":
                continue
            if str(raw.get("status") or "").lower() in {"cancelled", "postponed"}:
                continue
            at = _utc(raw.get("datetime_utc"))
            title = str(raw.get("title") or "").strip()
            if at is None or not title:
                continue
            events.append(EconomicEvent(
                event_id=_event_id("HELIOUS", title, "USD", at),
                title=title, currency="USD", scheduled_at=at,
                impact=_impact(str(raw.get("impact") or "")),
                source="HELIOUS", source_url=self.url,
                actual=_parse_calendar_number(raw.get("actual")),
                forecast=_parse_calendar_number(raw.get("forecast")),
                previous=_parse_calendar_number(raw.get("previous")),
            ))
        if not events:
            raise DataContractError("Helious calendar contains no usable USD economic events")
        return EconomicCalendarSnapshot(
            tuple(sorted(events, key=lambda event: (event.scheduled_at, event.event_id))),
            current, "HELIOUS", self.url,
        )


class TradingEconomicsCalendarProvider:
    """Licensed backup; requires an explicit subscribed API key."""

    def __init__(
        self, transport: Any, *,
        api_key: str,
        url: str = "https://api.tradingeconomics.com/calendar/country/united%20states",
        allowed_host: str = "api.tradingeconomics.com",
    ) -> None:
        if not str(api_key or "").strip():
            raise ValueError("Trading Economics subscription key required")
        self.transport, self.api_key = transport, str(api_key).strip()
        self.url, self.allowed_host = url, allowed_host

    def fetch(self, *, now: datetime | None = None) -> EconomicCalendarSnapshot:
        current = (now or datetime.now(UTC)).astimezone(UTC)
        source_url = self.url + ("&" if "?" in self.url else "?") + urlencode({
            "c": self.api_key, "f": "json",
        })
        rows = _json_response(self.transport, source_url, self.allowed_host)
        if not isinstance(rows, list):
            raise DataContractError("Trading Economics calendar schema invalid")
        events: list[EconomicEvent] = []
        for raw in rows:
            if not isinstance(raw, dict):
                continue
            if str(raw.get("Country") or "").lower() not in {"united states", "usa", "us"}:
                continue
            at = _utc(raw.get("Date"))
            title = str(raw.get("Event") or "").strip()
            if at is None or not title:
                continue
            importance = int(raw.get("Importance") or 1)
            impact = (
                EventImpact.HIGH if importance >= 3 else
                EventImpact.MEDIUM if importance == 2 else EventImpact.LOW
            )
            events.append(EconomicEvent(
                event_id=_event_id("TRADING_ECONOMICS", title, "USD", at),
                title=title, currency="USD", scheduled_at=at, impact=impact,
                source="TRADING_ECONOMICS",
                source_url="https://tradingeconomics.com/calendar",
                actual=_parse_calendar_number(raw.get("Actual")),
                forecast=_parse_calendar_number(raw.get("Forecast")),
                previous=_parse_calendar_number(raw.get("Previous")),
            ))
        if not events:
            raise DataContractError("Trading Economics calendar contains no usable USD events")
        return EconomicCalendarSnapshot(
            tuple(sorted(events, key=lambda event: (event.scheduled_at, event.event_id))),
            current, "TRADING_ECONOMICS", self.url,
        )

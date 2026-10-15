"""Read-only secondary economic-calendar adapters for Pre-News.

These providers are consensus cross-checks only. They never grant execution
authority, and failures are expected to be handled fail-open by the caller.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
from html.parser import HTMLParser
from io import StringIO
from typing import Any
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from .exceptions import DataContractError
from .providers.news import (
    EconomicCalendarSnapshot,
    EconomicEvent,
    EventImpact,
    _parse_calendar_number,
)


def _event_id(source: str, title: str, currency: str, scheduled_at: datetime) -> str:
    raw = f"{source}|{currency}|{scheduled_at.astimezone(UTC).isoformat()}|{title}".encode()
    return hashlib.sha256(raw).hexdigest()[:24]


def _impact(value: str, *, icon_count: int = 0) -> EventImpact:
    text = str(value or "").strip().upper()
    if icon_count >= 3 or "HIGH" in text:
        return EventImpact.HIGH
    if icon_count == 2 or "MED" in text:
        return EventImpact.MEDIUM
    return EventImpact.LOW


def _parse_datetime(date_text: str, time_text: str, timezone_name: str) -> datetime | None:
    zone = ZoneInfo(timezone_name)
    date_text = str(date_text or "").strip()
    time_text = str(time_text or "").strip()
    combined = f"{date_text} {time_text}".strip()
    formats = (
        "%d-%m-%Y %H:%M",
        "%Y-%m-%d %H:%M",
        "%m/%d/%Y %H:%M",
        "%b %d, %Y %H:%M",
        "%B %d, %Y %H:%M",
        "%d-%m-%Y %I:%M %p",
        "%Y-%m-%d %I:%M %p",
        "%b %d, %Y %I:%M %p",
        "%B %d, %Y %I:%M %p",
    )
    for fmt in formats:
        try:
            return datetime.strptime(combined, fmt).replace(tzinfo=zone).astimezone(UTC)
        except ValueError:
            continue
    return None


def _field(row: dict[str, str], *names: str) -> str:
    normalized = {str(key).strip().lower(): str(value or "").strip() for key, value in row.items()}
    for name in names:
        value = normalized.get(name.lower())
        if value is not None:
            return value
    return ""


class MyfxbookCalendarProvider:
    """Fetch Myfxbook's public CSV export in an explicit UTC window."""

    def __init__(
        self,
        transport: Any,
        *,
        url: str = "https://www.myfxbook.com/calendar_statement.csv",
        allowed_host: str = "www.myfxbook.com",
        timezone_name: str = "UTC",
        currency: str = "USD",
    ) -> None:
        self.transport = transport
        self.url = str(url)
        self.allowed_host = str(allowed_host)
        self.timezone_name = str(timezone_name)
        self.currency = str(currency).upper().strip()

    def fetch(self, *, now: datetime | None = None) -> EconomicCalendarSnapshot:
        fetched_at = (now or datetime.now(tz=UTC)).astimezone(UTC)
        start = fetched_at - timedelta(days=1)
        end = fetched_at + timedelta(days=31)
        query = urlencode(
            {
                "filter": f"0-1-2-3_{self.currency}",
                "start": start.strftime("%Y-%m-%d %H:%M:%S"),
                "end": end.strftime("%Y-%m-%d %H:%M:%S"),
                "calPeriod": "10",
                "tabType": "0",
            }
        )
        source_url = self.url + ("&" if "?" in self.url else "?") + query
        response = self.transport.get(
            source_url,
            allowed_host=self.allowed_host,
            headers={"Accept": "text/csv,text/plain;q=0.9,*/*;q=0.1"},
        )
        if int(response.status_code) != 200:
            raise DataContractError(f"Myfxbook calendar HTTP status {response.status_code}")
        text = response.body.decode("utf-8-sig", errors="replace").strip()
        if not text:
            raise DataContractError("Myfxbook calendar returned an empty CSV export")
        reader = csv.DictReader(StringIO(text))
        if not reader.fieldnames:
            raise DataContractError("Myfxbook calendar CSV header missing")

        events: list[EconomicEvent] = []
        for row in reader:
            date_text = _field(row, "Date")
            time_text = _field(row, "Time")
            title = _field(row, "Name", "Event")
            currency = _field(row, "Currency").upper()
            if not title or currency != self.currency:
                continue
            scheduled_at = _parse_datetime(date_text, time_text, self.timezone_name)
            if scheduled_at is None:
                continue
            events.append(
                EconomicEvent(
                    event_id=_event_id("MYFXBOOK", title, currency, scheduled_at),
                    title=title,
                    currency=currency,
                    scheduled_at=scheduled_at,
                    impact=_impact(_field(row, "Impact")),
                    source="MYFXBOOK",
                    source_url=self.url,
                    actual=_parse_calendar_number(_field(row, "Actual")),
                    forecast=_parse_calendar_number(_field(row, "Consensus", "Forecast")),
                    previous=_parse_calendar_number(_field(row, "Previous")),
                )
            )
        if not events:
            raise DataContractError("Myfxbook calendar contained no usable USD events")
        events.sort(key=lambda event: (event.scheduled_at, event.event_id))
        return EconomicCalendarSnapshot(tuple(events), fetched_at, "MYFXBOOK", self.url)


@dataclass(slots=True)
class _InvestingRow:
    attrs: dict[str, str]
    values: dict[str, str]
    impact_icons: int = 0


class _InvestingCalendarHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[_InvestingRow] = []
        self._row: _InvestingRow | None = None
        self._field_name: str | None = None
        self._parts: list[str] = []

    @staticmethod
    def _class_tokens(attrs: dict[str, str]) -> set[str]:
        return {part for part in attrs.get("class", "").split() if part}

    def handle_starttag(self, tag: str, attrs) -> None:
        values = {str(k): str(v or "") for k, v in attrs}
        lower = tag.lower()
        if lower == "tr":
            classes = self._class_tokens(values)
            row_id = values.get("id", "")
            if "js-event-item" in classes or row_id.startswith("eventRowId"):
                self._row = _InvestingRow(values, {})
            return
        if self._row is None:
            return
        if lower == "td":
            classes = self._class_tokens(values)
            mapping = (
                ("currency", {"flagCur", "currency"}),
                ("title", {"event"}),
                ("impact", {"sentiment"}),
                ("actual", {"act"}),
                ("forecast", {"fore"}),
                ("previous", {"prev"}),
            )
            self._field_name = None
            for field, wanted in mapping:
                if classes.intersection(wanted):
                    self._field_name = field
                    break
            self._parts = []
            if self._field_name == "impact" and values.get("title"):
                self._parts.append(values["title"])
        elif lower == "i" and self._field_name == "impact":
            classes = self._class_tokens(values)
            if any("BullishIcon" in item for item in classes):
                self._row.impact_icons += 1

    def handle_data(self, data: str) -> None:
        if self._row is not None and self._field_name is not None:
            text = " ".join(str(data).split())
            if text:
                self._parts.append(text)

    def handle_endtag(self, tag: str) -> None:
        lower = tag.lower()
        if lower == "td" and self._row is not None and self._field_name is not None:
            self._row.values[self._field_name] = " ".join(self._parts).strip()
            self._field_name = None
            self._parts = []
        elif lower == "tr" and self._row is not None:
            if self._row.values.get("title") and self._row.values.get("currency"):
                self.rows.append(self._row)
            self._row = None
            self._field_name = None
            self._parts = []


def _parse_investing_timestamp(raw: str, timezone_name: str) -> datetime | None:
    text = str(raw or "").strip()
    if not text:
        return None
    if text.isdigit():
        value = int(text)
        if value > 10_000_000_000:
            value //= 1000
        try:
            return datetime.fromtimestamp(value, tz=UTC)
        except (OSError, OverflowError, ValueError):
            return None
    zone = ZoneInfo(timezone_name)
    for fmt in ("%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=zone).astimezone(UTC)
        except ValueError:
            continue
    return None


class InvestingCalendarProvider:
    """Parse the public Investing.com calendar HTML using stable row semantics.

    No anti-bot bypass is attempted. If Investing changes or rejects the public
    GET request, the caller records the source as unavailable and continues.
    """

    def __init__(
        self,
        transport: Any,
        *,
        url: str = "https://www.investing.com/economic-calendar/",
        allowed_host: str = "www.investing.com",
        timezone_name: str = "UTC",
        currency: str = "USD",
    ) -> None:
        self.transport = transport
        self.url = str(url)
        self.allowed_host = str(allowed_host)
        self.timezone_name = str(timezone_name)
        self.currency = str(currency).upper().strip()

    def fetch(self, *, now: datetime | None = None) -> EconomicCalendarSnapshot:
        fetched_at = (now or datetime.now(tz=UTC)).astimezone(UTC)
        response = self.transport.get(
            self.url,
            allowed_host=self.allowed_host,
            headers={
                "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.1",
                "Accept-Language": "en-US,en;q=0.8",
            },
        )
        if int(response.status_code) != 200:
            raise DataContractError(f"Investing calendar HTTP status {response.status_code}")
        parser = _InvestingCalendarHTMLParser()
        parser.feed(response.body.decode("utf-8", errors="replace"))
        events: list[EconomicEvent] = []
        for row in parser.rows:
            currency = row.values.get("currency", "").strip().upper()
            if currency != self.currency:
                continue
            title = row.values.get("title", "").strip()
            raw_time = (
                row.attrs.get("data-event-datetime")
                or row.attrs.get("event_timestamp")
                or row.attrs.get("data-event-timestamp")
                or ""
            )
            scheduled_at = _parse_investing_timestamp(raw_time, self.timezone_name)
            if not title or scheduled_at is None:
                continue
            events.append(
                EconomicEvent(
                    event_id=_event_id("INVESTING_COM", title, currency, scheduled_at),
                    title=title,
                    currency=currency,
                    scheduled_at=scheduled_at,
                    impact=_impact(row.values.get("impact", ""), icon_count=row.impact_icons),
                    source="INVESTING_COM",
                    source_url=self.url,
                    actual=_parse_calendar_number(row.values.get("actual")),
                    forecast=_parse_calendar_number(row.values.get("forecast")),
                    previous=_parse_calendar_number(row.values.get("previous")),
                )
            )
        if not events:
            raise DataContractError("Investing calendar contained no usable USD events")
        events.sort(key=lambda event: (event.scheduled_at, event.event_id))
        return EconomicCalendarSnapshot(tuple(events), fetched_at, "INVESTING_COM", self.url)

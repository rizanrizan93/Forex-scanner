from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
import re
from typing import Any, Iterable
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from .research_xau_event_reaction_v193 import (
    HistoricalEvent,
    classify_event_family,
    parse_release_number,
)

BASE_URLS = (
    "https://www.forexfactory.com/calendar",
    "https://calendar.forexfactory.com/calendar",
    "https://secure.forexfactory.com/calendar",
)
SOURCE = "FOREX_FACTORY_HISTORICAL_RANGE"
SOURCE_TIER = "SECONDARY_CURRENT_PAGE"
MAX_PAGE_BYTES = 8 * 1024 * 1024

_MONTH = {
    1: "jan", 2: "feb", 3: "mar", 4: "apr", 5: "may", 6: "jun",
    7: "jul", 8: "aug", 9: "sep", 10: "oct", 11: "nov", 12: "dec",
}


def _ff_date(value: date) -> str:
    return f"{_MONTH[value.month]}{value.day}.{value.year}"


def _month_ranges(start: date, end: date) -> tuple[tuple[date, date], ...]:
    if start > end:
        return ()
    output: list[tuple[date, date]] = []
    cursor = date(start.year, start.month, 1)
    while cursor <= end:
        if cursor.month == 12:
            next_month = date(cursor.year + 1, 1, 1)
        else:
            next_month = date(cursor.year, cursor.month + 1, 1)
        month_start = max(start, cursor)
        month_end = min(end, next_month - timedelta(days=1))
        output.append((month_start, month_end))
        cursor = next_month
    return tuple(output)


def _fetch_page(start: date, end: date) -> tuple[bytes, str]:
    query = urlencode({"range": f"{_ff_date(start)}-{_ff_date(end)}"})
    errors: list[str] = []
    for base_url in BASE_URLS:
        url = f"{base_url}?{query}"
        req = Request(
            url,
            method="GET",
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Linux; Android 16) AppleWebKit/537.36 "
                    "Chrome/140 Safari/537.36 XAU-V193-Research"
                ),
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "en-US,en;q=0.9",
            },
        )
        try:
            with urlopen(req, timeout=30) as response:
                body = response.read(MAX_PAGE_BYTES + 1)
            if len(body) > MAX_PAGE_BYTES:
                raise RuntimeError("Forex Factory historical page exceeds bounded size")
            if b"calendar" not in body.lower():
                raise RuntimeError("Forex Factory historical page content unexpected")
            return body, url
        except Exception as exc:
            errors.append(f"{base_url}:{type(exc).__name__}:{exc}")
    raise RuntimeError(
        "Forex Factory historical range fetch failed across bounded mirrors: "
        + " | ".join(errors)
    )


def _class_has(cell: Any, token: str) -> bool:
    classes = cell.get("class") or []
    return any(token in str(value) for value in classes)


def _cell(row: Any, token: str):
    return row.find(
        "td",
        class_=lambda value: bool(value)
        and (
            token in value
            if isinstance(value, str)
            else any(token in str(item) for item in value)
        ),
    )


def _impact_from_cell(cell: Any) -> str:
    if cell is None:
        return "UNKNOWN"
    titled = cell.find(attrs={"title": re.compile(r"Impact Expected", re.I)})
    if titled is not None:
        title = str(titled.get("title") or "").upper()
        if "HIGH" in title:
            return "HIGH"
        if "MED" in title:
            return "MEDIUM"
        if "LOW" in title:
            return "LOW"
    html = str(cell).lower()
    if "impact-red" in html or "high impact" in html:
        return "HIGH"
    if "impact-ora" in html or "impact-orange" in html or "med impact" in html:
        return "MEDIUM"
    if "impact-yel" in html or "impact-yellow" in html or "low impact" in html:
        return "LOW"
    return "UNKNOWN"


def _parse_date_text(text: str, year_hint: int) -> date | None:
    normalized = " ".join(str(text).split())
    if not normalized:
        return None
    for fmt in ("%a %b %d %Y", "%b %d %Y"):
        try:
            return datetime.strptime(f"{normalized} {year_hint}", fmt).date()
        except ValueError:
            continue
    match = re.search(r"([A-Za-z]{3})\s+(\d{1,2})", normalized)
    if not match:
        return None
    try:
        return datetime.strptime(
            f"{match.group(1)} {match.group(2)} {year_hint}",
            "%b %d %Y",
        ).date()
    except ValueError:
        return None


def _calendar_timezone_name(soup: Any) -> str:
    text = " ".join(soup.get_text(" ", strip=True).split())
    patterns = (
        r"Calendar Time Zone:\s*([^()]+?)\s*\(GMT",
        r"Time Zone:\s*([^()]+?)\s*\(GMT",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.I)
        if not match:
            continue
        display_name = " ".join(match.group(1).split()).strip()
        # Forex Factory may render a human label such as "America/New York"
        # while Python's IANA key is "America/New_York".
        name = display_name.replace(" ", "_")
        try:
            ZoneInfo(name)
        except Exception as exc:
            raise RuntimeError(
                "Forex Factory calendar timezone is not a valid IANA zone: "
                f"display={display_name!r} normalized={name!r}"
            ) from exc
        return name
    raise RuntimeError(
        "Forex Factory calendar timezone was not explicitly present in the fetched page"
    )


def _calendar_timezone(soup: Any) -> ZoneInfo:
    return ZoneInfo(_calendar_timezone_name(soup))


def _parse_clock(text: str) -> tuple[int, int] | None:
    normalized = str(text).strip().lower().replace(" ", "")
    if not normalized or normalized in {"allday", "tentative"} or "day" in normalized:
        return None
    for fmt in ("%I:%M%p", "%I%p"):
        try:
            parsed = datetime.strptime(normalized, fmt)
            return parsed.hour, parsed.minute
        except ValueError:
            continue
    return None


def parse_forex_factory_html(
    body: bytes,
    *,
    year_hint: int,
    source_url: str,
) -> tuple[HistoricalEvent, ...]:
    try:
        from bs4 import BeautifulSoup
    except ModuleNotFoundError as exc:
        raise RuntimeError("beautifulsoup4 is required for V193 supplement") from exc

    soup = BeautifulSoup(body.decode("utf-8", errors="replace"), "html.parser")
    calendar_tz = _calendar_timezone(soup)
    rows = soup.select("tr.calendar__row")
    if not rows:
        rows = [
            row for row in soup.find_all("tr")
            if row.find("td") is not None
        ]

    current_date: date | None = None
    current_clock: tuple[int, int] | None = None
    output: list[HistoricalEvent] = []

    for ordinal, row in enumerate(rows):
        date_cell = _cell(row, "calendar__date")
        time_cell = _cell(row, "calendar__time")
        currency_cell = _cell(row, "calendar__currency")
        impact_cell = _cell(row, "calendar__impact")
        event_cell = _cell(row, "calendar__event")
        actual_cell = _cell(row, "calendar__actual")
        forecast_cell = _cell(row, "calendar__forecast")
        previous_cell = _cell(row, "calendar__previous")

        date_text = "" if date_cell is None else date_cell.get_text(" ", strip=True)
        parsed_date = _parse_date_text(date_text, year_hint)
        if parsed_date is not None:
            current_date = parsed_date
            current_clock = None

        time_text = "" if time_cell is None else time_cell.get_text(" ", strip=True)
        parsed_clock = _parse_clock(time_text)
        if parsed_clock is not None:
            current_clock = parsed_clock

        if current_date is None or current_clock is None:
            continue

        currency = "" if currency_cell is None else currency_cell.get_text(" ", strip=True).upper()
        if currency != "USD":
            continue

        impact = _impact_from_cell(impact_cell)
        if impact not in {"HIGH", "MEDIUM"}:
            continue

        title = "" if event_cell is None else event_cell.get_text(" ", strip=True)
        if not title:
            continue

        local = datetime(
            current_date.year,
            current_date.month,
            current_date.day,
            current_clock[0],
            current_clock[1],
            tzinfo=calendar_tz,
        )
        scheduled = local.astimezone(UTC)

        raw_key = (
            f"{scheduled.isoformat()}|{currency}|{title}|{ordinal}|{source_url}"
        )
        event_id = sha256(raw_key.encode("utf-8")).hexdigest()[:24]
        output.append(
            HistoricalEvent(
                event_id=event_id,
                scheduled_at=scheduled,
                title=title,
                family=classify_event_family(title),
                impact=impact,
                source=SOURCE,
                source_tier=SOURCE_TIER,
                actual=parse_release_number(
                    None if actual_cell is None else actual_cell.get_text(" ", strip=True)
                ),
                forecast=parse_release_number(
                    None if forecast_cell is None else forecast_cell.get_text(" ", strip=True)
                ),
                previous=parse_release_number(
                    None if previous_cell is None else previous_cell.get_text(" ", strip=True)
                ),
            )
        )
    output.sort(key=lambda item: (item.scheduled_at, item.event_id))
    return tuple(output)


def fetch_supplement(
    *,
    start: date,
    end: date,
) -> tuple[tuple[HistoricalEvent, ...], tuple[dict[str, Any], ...]]:
    events: list[HistoricalEvent] = []
    provenance: list[dict[str, Any]] = []
    for page_start, page_end in _month_ranges(start, end):
        body, url = _fetch_page(page_start, page_end)
        try:
            from bs4 import BeautifulSoup
        except ModuleNotFoundError as exc:
            raise RuntimeError("beautifulsoup4 is required for V193 supplement") from exc
        page_soup = BeautifulSoup(body.decode("utf-8", errors="replace"), "html.parser")
        calendar_timezone = _calendar_timezone_name(page_soup)
        parsed = parse_forex_factory_html(
            body,
            year_hint=page_start.year,
            source_url=url,
        )
        events.extend(parsed)
        provenance.append(
            {
                "range_start": page_start.isoformat(),
                "range_end": page_end.isoformat(),
                "url": url,
                "sha256": sha256(body).hexdigest(),
                "events": len(parsed),
                "source_tier": SOURCE_TIER,
                "calendar_timezone": calendar_timezone,
                "timestamp_contract": "PAGE_DECLARED_IANA_TIMEZONE_TO_UTC",
            }
        )

    dedup: dict[tuple[str, str], HistoricalEvent] = {}
    for event in events:
        key = (event.scheduled_at.isoformat(), event.title.strip().upper())
        dedup[key] = event
    ordered = tuple(sorted(dedup.values(), key=lambda item: (item.scheduled_at, item.event_id)))
    return ordered, tuple(provenance)


def merge_event_corpora(
    archived: Iterable[HistoricalEvent],
    supplement: Iterable[HistoricalEvent],
) -> tuple[HistoricalEvent, ...]:
    # Prefer archived/pinned rows when the same title/timestamp exists.
    merged: dict[tuple[str, str], HistoricalEvent] = {}
    for event in supplement:
        merged[(event.scheduled_at.isoformat(), event.title.strip().upper())] = event
    for event in archived:
        merged[(event.scheduled_at.isoformat(), event.title.strip().upper())] = event
    return tuple(sorted(merged.values(), key=lambda item: (item.scheduled_at, item.event_id)))

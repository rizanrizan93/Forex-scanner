from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from html.parser import HTMLParser
import re
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from .config import ProjectConfig
from .providers.news import EconomicEvent, ForexFactoryCalendarProvider
from .providers.transport import UrllibHttpTransport

NY = ZoneInfo("America/New_York")
WIB = ZoneInfo("Asia/Jakarta")
SCOPE = {
    "CPI",
    "PCE",
    "NFP",
    "ISM",
    "FOMC",
    "JOBLESS_CLAIMS",
    "FED_SPEECH",
    "GEOPOLITICAL_SHOCK",
}


@dataclass(frozen=True, slots=True)
class NewsZoneEvent:
    event_id: str
    title: str
    scheduled_at: datetime
    category: str
    impact: str
    source: str
    source_tier: str
    source_url: str
    unscheduled: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "title": self.title,
            "scheduled_at": self.scheduled_at.astimezone(UTC).isoformat(),
            "scheduled_at_wib": self.scheduled_at.astimezone(WIB).isoformat(),
            "category": self.category,
            "impact": self.impact,
            "source": self.source,
            "source_tier": self.source_tier,
            "source_url": self.source_url,
            "unscheduled": self.unscheduled,
        }


def category_from_title(title: str) -> str | None:
    text = re.sub(r"\s+", " ", str(title or "")).upper().strip()
    if not text:
        return None
    if "CONSUMER PRICE INDEX" in text or re.search(r"\bCPI\b", text):
        return "CPI"
    if "PERSONAL INCOME AND OUTLAYS" in text or re.search(r"\bPCE\b", text):
        return "PCE"
    if (
        "EMPLOYMENT SITUATION" in text
        or "NON-FARM" in text
        or "NONFARM" in text
        or "PAYROLL" in text
        or "AVERAGE HOURLY EARNINGS" in text
        or "UNEMPLOYMENT RATE" in text
    ):
        return "NFP"
    if "ISM" in text and ("PMI" in text or "MANUFACTURING" in text or "SERVICES" in text):
        return "ISM"
    if "FOMC" in text or "FEDERAL FUNDS RATE" in text or "FED FUNDS RATE" in text:
        return "FOMC"
    if (
        "JOBLESS CLAIM" in text
        or "UNEMPLOYMENT CLAIM" in text
        or "UNEMPLOYMENT INSURANCE" in text
        or "UI WEEKLY CLAIM" in text
    ):
        return "JOBLESS_CLAIMS"
    fed_person = (
        "FED CHAIR" in text
        or "FED GOVERNOR" in text
        or "FOMC MEMBER" in text
        or any(
            name in text
            for name in (
                "WARSH",
                "WILLIAMS",
                "WALLER",
                "BARR",
                "JEFFERSON",
                "BOWMAN",
                "LOGAN",
                "GOOLSBEE",
                "DALY",
                "BARKIN",
                "KASHKARI",
                "MIRAN",
            )
        )
    )
    if fed_person and any(word in text for word in ("SPEAK", "SPEECH", "TESTIF", "REMARK")):
        return "FED_SPEECH"
    return None


def _impact(category: str, raw_impact: str | None = None) -> str:
    raw = str(raw_impact or "").upper()
    if category in {"CPI", "PCE", "NFP", "ISM", "FOMC", "GEOPOLITICAL_SHOCK"}:
        return "HIGH"
    if category in {"JOBLESS_CLAIMS", "FED_SPEECH"}:
        return "MEDIUM" if raw != "HIGH" else "HIGH"
    return raw or "LOW"


def _id(source: str, title: str, scheduled_at: datetime) -> str:
    raw = f"{source}|{scheduled_at.astimezone(UTC).isoformat()}|{title}".encode()
    return sha256(raw).hexdigest()[:24]


def from_economic_event(event: EconomicEvent) -> NewsZoneEvent | None:
    if event.currency != "USD":
        return None
    category = category_from_title(event.title)
    if category not in SCOPE:
        return None
    return NewsZoneEvent(
        event_id=event.event_id,
        title=event.title,
        scheduled_at=event.scheduled_at.astimezone(UTC),
        category=category,
        impact=_impact(category, event.impact.value),
        source=event.source,
        source_tier="DISCOVERY_UNVERIFIED",
        source_url=event.source_url,
    )


def _unfold_ics(text: str) -> list[str]:
    raw = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out: list[str] = []
    for line in raw:
        if (line.startswith(" ") or line.startswith("\t")) and out:
            out[-1] += line[1:]
        else:
            out.append(line)
    return out


def _parse_ics_dt(key: str, value: str) -> datetime | None:
    value = value.strip()
    if not value:
        return None
    timezone_name = None
    match = re.search(r"TZID=([^;:]+)", key)
    if match:
        timezone_name = match.group(1)
    if value.endswith("Z"):
        tz = UTC
        value = value[:-1]
    elif timezone_name:
        try:
            tz = ZoneInfo(timezone_name)
        except Exception:
            tz = NY
    else:
        tz = NY
    for fmt in ("%Y%m%dT%H%M%S", "%Y%m%dT%H%M", "%Y%m%d"):
        try:
            parsed = datetime.strptime(value, fmt)
            return parsed.replace(tzinfo=tz).astimezone(UTC)
        except ValueError:
            continue
    return None


def parse_bls_scope(body: bytes, *, source_url: str) -> tuple[NewsZoneEvent, ...]:
    current: dict[str, str] | None = None
    out: list[NewsZoneEvent] = []
    for line in _unfold_ics(body.decode("utf-8", errors="replace")):
        if line == "BEGIN:VEVENT":
            current = {}
            continue
        if line == "END:VEVENT":
            if current:
                title = current.get("SUMMARY", "").strip()
                key = next((k for k in current if k.startswith("DTSTART")), None)
                at = None if key is None else _parse_ics_dt(key, current[key])
                category = category_from_title(title)
                if at is not None and category in SCOPE:
                    out.append(
                        NewsZoneEvent(
                            event_id=_id("BLS_OFFICIAL_ICS", title, at),
                            title=title,
                            scheduled_at=at,
                            category=category,
                            impact=_impact(category),
                            source="BLS_OFFICIAL_ICS",
                            source_tier="OFFICIAL",
                            source_url=source_url,
                        )
                    )
            current = None
            continue
        if current is not None and ":" in line:
            key, value = line.split(":", 1)
            current[key] = value
    return tuple(sorted(out, key=lambda x: x.scheduled_at))


class _TableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.lower() == "tr":
            self._row = []
        elif tag.lower() in {"td", "th"} and self._row is not None:
            self._cell = []

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"td", "th"} and self._row is not None and self._cell is not None:
            self._row.append(re.sub(r"\s+", " ", " ".join(self._cell)).strip())
            self._cell = None
        elif tag.lower() == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None
            self._cell = None


def _parse_bea_when(cells: list[str], year: int) -> tuple[datetime | None, int]:
    candidates: list[tuple[str, int]] = []
    if cells:
        candidates.append((cells[0], 1))
    if len(cells) >= 2:
        candidates.insert(0, (f"{cells[0]} {cells[1]}", 2))
    for raw, used in candidates:
        text = re.sub(r"\s+", " ", raw).strip()
        for fmt in ("%B %d %I:%M %p", "%B %d, %Y %I:%M %p", "%B %d %Y %I:%M %p"):
            try:
                parsed = datetime.strptime(text, fmt)
                if "%Y" not in fmt:
                    parsed = parsed.replace(year=year)
                return parsed.replace(tzinfo=NY).astimezone(UTC), used
            except ValueError:
                continue
    return None, 0


def parse_bea_scope(
    body: bytes,
    *,
    source_url: str,
    now: datetime,
) -> tuple[NewsZoneEvent, ...]:
    parser = _TableParser()
    parser.feed(body.decode("utf-8", errors="replace"))
    out: list[NewsZoneEvent] = []
    for row in parser.rows:
        at, used = _parse_bea_when(row, now.astimezone(NY).year)
        if at is None:
            continue
        remaining = [x for x in row[used:] if x and x.lower() not in {"news", "data", "article"}]
        if not remaining:
            continue
        title = max(remaining, key=len).strip()
        category = category_from_title(title)
        if category not in SCOPE:
            continue
        out.append(
            NewsZoneEvent(
                event_id=_id("BEA_OFFICIAL_SCHEDULE", title, at),
                title=title,
                scheduled_at=at,
                category=category,
                impact=_impact(category),
                source="BEA_OFFICIAL_SCHEDULE",
                source_tier="OFFICIAL",
                source_url=source_url,
            )
        )
    return tuple(sorted(out, key=lambda x: x.scheduled_at))


def merge_events(events: Iterable[NewsZoneEvent]) -> tuple[NewsZoneEvent, ...]:
    ordered = sorted(
        events,
        key=lambda e: (
            e.scheduled_at,
            e.category,
            0 if e.source_tier == "OFFICIAL" else 1,
        ),
    )
    out: list[NewsZoneEvent] = []
    for event in ordered:
        duplicate = next(
            (
                i
                for i, old in enumerate(out)
                if old.category == event.category
                and abs((old.scheduled_at - event.scheduled_at).total_seconds()) <= 120
            ),
            None,
        )
        if duplicate is None:
            out.append(event)
        elif event.source_tier == "OFFICIAL" and out[duplicate].source_tier != "OFFICIAL":
            out[duplicate] = event
    return tuple(sorted(out, key=lambda x: x.scheduled_at))


def collect_news_zone_events(
    cfg: ProjectConfig,
    *,
    now: datetime,
) -> tuple[tuple[NewsZoneEvent, ...], dict[str, str]]:
    transport_cfg = cfg.providers["transport"]
    transport = UrllibHttpTransport(
        timeout_seconds=float(transport_cfg["timeout_seconds"]),
        max_response_bytes=int(transport_cfg["max_response_bytes"]),
        user_agent=str(transport_cfg["user_agent"]),
    )
    calendar = dict(cfg.providers.get("calendar") or {})
    events: list[NewsZoneEvent] = []
    status: dict[str, str] = {}

    ff = dict(calendar.get("FOREX_FACTORY_WEEKLY") or {})
    if ff.get("enabled"):
        try:
            snap = ForexFactoryCalendarProvider(
                transport,
                url=str(ff["base_url"]),
                allowed_host=str(ff["allowed_host"]),
            ).fetch(now=now)
            scoped = [x for e in snap.events if (x := from_economic_event(e)) is not None]
            events.extend(scoped)
            status["FOREX_FACTORY_WEEKLY"] = f"OK:{len(scoped)}"
        except Exception as exc:
            status["FOREX_FACTORY_WEEKLY"] = f"ERROR:{type(exc).__name__}:{exc}"

    bls = dict(calendar.get("BLS_OFFICIAL_ICS") or {})
    if bls.get("enabled"):
        try:
            response = transport.get(
                str(bls["base_url"]),
                allowed_host=str(bls["allowed_host"]),
                headers={"Accept": "text/calendar,text/plain;q=0.9,*/*;q=0.1"},
            )
            scoped = parse_bls_scope(response.body, source_url=str(bls["base_url"]))
            events.extend(scoped)
            status["BLS_OFFICIAL_ICS"] = f"OK:{len(scoped)}"
        except Exception as exc:
            status["BLS_OFFICIAL_ICS"] = f"ERROR:{type(exc).__name__}:{exc}"

    bea = dict(calendar.get("BEA_OFFICIAL_SCHEDULE") or {})
    if bea.get("enabled"):
        try:
            response = transport.get(
                str(bea["base_url"]),
                allowed_host=str(bea["allowed_host"]),
                headers={"Accept": "text/html,*/*;q=0.1"},
            )
            scoped = parse_bea_scope(
                response.body,
                source_url=str(bea["base_url"]),
                now=now,
            )
            events.extend(scoped)
            status["BEA_OFFICIAL_SCHEDULE"] = f"OK:{len(scoped)}"
        except Exception as exc:
            status["BEA_OFFICIAL_SCHEDULE"] = f"ERROR:{type(exc).__name__}:{exc}"

    # Unscheduled geopolitical shocks require a separate verified headline feed.
    # V346 exposes the interface but does not fabricate a shock from price action.
    status["GEOPOLITICAL_SHOCK_FEED"] = "NOT_CONFIGURED_NO_FABRICATION"
    return merge_events(events), status

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from html.parser import HTMLParser
import re
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from .config import load_project_config
from .providers.news import (
    EconomicEvent,
    EventImpact,
    ForexFactoryCalendarProvider,
)
from .providers.transport import UrllibHttpTransport
from .storage.supabase_operational import SupabaseOperationalStore

WORKER_NAME = "ctrader_demo_xau_event_risk_v192"
CONTRACT = "XAU_USD_EVENT_RISK_LAYER_V192"
NY = ZoneInfo("America/New_York")
WIB = ZoneInfo("Asia/Jakarta")

EVENT_HORIZON_HOURS = 36
DISPLAY_EVENTS = 10


@dataclass(frozen=True, slots=True)
class RiskEvent:
    event_id: str
    title: str
    scheduled_at: datetime
    impact: str
    category: str
    source: str
    source_tier: str
    source_url: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "title": self.title,
            "scheduled_at": self.scheduled_at.astimezone(UTC).isoformat(),
            "scheduled_at_wib": self.scheduled_at.astimezone(WIB).isoformat(),
            "impact": self.impact,
            "category": self.category,
            "source": self.source,
            "source_tier": self.source_tier,
            "source_url": self.source_url,
        }


def _event_id(source: str, title: str, scheduled_at: datetime) -> str:
    raw = f"{source}|{scheduled_at.astimezone(UTC).isoformat()}|{title}".encode()
    return sha256(raw).hexdigest()[:24]


def _category(title: str) -> str:
    text = re.sub(r"\s+", " ", str(title)).upper()
    if "JOBLESS" in text or "UNEMPLOYMENT INSURANCE" in text or "UI WEEKLY CLAIMS" in text:
        return "JOBLESS_CLAIMS"
    if "EMPLOYMENT SITUATION" in text or "NONFARM" in text or "PAYROLL" in text:
        return "EMPLOYMENT"
    if "CONSUMER PRICE INDEX" in text or re.search(r"\bCPI\b", text):
        return "CPI"
    if "PRODUCER PRICE INDEX" in text or re.search(r"\bPPI\b", text):
        return "PPI"
    if "PERSONAL INCOME AND OUTLAYS" in text or re.search(r"\bPCE\b", text):
        return "PCE"
    if "GROSS DOMESTIC PRODUCT" in text or re.search(r"\bGDP\b", text):
        return "GDP"
    if "INTERNATIONAL TRANSACTIONS" in text or "CURRENT ACCOUNT" in text:
        return "CURRENT_ACCOUNT"
    if "INTERNATIONAL TRADE" in text or "TRADE IN GOODS" in text:
        return "TRADE"
    if "FOMC" in text or "FEDERAL FUNDS" in text:
        return "FOMC"
    if "FED" in text and ("SPEECH" in text or "SPEAK" in text):
        return "FED_SPEECH"
    if "SPEECH" in text and any(
        name in text
        for name in ("WILLIAMS", "WALLER", "BARR", "JEFFERSON", "BOWMAN", "WARSH")
    ):
        return "FED_SPEECH"
    if "JOLTS" in text or "JOB OPENINGS" in text:
        return "JOLTS"
    return "OTHER_USD"


def _official_impact(title: str) -> str:
    category = _category(title)
    if category in {"EMPLOYMENT", "CPI", "PPI", "PCE", "GDP", "FOMC"}:
        return EventImpact.HIGH.value
    if category in {
        "JOBLESS_CLAIMS",
        "CURRENT_ACCOUNT",
        "TRADE",
        "JOLTS",
        "FED_SPEECH",
    }:
        return EventImpact.MEDIUM.value
    return EventImpact.LOW.value


def _unfold_ics(text: str) -> list[str]:
    raw = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    output: list[str] = []
    for line in raw:
        if (line.startswith(" ") or line.startswith("\t")) and output:
            output[-1] += line[1:]
        else:
            output.append(line)
    return output


def _parse_ics_dt(key: str, value: str) -> datetime | None:
    value = value.strip()
    if not value:
        return None
    timezone_name = None
    match = re.search(r"TZID=([^;:]+)", key)
    if match:
        timezone_name = match.group(1)
    if value.endswith("Z"):
        timezone = UTC
        value = value[:-1]
    elif timezone_name:
        try:
            timezone = ZoneInfo(timezone_name)
        except Exception:
            timezone = NY
    else:
        # BLS publishes release times in Eastern Time.
        timezone = NY

    for fmt in ("%Y%m%dT%H%M%S", "%Y%m%dT%H%M", "%Y%m%d"):
        try:
            parsed = datetime.strptime(value, fmt)
            return parsed.replace(tzinfo=timezone).astimezone(UTC)
        except ValueError:
            continue
    return None


def parse_bls_ics(body: bytes, *, source_url: str) -> tuple[RiskEvent, ...]:
    text = body.decode("utf-8", errors="replace")
    lines = _unfold_ics(text)
    events: list[RiskEvent] = []
    current: dict[str, str] | None = None
    for line in lines:
        if line == "BEGIN:VEVENT":
            current = {}
            continue
        if line == "END:VEVENT":
            if current:
                summary = current.get("SUMMARY", "").strip()
                dt_key = next((key for key in current if key.startswith("DTSTART")), None)
                scheduled = None if dt_key is None else _parse_ics_dt(dt_key, current[dt_key])
                if summary and scheduled is not None:
                    events.append(
                        RiskEvent(
                            event_id=_event_id("BLS_OFFICIAL_ICS", summary, scheduled),
                            title=summary,
                            scheduled_at=scheduled,
                            impact=_official_impact(summary),
                            category=_category(summary),
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
    return tuple(sorted(events, key=lambda event: event.scheduled_at))


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
            value = re.sub(r"\s+", " ", " ".join(self._cell)).strip()
            self._row.append(value)
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


def parse_bea_schedule(
    body: bytes,
    *,
    source_url: str,
    now: datetime,
) -> tuple[RiskEvent, ...]:
    parser = _TableParser()
    parser.feed(body.decode("utf-8", errors="replace"))
    events: list[RiskEvent] = []
    for row in parser.rows:
        scheduled, used = _parse_bea_when(row, now.astimezone(NY).year)
        if scheduled is None:
            continue
        remaining = [cell for cell in row[used:] if cell and cell.lower() not in {"news", "data", "article"}]
        if not remaining:
            continue
        title = max(remaining, key=len).strip()
        if not title or title.lower() == "release":
            continue
        events.append(
            RiskEvent(
                event_id=_event_id("BEA_OFFICIAL_SCHEDULE", title, scheduled),
                title=title,
                scheduled_at=scheduled,
                impact=_official_impact(title),
                category=_category(title),
                source="BEA_OFFICIAL_SCHEDULE",
                source_tier="OFFICIAL",
                source_url=source_url,
            )
        )
    return tuple(sorted(events, key=lambda event: event.scheduled_at))


def _from_discovery(event: EconomicEvent) -> RiskEvent:
    category = _category(event.title)
    source_tier = "DISCOVERY_UNVERIFIED"
    local = event.scheduled_at.astimezone(NY)
    if (
        category == "JOBLESS_CLAIMS"
        and local.weekday() == 3
        and local.hour == 8
        and local.minute == 30
    ):
        source_tier = "OFFICIAL_DOL_CADENCE_MATCHED"
    return RiskEvent(
        event_id=event.event_id,
        title=event.title,
        scheduled_at=event.scheduled_at,
        impact=event.impact.value,
        category=category,
        source=event.source,
        source_tier=source_tier,
        source_url=event.source_url,
    )


def _merge_events(events: Iterable[RiskEvent]) -> tuple[RiskEvent, ...]:
    ordered = sorted(
        events,
        key=lambda event: (
            event.scheduled_at,
            event.category,
            0 if event.source_tier.startswith("OFFICIAL") else 1,
        ),
    )
    merged: list[RiskEvent] = []
    for event in ordered:
        duplicate_index = None
        for index, existing in enumerate(merged):
            if (
                event.category == existing.category
                and abs((event.scheduled_at - existing.scheduled_at).total_seconds()) <= 120
            ):
                duplicate_index = index
                break
        if duplicate_index is None:
            merged.append(event)
            continue
        existing = merged[duplicate_index]
        if (
            event.source_tier.startswith("OFFICIAL")
            and not existing.source_tier.startswith("OFFICIAL")
        ):
            merged[duplicate_index] = event
    return tuple(sorted(merged, key=lambda event: event.scheduled_at))


def evaluate_event_risk(
    events: Iterable[RiskEvent],
    *,
    now: datetime,
) -> dict[str, Any]:
    current = now.astimezone(UTC)
    horizon_end = current + timedelta(hours=EVENT_HORIZON_HOURS)
    relevant = [
        event
        for event in events
        if current - timedelta(minutes=45) <= event.scheduled_at <= horizon_end
    ]

    active: list[tuple[int, RiskEvent, float, str]] = []
    for event in relevant:
        delta_minutes = (event.scheduled_at - current).total_seconds() / 60.0
        if event.impact == EventImpact.HIGH.value:
            pre, live, post = 30.0, 10.0, 30.0
        elif event.impact == EventImpact.MEDIUM.value:
            pre, live, post = 15.0, 5.0, 15.0
        else:
            pre, live, post = 5.0, 2.0, 5.0

        if -live <= delta_minutes <= live:
            active.append((4, event, delta_minutes, "EVENT_WINDOW"))
        elif 0 < delta_minutes <= pre:
            active.append((3, event, delta_minutes, "PRE_EVENT"))
        elif -post <= delta_minutes < 0:
            active.append((2, event, delta_minutes, "POST_EVENT_DISCOVERY"))

    if active:
        active.sort(key=lambda item: (-item[0], abs(item[2]), item[1].scheduled_at))
        _priority, focal, delta_minutes, state = active[0]
    else:
        focal = next((event for event in relevant if event.scheduled_at >= current), None)
        delta_minutes = (
            None
            if focal is None
            else (focal.scheduled_at - current).total_seconds() / 60.0
        )
        state = "CLEAR"

    if state == "EVENT_WINDOW":
        action = "NO_CHASE_WAIT_PRICE_DISCOVERY"
    elif state == "PRE_EVENT":
        action = "PREPARE_ONLY_AVOID_NEW_CHASE"
    elif state == "POST_EVENT_DISCOVERY":
        action = "REVALIDATE_SPREAD_DOM_STRUCTURE"
    else:
        action = "NORMAL_EVENT_RISK_CONTEXT"

    return {
        "state": state,
        "action": action,
        "focal_event": None if focal is None else focal.as_dict(),
        "minutes_to_focal": delta_minutes,
        "upcoming_events": [event.as_dict() for event in relevant[:DISPLAY_EVENTS]],
        "execution_influence": False,
        "execution_authority": False,
        "interpretation": (
            "Event-risk state controls preparation and revalidation context only. "
            "It does not predict event direction or authorize/block an order."
        ),
    }


def run() -> int:
    cfg = load_project_config(None)
    calendar_cfg = cfg.providers.get("calendar", {})
    transport_cfg = cfg.providers["transport"]
    transport = UrllibHttpTransport(
        timeout_seconds=float(transport_cfg["timeout_seconds"]),
        max_response_bytes=int(transport_cfg["max_response_bytes"]),
        user_agent=str(transport_cfg["user_agent"]),
    )
    now = datetime.now(tz=UTC)
    events: list[RiskEvent] = []
    source_status: dict[str, str] = {}

    ff_cfg = calendar_cfg.get("FOREX_FACTORY_WEEKLY", {})
    if bool(ff_cfg.get("enabled", False)):
        try:
            snapshot = ForexFactoryCalendarProvider(
                transport,
                url=str(ff_cfg["base_url"]),
                allowed_host=str(ff_cfg["allowed_host"]),
            ).fetch(now=now)
            usd_events = [event for event in snapshot.events if event.currency == "USD"]
            events.extend(_from_discovery(event) for event in usd_events)
            source_status["FOREX_FACTORY_WEEKLY"] = f"OK:{len(usd_events)}"
        except Exception as exc:
            source_status["FOREX_FACTORY_WEEKLY"] = f"ERROR:{type(exc).__name__}:{exc}"

    bls_cfg = calendar_cfg.get("BLS_OFFICIAL_ICS", {})
    if bool(bls_cfg.get("enabled", False)):
        try:
            response = transport.get(
                str(bls_cfg["base_url"]),
                allowed_host=str(bls_cfg["allowed_host"]),
                headers={"Accept": "text/calendar,text/plain;q=0.9,*/*;q=0.1"},
            )
            parsed = parse_bls_ics(response.body, source_url=str(bls_cfg["base_url"]))
            events.extend(parsed)
            source_status["BLS_OFFICIAL_ICS"] = f"OK:{len(parsed)}"
        except Exception as exc:
            source_status["BLS_OFFICIAL_ICS"] = f"ERROR:{type(exc).__name__}:{exc}"

    bea_cfg = calendar_cfg.get("BEA_OFFICIAL_SCHEDULE", {})
    if bool(bea_cfg.get("enabled", False)):
        try:
            response = transport.get(
                str(bea_cfg["base_url"]),
                allowed_host=str(bea_cfg["allowed_host"]),
                headers={"Accept": "text/html,*/*;q=0.1"},
            )
            parsed = parse_bea_schedule(
                response.body,
                source_url=str(bea_cfg["base_url"]),
                now=now,
            )
            events.extend(parsed)
            source_status["BEA_OFFICIAL_SCHEDULE"] = f"OK:{len(parsed)}"
        except Exception as exc:
            source_status["BEA_OFFICIAL_SCHEDULE"] = f"ERROR:{type(exc).__name__}:{exc}"

    merged = _merge_events(events)
    risk = evaluate_event_risk(merged, now=now)
    official_count = sum(event.source_tier.startswith("OFFICIAL") for event in merged)
    discovery_count = sum(event.source_tier == "DISCOVERY_UNVERIFIED" for event in merged)
    healthy = bool(merged) and any(value.startswith("OK:") for value in source_status.values())

    details = {
        "contract": CONTRACT,
        "symbol": "XAUUSD",
        "currency_focus": "USD",
        "observed_at": now.isoformat(),
        "risk": risk,
        "source_status": source_status,
        "event_count": len(merged),
        "official_or_cadence_verified_count": official_count,
        "discovery_unverified_count": discovery_count,
        "policy_effect": "SHADOW_EVENT_CONTEXT_ONLY",
        "execution_influence": False,
        "execution_authority": False,
    }
    store = SupabaseOperationalStore.from_env()
    store.write_heartbeat(
        WORKER_NAME,
        healthy=healthy,
        lag_seconds=0.0,
        details=details,
    )
    print(
        "CTRADER_DEMO_XAU_EVENT_RISK_V192 "
        f"healthy={int(healthy)} events={len(merged)} "
        f"state={risk.get('state')} action={risk.get('action')} "
        f"execution_authority=0"
    )
    return 0 if healthy else 2


if __name__ == "__main__":
    raise SystemExit(run())

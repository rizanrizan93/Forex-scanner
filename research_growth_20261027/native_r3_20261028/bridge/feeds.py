"""Read-only XAU macro/news snapshot adapter for the frozen cBot contract.

No trading credential or execution function belongs in this module. The logic is
pinned to the XAU frozen replay assumptions: DGS10 for SELL, DFII10 for BUY,
conservative +2 US-federal-business-day availability, and the NFP/CPI/PPI/
JOLTS/ECI/FOMC event family.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from io import StringIO
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo
import json
import re

import pandas as pd
from pandas.tseries.holiday import USFederalHolidayCalendar
from pandas.tseries.offsets import CustomBusinessDay
from icalendar import Calendar

try:
    from .timestamps import parse_utc, utc_text
except ImportError:
    from timestamps import parse_utc, utc_text

UTC = timezone.utc
_CACHE: dict[str, tuple[datetime, bytes]] = {}
FF = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
BLS = "https://www.bls.gov/schedule/news_release/bls.ics"
FRED = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={}"


def fetch(url: str, now: datetime, ttl: timedelta) -> bytes:
    cached = _CACHE.get(url)
    if cached and timedelta(0) <= now - cached[0] < ttl:
        return cached[1]
    request = Request(
        url,
        headers={"User-Agent": "Rizan-cBot-data-bridge/1.1", "Accept": "*/*"},
    )
    with urlopen(request, timeout=15) as response:
        if int(getattr(response, "status", 200)) != 200:
            raise ValueError("SOURCE_HTTP_ERROR")
        body = response.read(8_000_001)
    if len(body) > 8_000_000:
        raise ValueError("SOURCE_TOO_LARGE")
    _CACHE[url] = (now, body)
    return body


def category(title: str) -> str | None:
    text = re.sub(r"\s+", " ", str(title)).upper()
    for name, pattern in (
        ("PPI", r"PRODUCER PRICE INDEX|\bPPI\b"),
        ("JOLTS", r"JOB OPENINGS|JOLTS"),
        ("ECI", r"EMPLOYMENT COST INDEX|\bECI\b"),
        ("CPI", r"CONSUMER PRICE INDEX|\bCPI\b"),
        (
            "NFP",
            r"EMPLOYMENT SITUATION|NON-FARM|NONFARM|PAYROLL|AVERAGE HOURLY EARNINGS|UNEMPLOYMENT RATE",
        ),
        ("FOMC", r"FOMC|FEDERAL FUNDS RATE|FED FUNDS RATE"),
    ):
        if re.search(pattern, text):
            return name
    return None


def macro_point(body: bytes, series: str, now: datetime) -> dict[str, object]:
    """Return the latest point that would have been known under the frozen lag rule."""
    frame = pd.read_csv(StringIO(body.decode())).rename(columns={"observation_date": "DATE"})
    if "DATE" not in frame or series not in frame:
        raise ValueError("MACRO_SCHEMA_INVALID")
    numeric = pd.to_numeric(frame[series], errors="coerce")
    valid = frame.loc[numeric.notna(), ["DATE"]].copy()
    valid[series] = numeric[numeric.notna()].astype(float).to_numpy()
    valid = valid.tail(90)
    if len(valid) < 2:
        raise ValueError("MACRO_INSUFFICIENT_HISTORY")
    dates = pd.to_datetime(valid["DATE"], errors="raise").dt.normalize()
    days = CustomBusinessDay(calendar=USFederalHolidayCalendar())
    available = pd.DatetimeIndex([d + 2 * days for d in dates])
    available = available.tz_localize("America/New_York").tz_convert("UTC")
    rows = pd.DataFrame(
        {
            "value": valid[series].to_numpy(dtype=float),
            "delta": valid[series].diff().to_numpy(dtype=float),
            "available": available,
        }
    )
    now_ts = pd.Timestamp(now.astimezone(UTC))
    known = rows[rows.available <= now_ts]
    if known.empty:
        raise ValueError("MACRO_NOT_AVAILABLE")
    last = known.iloc[-1]
    if pd.isna(last.delta):
        raise ValueError("MACRO_DELTA_MISSING")
    age = now.astimezone(UTC) - last.available.to_pydatetime()
    if age < timedelta(0):
        raise ValueError("MACRO_FROM_FUTURE")
    if age > timedelta(days=7):
        raise ValueError("MACRO_STALE")
    return {
        "Delta": float(last.delta),
        "AvailableUtc": utc_text(last.available.to_pydatetime()),
    }


def ff_events(body: bytes, now: datetime) -> tuple[list[dict[str, str]], datetime, datetime]:
    rows = json.loads(body)
    if not isinstance(rows, list) or not rows:
        raise ValueError("FF_EMPTY_OR_INVALID_CALENDAR")
    local = now.astimezone(ZoneInfo("America/New_York"))
    sunday = (
        local - timedelta(days=(local.weekday() + 1) % 7)
    ).replace(hour=0, minute=0, second=0, microsecond=0)
    start = sunday.astimezone(UTC)
    end = (sunday + timedelta(days=7)).astimezone(UTC)
    parsed: list[tuple[dict, datetime]] = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("FF_ROW_INVALID")
        raw = row.get("date")
        if not raw:
            raise ValueError("FF_UNTIMED_EVENT")
        at = parse_utc(str(raw))
        if at.tzinfo is None:
            raise ValueError("FF_TIMEZONE_REQUIRED")
        parsed.append((row, at.astimezone(UTC)))
    if not any(start <= at < end for _, at in parsed):
        raise ValueError("FF_WEEK_MISMATCH")
    if any(not start <= at < end for _, at in parsed):
        raise ValueError("FF_WEEK_MISMATCH")
    events = [
        {"AtUtc": utc_text(at), "Category": cat}
        for row, at in parsed
        if str(row.get("country", "")).upper() == "USD"
        and (cat := category(str(row.get("title", ""))))
    ]
    return events, start, end


def bls_events(body: bytes, start: datetime, end: datetime) -> list[dict[str, str]]:
    calendar = Calendar.from_ical(body)
    events: list[dict[str, str]] = []
    dates: list[datetime] = []
    for component in calendar.walk("VEVENT"):
        at = component.decoded("DTSTART", None)
        if not isinstance(at, datetime) or at.tzinfo is None:
            raise ValueError("BLS_UNTIMED_EVENT")
        at = at.astimezone(UTC)
        dates.append(at)
        cat = category(str(component.get("SUMMARY", "")))
        if cat:
            events.append({"AtUtc": utc_text(at), "Category": cat})
    if not dates or min(dates) > start or max(dates) < end:
        raise ValueError("BLS_CALENDAR_COVERAGE_INCOMPLETE")
    return events


def snapshot(now: datetime | None = None) -> dict[str, object]:
    """Build the exact camel-case snapshot consumed by RizanXAU.algo."""
    now = now or datetime.now(UTC)
    if now.utcoffset() is None:
        raise ValueError("TIMESTAMP_OFFSET_REQUIRED")
    now = now.astimezone(UTC)
    errors: list[str] = []
    result: dict[str, object] = {
        "ProducedUtc": utc_text(now),
        "CoverageFromUtc": utc_text(now),
        "CoverageToUtc": utc_text(now),
        "ForexFactoryOk": False,
        "BlsOk": False,
        "Dgs10": None,
        "Dfii10": None,
        "Events": [],
        "Errors": errors,
    }
    for series, key in (("DGS10", "Dgs10"), ("DFII10", "Dfii10")):
        try:
            result[key] = macro_point(
                fetch(FRED.format(series), now, timedelta(hours=1)), series, now
            )
        except Exception as exc:
            errors.append(f"{series}:{type(exc).__name__}")
    try:
        events, start, end = ff_events(fetch(FF, now, timedelta(minutes=15)), now)
        result.update(
            ForexFactoryOk=True,
            CoverageFromUtc=utc_text(start),
            CoverageToUtc=utc_text(end),
            Events=events,
        )
    except Exception as exc:
        errors.append(f"FF:{type(exc).__name__}")
        return result
    try:
        combined = list(result["Events"])
        combined.extend(bls_events(fetch(BLS, now, timedelta(minutes=15)), start, end))
        # Stable de-duplication protects against the same release appearing in both calendars.
        unique: dict[tuple[str, str], dict[str, str]] = {}
        for event in combined:
            unique[(event["AtUtc"], event["Category"])] = event
        result["Events"] = [unique[k] for k in sorted(unique)]
        result["BlsOk"] = True
    except Exception as exc:
        errors.append(f"BLS:{type(exc).__name__}")
    return result


if __name__ == "__main__":
    print(json.dumps(snapshot(), indent=2, allow_nan=False))


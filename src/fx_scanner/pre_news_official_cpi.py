"""Read-only parser for BLS CPI monthly actuals; never predicts unpublished data."""
from __future__ import annotations

from datetime import UTC, datetime
from html import unescape
import re
from typing import Any
from zoneinfo import ZoneInfo

OFFICIAL_CPI_URL = "https://www.bls.gov/news.release/cpi.htm"
_NY = ZoneInfo("America/New_York")


def parse_official_cpi_release(
    body: str | bytes, *, now: datetime, source_url: str = OFFICIAL_CPI_URL,
) -> dict[str, Any]:
    """Accept only the current, already-published BLS CPI release.

    Fail closed when the release timestamp or either monthly figure is absent.
    Annual CPI is deliberately not inferred from monthly observations.
    """
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    raw = body.decode("utf-8", errors="replace") if isinstance(body, bytes) else str(body)
    text = re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", raw)))
    date_match = re.search(
        r"embargoed until\s+8:30\s*a\.m\.\s*\(ET\)\s+"
        r"(?:Monday|Tuesday|Wednesday|Thursday|Friday),\s+"
        r"([A-Za-z]+\s+\d{1,2},\s+\d{4})",
        text, re.I,
    )
    if not date_match:
        return {}
    try:
        local_date = datetime.strptime(date_match.group(1), "%B %d, %Y")
        release_local = local_date.replace(hour=8, minute=30, tzinfo=_NY)
    except ValueError:
        return {}
    release_at = release_local.astimezone(UTC)
    elapsed = (now.astimezone(UTC) - release_at).total_seconds()
    if elapsed < 0 or elapsed > 24 * 3600:
        return {}
    period = re.search(
        r"CONSUMER PRICE INDEX\s*[-–]\s*([A-Za-z]+)\s+(\d{4})",
        text, re.I,
    )
    if not period:
        return {}
    month, year = period.group(1).lower(), int(period.group(2))
    if year != release_local.year or month == release_local.strftime("%B").lower():
        # CPI is published the month after the measurement month.
        return {}
    headline = re.search(
        r"Consumer Price Index for All Urban Consumers\s*\(CPI-U\)\s+"
        r"(increased|decreased|rose|fell)\s+([\d.]+)\s+percent\s+"
        r"on a seasonally adjusted basis in\s+([A-Za-z]+)",
        text, re.I,
    )
    core = re.search(
        r"index for all items less food and energy\s+"
        r"(rose|increased|decreased|fell)\s+([\d.]+)\s+percent in\s+([A-Za-z]+)",
        text, re.I,
    )
    if not headline or not core:
        return {}
    if headline.group(3).lower() != month or core.group(3).lower() != month:
        return {}
    def signed(match: re.Match[str]) -> float:
        value = float(match.group(2))
        if value > 10:
            raise ValueError("CPI monthly value outside plausibility range")
        return -value if match.group(1).lower() in {"decreased", "fell"} else value
    try:
        headline_actual, core_actual = signed(headline), signed(core)
    except (ValueError, OverflowError):
        return {}
    return {
        "release_at": release_at,
        "CPI_MOM": headline_actual,
        "CORE_CPI_MOM": core_actual,
        "source_url": source_url,
        "source": "BLS_OFFICIAL_CPI_RELEASE",
    }

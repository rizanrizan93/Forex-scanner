"""Read-only Federal Reserve H.15 fallback for FRED daily Treasury yields.

No live quote, broker order authority, or assumed previous-day values. The
published observation dates (not retrieval time) determine freshness.
"""
from __future__ import annotations

import csv
import io
from datetime import UTC, datetime, time
from math import isfinite
from urllib.parse import urlencode

H15_URL = "https://www.federalreserve.gov/datadownload/Output.aspx?" + urlencode({
    "rel": "H15", "series": "bf17364827e38702b42a58cf8eaa3f78",
    "lastobs": "30", "from": "", "to": "", "filetype": "csv",
    "label": "include", "layout": "seriescolumn", "type": "package",
})
H15_HOST = "www.federalreserve.gov"
H15_SERIES = {
    "US2Y": ("DGS2", "RIFLGFCY02_N.B"),
    "US10Y": ("DGS10", "RIFLGFCY10_N.B"),
    "REAL_YIELD_10Y": ("DFII10", "RIFLGFCY10_XII_N.B"),
}
MAX_DAILY_AGE_SECONDS = 5 * 24 * 60 * 60
MAX_BODY_BYTES = 2 * 1024 * 1024


def parse_h15_daily_rows(raw: bytes, *, now: datetime | None = None) -> dict[str, dict]:
    """Parse the H.15 series-column CSV, skipping ND/missing observations.

    Fail closed when its canonical column IDs or two dated observations are
    absent. Yield units are percentage points; daily delta is basis points.
    """
    now = now or datetime.now(UTC)
    if now.tzinfo is None:
        raise ValueError("H15 now must be timezone aware")
    if len(raw) > MAX_BODY_BYTES:
        raise ValueError("H15 CSV too large")
    rows = csv.reader(io.StringIO(raw.decode("utf-8-sig")))
    columns = None
    history = {name: [] for name in H15_SERIES}
    for fields in rows:
        if not fields:
            continue
        first = fields[0].strip().strip('"').lower()
        if columns is None:
            if first not in {"time period", "date"}:
                continue
            # The CSV includes a separate 'Unique Identifier' metadata row.
            columns = {cell.strip().strip('"'): idx for idx, cell in enumerate(fields)}
            if not any(code in columns for _, code in H15_SERIES.values()):
                raise ValueError("H15 daily series columns unavailable")
            continue
        try:
            observed = datetime.combine(
                datetime.strptime(fields[0].strip(), "%Y-%m-%d").date(),
                time.min, tzinfo=UTC,
            )
        except (ValueError, IndexError):
            continue
        if observed > now:
            continue
        for name, (_series, code) in H15_SERIES.items():
            index = columns.get(code)
            if index is None or index >= len(fields):
                continue
            try:
                value = float(fields[index].strip())
            except (TypeError, ValueError):
                continue
            if isfinite(value) and 0.0 < value < 30.0:
                history[name].append((observed, value))
    if columns is None:
        raise ValueError("H15 CSV Time Period header unavailable")
    output = {}
    for name, (series, _code) in H15_SERIES.items():
        unique = dict(history[name])
        observations = sorted(unique.items())
        if len(observations) < 2:
            continue
        (previous_at, previous), (observed_at, current) = observations[-2:]
        age_seconds = max(0., (now - observed_at).total_seconds())
        freshness = "FRESH" if age_seconds <= MAX_DAILY_AGE_SECONDS else "STALE"
        output[name] = {
            "series": series, "provider": "FEDERAL_RESERVE_H15",
            "source_url": H15_URL, "provider_status": (
                "AVAILABLE" if freshness == "FRESH" else "STALE"
            ),
            "freshness": freshness, "age_seconds": age_seconds,
            "observed_at": observed_at.isoformat(),
            "previous_observed_at": previous_at.isoformat(),
            "current": current, "previous": previous,
            "delta": round((current - previous) * 100.0, 6),
            "delta_unit": "BPS", "execution_authority": False,
            "execution_influence": False,
        }
    return output


def fetch_h15_daily_rows(*, transport=None, now: datetime | None = None) -> dict[str, dict]:
    """Get only one fixed official host, with response/timeout limits."""
    if transport is None:
        from .providers.transport import UrllibHttpTransport
        transport = UrllibHttpTransport(
            timeout_seconds=8.0, max_response_bytes=MAX_BODY_BYTES,
            user_agent="RIZAN-H15-Daily-Fallback/1.0",
        )
    response = transport.get(
        H15_URL, allowed_host=H15_HOST, headers={"Accept": "text/csv"},
    )
    if response.status_code != 200:
        raise ValueError(f"H15 HTTP {response.status_code}")
    return parse_h15_daily_rows(response.body, now=now)

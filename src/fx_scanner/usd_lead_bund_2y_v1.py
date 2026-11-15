"""Bundesbank official daily 2Y Schatz yield, paired to official US Treasury 2Y.

Observation dates are DAILY. The retrieval timestamp is never interpreted as
the market quote or official publication instant. No account or order access.
"""
from __future__ import annotations

import csv
import io
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .usd_lead_decision_v1 import SPREAD_CONTRACT, _dt, _n, _obj

BUND_SERIES = "BBSSY.D.REN.EUR.A610.000000WT0202.A"
BUND_URL = "https://api.statistiken.bundesbank.de/rest/data/BBSSY/D.REN.EUR.A610.000000WT0202.A"
MAX_BYTES = 256 * 1024


def parse_bundesbank_daily_csv(raw: bytes) -> dict[str, float]:
    if len(raw) > MAX_BYTES:
        raise ValueError("BUNDESBANK_CSV_TOO_LARGE")
    text = raw.decode("utf-8-sig")
    if "<html" in text[:150].lower():
        raise ValueError("BUNDESBANK_RETURNED_HTML")
    # SDMX CSV can contain multiple metadata lines before TIME_PERIOD/OBS_VALUE.
    lines = text.splitlines()
    header_index = next((i for i, line in enumerate(lines[:80])
                         if "TIME_PERIOD" in line.upper() and "OBS_VALUE" in line.upper()), None)
    if header_index is None:
        raise ValueError("BUNDESBANK_CSV_NO_SDMX_COLUMNS")
    line = lines[header_index]
    delimiter = ";" if line.count(";") > line.count(",") else ","
    reader = csv.DictReader(io.StringIO("\n".join(lines[header_index:])), delimiter=delimiter)
    columns = {str(c).strip().upper(): c for c in reader.fieldnames or []}
    if "TIME_PERIOD" not in columns or "OBS_VALUE" not in columns:
        raise ValueError("BUNDESBANK_CSV_BAD_COLUMNS")
    result = {}
    for row in reader:
        date = str(row.get(columns["TIME_PERIOD"]) or "").strip().strip('"')
        value = str(row.get(columns["OBS_VALUE"]) or "").strip().strip('"').replace(" ", "")
        if len(date) != 10 or date[4] != "-" or date[7] != "-":
            continue
        try:
            dt = datetime.strptime(date, "%Y-%m-%d")
            v = float(value.replace(",", "."))
        except ValueError:
            continue
        if not -5 <= v <= 20:
            raise ValueError("BUNDESBANK_YIELD_OUT_OF_BOUNDS")
        if date in result and result[date] != v:
            raise ValueError("BUNDESBANK_DUPLICATE_CONFLICT")
        result[date] = v
    if len(result) < 2:
        raise ValueError("BUNDESBANK_INSUFFICIENT_DAILY_OBSERVATIONS")
    return result


def fetch_bundesbank_2y(*, now: datetime, opener=urlopen, timeout_seconds: float = 9.) -> dict:
    if now.tzinfo is None:
        raise ValueError("NOW_REQUIRES_TIMEZONE")
    current = now.astimezone(UTC)
    start = (current - timedelta(days=14)).strftime("%Y-%m-%d")
    url = BUND_URL + "?" + urlencode({"format": "csv", "lang": "en", "startPeriod": start})
    req = Request(url, headers={
        "User-Agent": "RIZAN-USD-Lead-DailyBund/1",
        "Accept": "text/csv,application/vnd.bbk.data+csv;q=0.9",
    })
    with opener(req, timeout=timeout_seconds) as r:
        raw = r.read(MAX_BYTES + 1)
    vals = parse_bundesbank_daily_csv(raw)
    vals = {d: v for d, v in vals.items()
            if datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=UTC) <= current}
    return {
        "series": BUND_SERIES, "source": "DEUTSCHE_BUNDESBANK_DAILY_CSV",
        "retrieved_at": current.isoformat(),
        "daily": vals, "execution_authority": False, "execution_influence": False,
    }


def pair_with_treasury_2y(bundesbank: dict | None, treasury: dict | None,
                          *, now: datetime) -> dict | None:
    """Require two matching official OBSERVATION dates; reject mixed calendars."""
    b = _obj(bundesbank)
    u = _obj(treasury)
    if (b.get("source") != "DEUTSCHE_BUNDESBANK_DAILY_CSV"
            or b.get("series") != BUND_SERIES
            or b.get("execution_authority") is not False
            or b.get("execution_influence") is not False
            or u.get("provider") != "US_TREASURY_DAILY_XML"
            or u.get("release_state") != "CURRENT_PUBLISHED"
            or u.get("freshness") != "FRESH"):
        return None
    at, prev_at = _dt(u.get("observed_at")), _dt(u.get("previous_observed_at"))
    if at is None or prev_at is None or prev_at >= at or now.tzinfo is None:
        return None
    current = now.astimezone(UTC)
    if not 0 <= (current - at).total_seconds() <= 5*86400:
        return None
    days = _obj(b.get("daily"))
    date, prev_date = at.date().isoformat(), prev_at.date().isoformat()
    de = _n(days.get(date))
    de_prev = _n(days.get(prev_date))
    us = _n(u.get("current"))
    us_prev = _n(u.get("previous"))
    if None in (de, de_prev, us, us_prev):
        return None
    return {
        "contract": SPREAD_CONTRACT,
        "source": "US_TREASURY_AND_BUNDESBANK_OFFICIAL_DAILY",
        "observed_at": at.isoformat(), "previous_observed_at": prev_at.isoformat(),
        "us2y_current": us, "us2y_previous": us_prev,
        "de2y_current": de, "de2y_previous": de_prev,
        "retrieved_at": b.get("retrieved_at"),
        "publication_timestamp_audited": False,
        "execution_authority": False, "execution_influence": False,
    }

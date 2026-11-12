"""Primary official U.S. Treasury *daily* nominal/real CMT yield feed.

Treasury is an independent publication path, NOT an intraday yield source.
Use original source observation dates, never dashboard refresh timestamps.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from math import isfinite
from urllib.parse import urlencode
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo

from .providers.transport import HttpTransportError

TREASURY_HOST = "home.treasury.gov"
TREASURY_ENDPOINT = (
    "https://home.treasury.gov/resource-center/data-chart-center/"
    "interest-rates/pages/xml"
)
MAX_XML_BYTES = 2 * 1024 * 1024
MAX_DAILY_AGE_SECONDS = 5 * 86400
_NY = ZoneInfo("America/New_York")
# Treasury nominal constant maturity (BC), TIPS real constant maturity (TC).
SPECS = {
    "US2Y": ("daily_treasury_yield_curve", "BC_2YEAR", "DGS2"),
    "US10Y": ("daily_treasury_yield_curve", "BC_10YEAR", "DGS10"),
    "REAL_YIELD_10Y": ("daily_treasury_real_yield_curve", "TC_10YEAR", "DFII10"),
}


def treasury_xml_url(dataset: str, year_month: str) -> str:
    if dataset not in {"daily_treasury_yield_curve", "daily_treasury_real_yield_curve"}:
        raise ValueError("Unsupported Treasury dataset")
    if not (len(year_month) == 6 and year_month.isascii()
            and year_month.isdigit() and 1 <= int(year_month[4:]) <= 12):
        raise ValueError("Invalid Treasury month")
    return TREASURY_ENDPOINT + "?" + urlencode({
        "data": dataset, "field_tdr_date_value_month": year_month,
    })


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].rsplit(":", 1)[-1]


def _observation_date(raw: str | None) -> date | None:
    if not raw:
        return None
    try:
        # NEW_DATE is an observation calendar date, not a publication timestamp.
        return date.fromisoformat(str(raw).strip()[:10])
    except ValueError:
        return None


def parse_treasury_xml(
    raw: bytes, *, dataset: str, now: datetime,
) -> dict[str, dict[date, float]]:
    """Parse Atom/OData <entry><m:properties><d:NEW_DATE> safely.

    Never forward-fill holidays/blank fields or infer a publication time.
    A record can have a date without any valid yield at a requested tenor.
    """
    if now.tzinfo is None:
        raise ValueError("now must be timezone aware")
    if len(raw) > MAX_XML_BYTES:
        raise ValueError("Treasury XML response too large")
    fields = {
        name: column for name, (source, column, _) in SPECS.items()
        if source == dataset
    }
    if not fields:
        raise ValueError("Unsupported Treasury dataset")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise ValueError("Invalid Treasury XML") from exc
    if _local_name(root.tag) != "feed":
        raise ValueError("Treasury response is not an Atom feed")
    out: dict[str, dict[date, float]] = {name: {} for name in fields}
    today_ny = now.astimezone(_NY).date()
    entries = 0
    for entry in root.iter():
        if _local_name(entry.tag) != "entry":
            continue
        entries += 1
        props = next(
            (e for e in entry.iter() if _local_name(e.tag) == "properties"),
            None,
        )
        if props is None:
            continue
        row = {_local_name(e.tag): (e.text or "").strip() for e in props}
        observed = _observation_date(row.get("NEW_DATE"))
        if observed is None or observed > today_ny:
            continue
        for name, column in fields.items():
            try:
                value = float(row.get(column, ""))
            except (ValueError, TypeError):
                continue
            # TIPS real CMT may be negative, unlike nominal CMT.
            low = -10.0 if name == "REAL_YIELD_10Y" else 0.0
            if isfinite(value) and low < value < 30.0:
                out[name][observed] = value
    if not entries:
        raise ValueError("Treasury XML has no entries")
    return out


def _previous_month(month: str) -> str:
    year, n = int(month[:4]), int(month[4:])
    return f"{year - 1}12" if n == 1 else f"{year}{n - 1:02d}"


def _as_rows(
    histories: dict[str, dict[date, float]], *,
    now: datetime,
) -> dict[str, dict]:
    output = {}
    for name, history in histories.items():
        observations = sorted(history.items())
        if len(observations) < 2:
            continue
        (previous_date, previous), (observed_date, current) = observations[-2:]
        # Use midnight UTC as a DATE marker, not the actual publication time.
        obs = datetime.combine(observed_date, time.min, tzinfo=UTC)
        prev = datetime.combine(previous_date, time.min, tzinfo=UTC)
        age_seconds = (now.astimezone(UTC) - obs).total_seconds()
        if age_seconds < 0:
            continue
        freshness = "FRESH" if age_seconds <= MAX_DAILY_AGE_SECONDS else "STALE"
        dataset, _, fred_series = SPECS[name]
        output[name] = {
            "series": fred_series,
            "provider": "US_TREASURY_DAILY_XML",
            "source_url": treasury_xml_url(dataset, observed_date.strftime("%Y%m")),
            "dataset": dataset,
            "provider_status": "AVAILABLE" if freshness == "FRESH" else "STALE",
            "freshness": freshness,
            "age_seconds": age_seconds,
            "observed_at": obs.isoformat(),
            "previous_observed_at": prev.isoformat(),
            "current": current,
            "previous": previous,
            "delta": round((current - previous) * 100.0, 6),
            "delta_unit": "BPS",
            "observation_basis": "US_TREASURY_DAILY_CLOSE_NOT_INTRADAY",
            "execution_authority": False,
            "execution_influence": False,
        }
    return output


def fetch_treasury_daily_rows(*, transport=None, now: datetime | None = None) -> dict[str, dict]:
    """Get official monthly XML directly; retry preceding month at boundaries.

    Nominal and real datasets are fault-isolated. A missing dataset must not
    create synthetic previous values or prevent use of the other dataset.
    """
    now = now or datetime.now(UTC)
    if now.tzinfo is None:
        raise ValueError("Treasury clock must be timezone-aware")
    if transport is None:
        from .providers.transport import UrllibHttpTransport
        transport = UrllibHttpTransport(
            timeout_seconds=8.0, max_response_bytes=MAX_XML_BYTES,
            user_agent="RIZAN-Official-Treasury-Daily/1.0",
        )
    month = now.astimezone(_NY).strftime("%Y%m")
    histories: dict[str, dict[date, float]] = {name: {} for name in SPECS}
    succeeded = 0
    for dataset in ("daily_treasury_yield_curve", "daily_treasury_real_yield_curve"):
        keys = [name for name, (key, _, _) in SPECS.items() if key == dataset]
        try:
            for month_key in (month, _previous_month(month)):
                # One monthly request normally has enough valid trading days.
                if month_key != month and all(len(histories[k]) >= 2 for k in keys):
                    break
                url = treasury_xml_url(dataset, month_key)
                response = transport.get(
                    url, allowed_host=TREASURY_HOST,
                    headers={"Accept": "application/atom+xml,application/xml"},
                )
                if response.status_code != 200:
                    raise ValueError(f"Treasury HTTP {response.status_code}")
                parsed = parse_treasury_xml(response.body, dataset=dataset, now=now)
                for name in keys:
                    histories[name].update(parsed[name])
            succeeded += 1
        except (ValueError, OSError, TimeoutError, HttpTransportError):
            # Other official dataset may still be useful; fallback is per key.
            continue
    if not succeeded:
        raise ValueError("All official Treasury XML feeds failed")
    return _as_rows(histories, now=now)

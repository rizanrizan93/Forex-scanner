from __future__ import annotations

import csv
import hashlib
import io
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

from .research_xau_hierarchical_regime_router_v35_runtime import COST_SCENARIOS, _fetch, _metric_line
from .research_xau_v47_gvz_implied_vol_v75 import (
    ARTIFACT_CONTRACT,
    FULL_END,
    FULL_START,
    RESEARCH_VERSION,
    availability_timestamp,
    evaluate_v75,
)
from .storage.supabase_operational import SupabaseOperationalStore

UTC = timezone.utc
WORKER_NAME = "dukascopy_xau_v47_gvz_implied_vol_v75"
CBOE_GVZ_URL = "https://cdn.cboe.com/api/global/us_indices/daily_prices/GVZ_History.csv"
FRED_GVZ_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=GVZCLS"
FULL_ERA = {
    "fetch_start": datetime(2011, 1, 1, tzinfo=UTC),
    "start": FULL_START,
    "end": FULL_END,
}


def _download(url: str, *, timeout: int = 90) -> bytes:
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            request = Request(
                url,
                headers={"User-Agent": "ForexScannerResearch-V75/1.0"},
            )
            with urlopen(request, timeout=timeout) as response:
                return response.read()
        except Exception as exc:
            last_error = exc
            if attempt >= 2:
                break
    assert last_error is not None
    raise last_error


def _parse_gvz_csv(raw: bytes, *, source_url: str) -> list[tuple[datetime, float]]:
    text = raw.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    fields = [str(x) for x in (reader.fieldnames or [])]
    normalized = {field.upper().strip(): field for field in fields}
    date_key = (
        normalized.get("DATE")
        or normalized.get("OBSERVATION_DATE")
    )
    if date_key is None:
        raise RuntimeError(f"V75_GVZ_DATE_COLUMN_MISSING:{fields}")

    value_key = None
    if "GVZCLS" in normalized:
        value_key = normalized["GVZCLS"]
    else:
        close_candidates = [
            field
            for field in fields
            if "CLOSE" in field.upper()
        ]
        if close_candidates:
            value_key = close_candidates[-1]
    if value_key is None:
        raise RuntimeError(f"V75_GVZ_CLOSE_COLUMN_MISSING:{fields}")

    rows: list[tuple[datetime, float]] = []
    for row in reader:
        date_raw = row.get(date_key)
        value_raw = row.get(value_key)
        if not date_raw or value_raw in (None, "", "."):
            continue
        parsed = None
        for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y"):
            try:
                parsed = datetime.strptime(str(date_raw).strip(), fmt).replace(tzinfo=UTC)
                break
            except ValueError:
                continue
        if parsed is None:
            continue
        try:
            value = float(str(value_raw).strip())
        except (TypeError, ValueError):
            continue
        if value <= 0.0:
            continue
        rows.append((availability_timestamp(parsed), value))
    rows.sort(key=lambda x: x[0])
    if not rows:
        raise RuntimeError(f"V75_GVZ_PARSE_EMPTY:{source_url}")
    return rows


def _fetch_gvz() -> tuple[list[tuple[datetime, float]], str, int, str]:
    errors: list[str] = []
    for url in (CBOE_GVZ_URL, FRED_GVZ_URL):
        try:
            raw = _download(url)
            rows = _parse_gvz_csv(raw, source_url=url)
            return rows, hashlib.sha256(raw).hexdigest(), len(raw), url
        except Exception as exc:
            errors.append(f"{url}:{type(exc).__name__}:{exc}")
    raise RuntimeError("V75_GVZ_ALL_SOURCES_FAILED:" + " | ".join(errors))


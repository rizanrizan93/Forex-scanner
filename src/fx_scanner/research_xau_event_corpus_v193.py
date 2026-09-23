from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
import tempfile
from typing import Any
from urllib.request import Request, urlopen

import pandas as pd

from .research_xau_event_reaction_v193 import (
    HistoricalEvent,
    classify_event_family,
    parse_release_number,
)

SECONDARY_ARCHIVE_URL = (
    "https://huggingface.co/datasets/Tropstan/Forex_Factory_Calendar/"
    "resolve/refs%2Fconvert%2Fparquet/default/train/0000.parquet?download=true"
)
SECONDARY_ARCHIVE_SHA256 = (
    "c0d3de41b985773f4d37a08a6d3bed29fd89a1789b2115f841f9dac83ace023c"
)
SECONDARY_ARCHIVE_MAX_BYTES = 25 * 1024 * 1024
START_AT = datetime(2012, 1, 1, tzinfo=UTC)


def download_secondary_archive(
    *,
    url: str = SECONDARY_ARCHIVE_URL,
    destination: Path | None = None,
) -> Path:
    target = destination or Path(tempfile.gettempdir()) / "xau-v193-ff-calendar.parquet"
    request = Request(
        url,
        headers={
            "User-Agent": "FX-Institutional-Scanner/0.11 V193 research",
            "Accept": "application/octet-stream",
        },
        method="GET",
    )
    with urlopen(request, timeout=30) as response:
        body = response.read(SECONDARY_ARCHIVE_MAX_BYTES + 1)
    if len(body) > SECONDARY_ARCHIVE_MAX_BYTES:
        raise RuntimeError("V193 secondary archive exceeds bounded size")
    digest = sha256(body).hexdigest()
    if digest != SECONDARY_ARCHIVE_SHA256:
        raise RuntimeError(
            "V193 secondary archive SHA256 mismatch: "
            f"{digest} != {SECONDARY_ARCHIVE_SHA256}"
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(body)
    return target


def dataframe_to_events(frame: pd.DataFrame) -> tuple[HistoricalEvent, ...]:
    required = {
        "DateTime",
        "Currency",
        "Impact",
        "Event",
        "Actual",
        "Forecast",
        "Previous",
    }
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"V193 archive missing columns: {sorted(missing)}")

    work = frame.copy()
    work["Currency"] = work["Currency"].astype(str).str.upper().str.strip()
    work = work.loc[work["Currency"] == "USD"].copy()
    work["scheduled_at"] = pd.to_datetime(work["DateTime"], utc=True, errors="coerce")
    work = work.loc[work["scheduled_at"].notna()].copy()
    work = work.loc[work["scheduled_at"] >= pd.Timestamp(START_AT)].copy()

    impact_text = work["Impact"].astype(str).str.upper()
    work = work.loc[
        impact_text.str.contains("HIGH", na=False)
        | impact_text.str.contains("MEDIUM", na=False)
    ].copy()

    output: list[HistoricalEvent] = []
    for index, row in work.iterrows():
        scheduled = row["scheduled_at"].to_pydatetime().astimezone(UTC)
        title = str(row["Event"]).strip()
        impact = str(row["Impact"]).upper().replace(" IMPACT EXPECTED", "").strip()
        family = classify_event_family(title)
        raw_id = f"{scheduled.isoformat()}|USD|{title}|{index}"
        event_id = sha256(raw_id.encode("utf-8")).hexdigest()[:24]
        output.append(
            HistoricalEvent(
                event_id=event_id,
                scheduled_at=scheduled,
                title=title,
                family=family,
                impact=impact,
                source="FOREX_FACTORY_HISTORICAL_ARCHIVE",
                source_tier="SECONDARY_ARCHIVE",
                actual=parse_release_number(row["Actual"]),
                forecast=parse_release_number(row["Forecast"]),
                previous=parse_release_number(row["Previous"]),
            )
        )
    output.sort(key=lambda event: (event.scheduled_at, event.event_id))
    return tuple(output)


def load_secondary_archive(path: Path) -> tuple[HistoricalEvent, ...]:
    frame = pd.read_parquet(path)
    return dataframe_to_events(frame)


def summarize_corpus(events: tuple[HistoricalEvent, ...]) -> dict[str, Any]:
    families: dict[str, int] = {}
    impacts: dict[str, int] = {}
    surprise_ready = 0
    for event in events:
        families[event.family] = families.get(event.family, 0) + 1
        impacts[event.impact] = impacts.get(event.impact, 0) + 1
        if event.actual is not None and event.forecast is not None:
            surprise_ready += 1
    years = [event.scheduled_at.year for event in events]
    return {
        "source": "FOREX_FACTORY_HISTORICAL_ARCHIVE",
        "source_tier": "SECONDARY_ARCHIVE",
        "source_url": SECONDARY_ARCHIVE_URL,
        "pinned_sha256": SECONDARY_ARCHIVE_SHA256,
        "event_count": len(events),
        "year_min": None if not years else min(years),
        "year_max": None if not years else max(years),
        "surprise_ready_count": surprise_ready,
        "families": dict(sorted(families.items())),
        "impacts": dict(sorted(impacts.items())),
        "official_verification_required": True,
        "execution_influence": False,
        "execution_authority": False,
    }


def serialize_events(events: tuple[HistoricalEvent, ...]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for event in events:
        row = asdict(event)
        row["scheduled_at"] = event.scheduled_at.isoformat()
        rows.append(row)
    return rows

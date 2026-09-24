from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
import re
from typing import Any, Iterable

import pandas as pd

from .research_xau_event_corpus_v193 import (
    download_secondary_archive,
    load_secondary_archive,
)
from .research_xau_event_reaction_v193 import HistoricalEvent
from .research_xau_event_supplement_v193 import fetch_supplement
from .storage.supabase_operational import SupabaseOperationalStore

WORKER_NAME = "ctrader_xau_event_timestamp_audit_v193"
CONTRACT = "XAU_EVENT_TIMESTAMP_AUDIT_V193_1"

MAX_ANCHOR_ERROR_SECONDS = 60.0
MIN_ARCHIVE_OFFSET_RATIO = 0.999
MIN_ARCHIVE_ANCHORS_PASSED = 2

ANCHORS = (
    # Pinned archive anchors. BLS official schedule: 08:30 ET.
    {
        "id": "ARCHIVE_CPI_2025_01_15",
        "source": "ARCHIVE",
        "family": "CPI",
        "day": date(2025, 1, 15),
        "expected_at": datetime(2025, 1, 15, 13, 30, tzinfo=UTC),
        "exclude_title": (),
    },
    {
        "id": "ARCHIVE_CPI_2025_02_12",
        "source": "ARCHIVE",
        "family": "CPI",
        "day": date(2025, 2, 12),
        "expected_at": datetime(2025, 2, 12, 13, 30, tzinfo=UTC),
        "exclude_title": (),
    },
    {
        "id": "ARCHIVE_CPI_2025_03_12",
        "source": "ARCHIVE",
        "family": "CPI",
        "day": date(2025, 3, 12),
        "expected_at": datetime(2025, 3, 12, 12, 30, tzinfo=UTC),
        "exclude_title": (),
    },
    # Supplement anchors across EST and EDT.
    {
        "id": "SUPPLEMENT_CPI_2025_05_13",
        "source": "SUPPLEMENT",
        "family": "CPI",
        "day": date(2025, 5, 13),
        "expected_at": datetime(2025, 5, 13, 12, 30, tzinfo=UTC),
        "exclude_title": (),
    },
    {
        "id": "SUPPLEMENT_CPI_2026_01_13",
        "source": "SUPPLEMENT",
        "family": "CPI",
        "day": date(2026, 1, 13),
        "expected_at": datetime(2026, 1, 13, 13, 30, tzinfo=UTC),
        "exclude_title": (),
    },
    {
        "id": "SUPPLEMENT_NFP_2026_09_04",
        "source": "SUPPLEMENT",
        "family": "NFP_EMPLOYMENT",
        "day": date(2026, 9, 4),
        "expected_at": datetime(2026, 9, 4, 12, 30, tzinfo=UTC),
        "exclude_title": ("ADP",),
    },
    {
        "id": "SUPPLEMENT_PPI_2026_09_10",
        "source": "SUPPLEMENT",
        "family": "PPI",
        "day": date(2026, 9, 10),
        "expected_at": datetime(2026, 9, 10, 12, 30, tzinfo=UTC),
        "exclude_title": (),
    },
    {
        "id": "SUPPLEMENT_CPI_2026_09_11",
        "source": "SUPPLEMENT",
        "family": "CPI",
        "day": date(2026, 9, 11),
        "expected_at": datetime(2026, 9, 11, 12, 30, tzinfo=UTC),
        "exclude_title": (),
    },
)


def explicit_offset_ratio(frame: pd.DataFrame) -> float:
    if "DateTime" not in frame.columns:
        return 0.0
    values = frame["DateTime"].dropna().astype(str).str.strip()
    if values.empty:
        return 0.0
    explicit = values.str.contains(r"(?:Z|[+-]\d{2}:?\d{2})$", regex=True)
    return float(explicit.mean())


def _anchor_match(
    events: Iterable[HistoricalEvent],
    anchor: dict[str, Any],
) -> dict[str, Any]:
    candidates = []
    excluded = tuple(str(x).upper() for x in anchor.get("exclude_title") or ())
    for event in events:
        if event.family != anchor["family"]:
            continue
        if event.scheduled_at.astimezone(UTC).date() != anchor["day"]:
            continue
        title_upper = event.title.upper()
        if any(token in title_upper for token in excluded):
            continue
        candidates.append(event)

    expected = anchor["expected_at"]
    if not candidates:
        return {
            "id": anchor["id"],
            "passed": False,
            "expected_at": expected.isoformat(),
            "candidate_count": 0,
            "reason": "NO_MATCHING_EVENT",
        }

    best = min(
        candidates,
        key=lambda event: abs(
            (event.scheduled_at.astimezone(UTC) - expected).total_seconds()
        ),
    )
    error_seconds = abs(
        (best.scheduled_at.astimezone(UTC) - expected).total_seconds()
    )
    return {
        "id": anchor["id"],
        "passed": error_seconds <= MAX_ANCHOR_ERROR_SECONDS,
        "expected_at": expected.isoformat(),
        "observed_at": best.scheduled_at.astimezone(UTC).isoformat(),
        "error_seconds": error_seconds,
        "title": best.title,
        "family": best.family,
        "source": best.source,
        "source_tier": best.source_tier,
        "candidate_count": len(candidates),
    }


def _supplement_events_and_provenance():
    windows = (
        (date(2025, 5, 1), date(2025, 5, 31)),
        (date(2026, 1, 1), date(2026, 1, 31)),
        (date(2026, 9, 1), date(2026, 9, 24)),
    )
    events = []
    provenance = []
    for start, end in windows:
        rows, prov = fetch_supplement(start=start, end=end)
        events.extend(rows)
        provenance.extend(prov)
    return tuple(events), tuple(provenance)


def run() -> int:
    observed_at = datetime.now(tz=UTC)
    archive_path = download_secondary_archive()
    raw_archive = pd.read_parquet(archive_path)
    offset_ratio = explicit_offset_ratio(raw_archive)
    archive_events = load_secondary_archive(archive_path)

    supplement_events, provenance = _supplement_events_and_provenance()
    timezone_pages = [
        {
            "range_start": row.get("range_start"),
            "range_end": row.get("range_end"),
            "calendar_timezone": row.get("calendar_timezone"),
            "timestamp_contract": row.get("timestamp_contract"),
            "sha256": row.get("sha256"),
        }
        for row in provenance
    ]
    provenance_ok = bool(timezone_pages) and all(
        bool(row.get("calendar_timezone"))
        and row.get("timestamp_contract") == "PAGE_DECLARED_IANA_TIMEZONE_TO_UTC"
        for row in timezone_pages
    )

    anchor_results = []
    for anchor in ANCHORS:
        source_events = (
            archive_events
            if anchor["source"] == "ARCHIVE"
            else supplement_events
        )
        anchor_results.append(_anchor_match(source_events, anchor))

    anchors_passed = sum(bool(row.get("passed")) for row in anchor_results)
    archive_anchor_results = [
        row for row, anchor in zip(anchor_results, ANCHORS)
        if anchor["source"] == "ARCHIVE"
    ]
    supplement_anchor_results = [
        row for row, anchor in zip(anchor_results, ANCHORS)
        if anchor["source"] == "SUPPLEMENT"
    ]
    archive_anchors_passed = sum(
        bool(row.get("passed")) for row in archive_anchor_results
    )
    supplement_anchors_passed = sum(
        bool(row.get("passed")) for row in supplement_anchor_results
    )
    archive_anchor_contract_pass = (
        archive_anchors_passed >= MIN_ARCHIVE_ANCHORS_PASSED
    )
    supplement_anchor_contract_pass = (
        supplement_anchors_passed == len(supplement_anchor_results)
    )
    archive_contract_pass = (
        offset_ratio >= MIN_ARCHIVE_OFFSET_RATIO
        and archive_anchor_contract_pass
    )

    decision = (
        "TIMESTAMP_AUDIT_PASS"
        if archive_contract_pass
        and provenance_ok
        and supplement_anchor_contract_pass
        else "TIMESTAMP_AUDIT_FAIL"
    )
    details = {
        "contract": CONTRACT,
        "observed_at": observed_at.isoformat(),
        "decision": decision,
        "archive": {
            "source": "FOREX_FACTORY_HISTORICAL_ARCHIVE",
            "offset_ratio": offset_ratio,
            "minimum_offset_ratio": MIN_ARCHIVE_OFFSET_RATIO,
            "anchors_passed": archive_anchors_passed,
            "anchor_count": len(archive_anchor_results),
            "minimum_anchors_passed": MIN_ARCHIVE_ANCHORS_PASSED,
            "anchor_contract_pass": archive_anchor_contract_pass,
            "contract_pass": archive_contract_pass,
        },
        "supplement": {
            "source": "FOREX_FACTORY_HISTORICAL_RANGE",
            "page_count": len(timezone_pages),
            "provenance_pass": provenance_ok,
            "anchors_passed": supplement_anchors_passed,
            "anchor_count": len(supplement_anchor_results),
            "anchor_contract_pass": supplement_anchor_contract_pass,
            "pages": timezone_pages,
        },
        "anchors": anchor_results,
        "anchors_passed": anchors_passed,
        "anchor_count": len(anchor_results),
        "maximum_anchor_error_seconds": MAX_ANCHOR_ERROR_SECONDS,
        "policy_effect": "RESEARCH_DATA_INTEGRITY_GATE",
        "execution_influence": False,
        "execution_authority": False,
        "promotion_authority": False,
    }
    healthy = decision == "TIMESTAMP_AUDIT_PASS"
    SupabaseOperationalStore.from_env().write_heartbeat(
        WORKER_NAME,
        healthy=healthy,
        lag_seconds=0.0,
        details=details,
    )
    print(
        "XAU_EVENT_TIMESTAMP_AUDIT_V193 "
        f"decision={decision} archive_offset_ratio={offset_ratio:.6f} "
        f"pages={len(timezone_pages)} anchors={anchors_passed}/{len(anchor_results)} "
        f"archive_anchors={archive_anchors_passed}/{len(archive_anchor_results)} "
        f"supplement_anchors={supplement_anchors_passed}/{len(supplement_anchor_results)} "
        "execution_authority=0"
    )
    for row in anchor_results:
        print(
            "XAU_EVENT_TIMESTAMP_ANCHOR "
            f"id={row['id']} passed={int(bool(row.get('passed')))} "
            f"expected={row.get('expected_at')} observed={row.get('observed_at')} "
            f"error_seconds={row.get('error_seconds')}"
        )
    return 0 if healthy else 2


if __name__ == "__main__":
    raise SystemExit(run())

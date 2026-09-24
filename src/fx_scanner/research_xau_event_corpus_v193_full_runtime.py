from __future__ import annotations

import json
import os
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from .research_xau_event_corpus_v193 import (
    download_secondary_archive,
    load_secondary_archive,
    serialize_events,
    summarize_corpus,
)
from .research_xau_event_supplement_v193 import (
    fetch_supplement,
    merge_event_corpora,
)
from .storage.supabase_operational import SupabaseOperationalStore

WORKER_NAME = "ctrader_xau_event_corpus_v193_full"
ARTIFACT_CONTRACT = "XAU_EVENT_CORPUS_V193_FULL_1"
SUPPLEMENT_START = date(2025, 4, 8)


def _output_path() -> Path:
    raw = os.getenv(
        "XAU_EVENT_CORPUS_V193_FULL_OUTPUT",
        "artifacts/xau-event-corpus-v193-full.json",
    ).strip()
    if not raw:
        raise SystemExit("XAU_EVENT_CORPUS_V193_FULL_OUTPUT_REQUIRED")
    return Path(raw)


def _write(payload: dict[str, Any]) -> str:
    path = _output_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False, default=str)
        + "\n"
    )
    return str(path)


def _heartbeat(details: dict[str, Any], *, healthy: bool) -> None:
    try:
        SupabaseOperationalStore.from_env().write_heartbeat(
            WORKER_NAME,
            healthy=healthy,
            lag_seconds=0.0,
            details=details,
        )
    except Exception as exc:
        details["heartbeat_write_error"] = f"{type(exc).__name__}:{exc}"


def run() -> int:
    now = datetime.now(tz=UTC)
    details: dict[str, Any] = {
        "artifact_contract": ARTIFACT_CONTRACT,
        "observed_at": now.isoformat(),
        "policy_effect": "RESEARCH_ONLY",
        "execution_influence": False,
        "execution_authority": False,
        "promotion_authority": False,
    }
    try:
        archive_path = download_secondary_archive()
        archived = load_secondary_archive(archive_path)
        supplement, provenance = fetch_supplement(
            start=SUPPLEMENT_START,
            end=now.date(),
        )
        merged = merge_event_corpora(archived, supplement)
        summary = summarize_corpus(merged)
        summary["archive_event_count"] = len(archived)
        summary["supplement_event_count"] = len(supplement)
        summary["supplement_start"] = SUPPLEMENT_START.isoformat()
        summary["supplement_end"] = now.date().isoformat()
        summary["year_max"] = (
            None if not merged else max(event.scheduled_at.year for event in merged)
        )
        summary["source_tier"] = "MIXED_PINNED_ARCHIVE_PLUS_SECONDARY_CURRENT_PAGE"
        summary["official_verification_required"] = True
        summary["execution_authority"] = False

        payload = {
            "artifact_contract": ARTIFACT_CONTRACT,
            "contains_secrets": False,
            "details": {
                **details,
                "corpus": summary,
                "supplement_provenance": list(provenance),
                "decision": (
                    "FULL_CORPUS_READY_FOR_REACTION_BACKFILL"
                    if summary.get("year_min") == 2012
                    and int(summary.get("year_max") or 0) >= now.year
                    else "FULL_CORPUS_INCOMPLETE"
                ),
            },
            "events": serialize_events(merged),
        }
        healthy = payload["details"]["decision"] == "FULL_CORPUS_READY_FOR_REACTION_BACKFILL"
        path = _write(payload)
        heartbeat_details = dict(payload["details"])
        heartbeat_details["artifact_path"] = path
        _heartbeat(heartbeat_details, healthy=healthy)
        print(
            "XAU_EVENT_CORPUS_V193_FULL "
            f"events={len(merged)} archive={len(archived)} supplement={len(supplement)} "
            f"years={summary.get('year_min')}-{summary.get('year_max')} "
            f"decision={payload['details']['decision']} artifact={path} "
            "execution_authority=0"
        )
        return 0 if healthy else 2
    except Exception as exc:
        details["decision"] = "FULL_CORPUS_BUILD_FAILED"
        details["error"] = f"{type(exc).__name__}:{exc}"
        path = _write(
            {
                "artifact_contract": ARTIFACT_CONTRACT,
                "contains_secrets": False,
                "details": details,
                "events": [],
            }
        )
        details["artifact_path"] = path
        _heartbeat(details, healthy=False)
        print(
            "XAU_EVENT_CORPUS_V193_FULL "
            f"decision=FULL_CORPUS_BUILD_FAILED error={details['error']} "
            f"artifact={path} execution_authority=0"
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(run())

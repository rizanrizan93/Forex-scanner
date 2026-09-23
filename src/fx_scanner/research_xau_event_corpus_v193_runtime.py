from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .research_xau_event_corpus_v193 import (
    download_secondary_archive,
    load_secondary_archive,
    summarize_corpus,
)
from .storage.supabase_operational import SupabaseOperationalStore

WORKER_NAME = "ctrader_xau_event_corpus_v193"
ARTIFACT_CONTRACT = "XAU_EVENT_CORPUS_V193_1"


def _artifact_path() -> Path:
    raw = os.getenv(
        "XAU_EVENT_CORPUS_V193_OUTPUT",
        "artifacts/xau-event-corpus-v193.json",
    ).strip()
    if not raw:
        raise SystemExit("XAU_EVENT_CORPUS_V193_OUTPUT_REQUIRED")
    return Path(raw)


def _write_artifact(details: dict[str, Any]) -> str:
    path = _artifact_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "artifact_contract": ARTIFACT_CONTRACT,
                "contains_secrets": False,
                "details": details,
            },
            indent=2,
            sort_keys=True,
            allow_nan=False,
            default=str,
        )
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
    observed_at = datetime.now(tz=UTC)
    details: dict[str, Any] = {
        "artifact_contract": ARTIFACT_CONTRACT,
        "observed_at": observed_at.isoformat(),
        "policy_effect": "RESEARCH_ONLY",
        "execution_influence": False,
        "execution_authority": False,
        "promotion_authority": False,
    }
    try:
        path = download_secondary_archive()
        events = load_secondary_archive(path)
        details["corpus"] = summarize_corpus(events)
        details["decision"] = (
            "CORPUS_READY_FOR_REACTION_BACKFILL"
            if len(events) >= 1000
            else "DATA_INSUFFICIENT"
        )
        healthy = details["decision"] == "CORPUS_READY_FOR_REACTION_BACKFILL"
        artifact = _write_artifact(details)
        _heartbeat(details, healthy=healthy)
        print(
            "XAU_EVENT_CORPUS_V193 "
            f"events={len(events)} "
            f"years={details['corpus'].get('year_min')}-{details['corpus'].get('year_max')} "
            f"surprise_ready={details['corpus'].get('surprise_ready_count')} "
            f"decision={details['decision']} artifact={artifact} execution_authority=0"
        )
        return 0 if healthy else 2
    except Exception as exc:
        details["decision"] = "CORPUS_LOAD_FAILED"
        details["error"] = f"{type(exc).__name__}:{exc}"
        artifact = _write_artifact(details)
        _heartbeat(details, healthy=False)
        print(
            "XAU_EVENT_CORPUS_V193 "
            f"decision=CORPUS_LOAD_FAILED error={details['error']} "
            f"artifact={artifact} execution_authority=0"
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(run())

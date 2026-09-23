from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from .research_xau_event_corpus_v193 import (
    download_secondary_archive,
    load_secondary_archive,
)
from .research_xau_event_reaction_v193 import (
    build_reaction_atlas,
    cluster_events,
    reaction_for_cluster,
)
from .storage.supabase_operational import SupabaseOperationalStore

WORKER_NAME = "ctrader_xau_event_reaction_v193"
ARTIFACT_CONTRACT = "XAU_EVENT_REACTION_V193_PILOT_1"


def _parse_dt(name: str, default: str) -> datetime:
    raw = os.getenv(name, default).strip()
    parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _price_path() -> Path:
    raw = os.getenv("XAU_V193_PRICE_CSV", "").strip()
    if not raw:
        raise SystemExit("XAU_V193_PRICE_CSV_REQUIRED")
    path = Path(raw)
    if not path.exists():
        raise SystemExit(f"XAU_V193_PRICE_CSV_NOT_FOUND:{path}")
    return path


def _artifact_path() -> Path:
    raw = os.getenv(
        "XAU_EVENT_REACTION_V193_OUTPUT",
        "artifacts/xau-event-reaction-v193-pilot.json",
    ).strip()
    if not raw:
        raise SystemExit("XAU_EVENT_REACTION_V193_OUTPUT_REQUIRED")
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


def _load_bars(path: Path):
    frame = pd.read_csv(path)
    required = {"timestamp", "open", "high", "low", "close"}
    missing = required - set(frame.columns)
    if missing:
        raise RuntimeError(f"V193 XAU price CSV missing columns: {sorted(missing)}")

    frame["timestamp"] = pd.to_datetime(frame["timestamp"], unit="ms", utc=True, errors="coerce")
    frame = frame.loc[frame["timestamp"].notna()].copy()
    frame = frame.sort_values("timestamp")
    return tuple(frame.itertuples(index=False))


def run() -> int:
    start = _parse_dt("XAU_V193_EVENT_START", "2012-01-01T00:00:00+00:00")
    end = _parse_dt("XAU_V193_EVENT_END", "2012-02-01T00:00:00+00:00")
    if start >= end:
        raise SystemExit("XAU_V193_EVENT_RANGE_INVALID")

    observed_at = datetime.now(tz=UTC)
    details: dict[str, Any] = {
        "artifact_contract": ARTIFACT_CONTRACT,
        "observed_at": observed_at.isoformat(),
        "event_start": start.isoformat(),
        "event_end": end.isoformat(),
        "price_source": "DUKASCOPY_PUBLIC_M5_VIA_DUKASCOPY_NODE_1_50_0",
        "event_source": "FOREX_FACTORY_HISTORICAL_ARCHIVE_SECONDARY",
        "policy_effect": "RESEARCH_ONLY",
        "execution_influence": False,
        "execution_authority": False,
        "promotion_authority": False,
    }

    try:
        archive_path = download_secondary_archive()
        events_all = load_secondary_archive(archive_path)
        events = tuple(
            event
            for event in events_all
            if start <= event.scheduled_at < end
            and event.family != "OTHER_USD"
        )
        bars = _load_bars(_price_path())
        clusters = cluster_events(events)
        reactions = []
        for cluster in clusters:
            row = reaction_for_cluster(cluster, bars)
            if row is not None:
                reactions.append(row)

        details["event_count"] = len(events)
        details["cluster_count"] = len(clusters)
        details["reaction_count"] = len(reactions)
        details["price_bar_count"] = len(bars)
        details["price_start"] = (
            None if not bars else bars[0].timestamp.isoformat()
        )
        details["price_end"] = (
            None if not bars else bars[-1].timestamp.isoformat()
        )
        details["atlas"] = build_reaction_atlas(
            reactions,
            minimum_samples=3,
        )
        details["decision"] = (
            "PILOT_REACTION_ATLAS_AVAILABLE"
            if len(reactions) >= 10
            else "PILOT_DATA_INSUFFICIENT"
        )
        healthy = details["decision"] == "PILOT_REACTION_ATLAS_AVAILABLE"
        artifact = _write_artifact(details)
        _heartbeat(details, healthy=healthy)
        print(
            "XAU_EVENT_REACTION_V193 "
            f"bars={len(bars)} events={len(events)} clusters={len(clusters)} "
            f"reactions={len(reactions)} decision={details['decision']} "
            f"artifact={artifact} execution_authority=0"
        )
        return 0 if healthy else 2
    except Exception as exc:
        details["decision"] = "PILOT_FAILED"
        details["error"] = f"{type(exc).__name__}:{exc}"
        artifact = _write_artifact(details)
        _heartbeat(details, healthy=False)
        print(
            "XAU_EVENT_REACTION_V193 "
            f"decision=PILOT_FAILED error={details['error']} "
            f"artifact={artifact} execution_authority=0"
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(run())

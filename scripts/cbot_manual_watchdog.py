"""Recover the read-only cBot monitor when its published snapshot is stale.

This watchdog can only dispatch the existing GitHub Actions monitor. It never
touches cTrader orders, broker state, account configuration, or VPS services.
"""
from __future__ import annotations

import base64
import json
import os
import subprocess
from datetime import UTC, datetime
from typing import Any

WORKFLOW = "cbot-manual-monitor.yml"
SNAPSHOT_BRANCH = "cbot-manual-snapshots"
MAX_AGE_SECONDS = 180
ACTIVE_STATUSES = frozenset({"requested", "queued", "in_progress", "pending", "waiting"})


def _stamp(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return result.astimezone(UTC) if result.tzinfo else None


def decide(snapshot: dict | None, runs: list[dict], *, now: datetime) -> tuple[str, int | None]:
    """Return FRESH, ACTIVE or DISPATCH, conservatively checking producer runs."""
    published = _stamp((snapshot or {}).get("as_of"))
    age = int((now - published).total_seconds()) if published else None
    if age is not None and -10 <= age <= MAX_AGE_SECONDS:
        return "FRESH", age
    if any(str(run.get("status") or "").lower() in ACTIVE_STATUSES for run in runs):
        return "ACTIVE", age
    return "DISPATCH", age


def gh_api(path: str) -> dict:
    completed = subprocess.run(
        ["gh", "api", path], check=True, text=True, capture_output=True, timeout=30
    )
    return json.loads(completed.stdout)


def main() -> None:
    repo = os.environ["GITHUB_REPOSITORY"]
    try:
        meta = gh_api(
            f"repos/{repo}/contents/runtime/cbot_manual_snapshot.json?ref={SNAPSHOT_BRANCH}"
        )
        if meta.get("encoding") != "base64":
            raise ValueError("Unexpected GitHub content encoding")
        snapshot = json.loads(base64.b64decode(meta["content"]))
    except (subprocess.CalledProcessError, ValueError, KeyError, json.JSONDecodeError):
        # Missing or unreadable publication is stale; the Actions run list
        # must still be readable before a new monitor can be dispatched.
        snapshot = None

    runs = gh_api(
        f"repos/{repo}/actions/workflows/{WORKFLOW}/runs?per_page=10"
    )["workflow_runs"]
    decision, age = decide(snapshot, runs, now=datetime.now(UTC))
    print(f"CBOT_MONITOR_WATCHDOG status={decision} age_seconds={age}", flush=True)
    if decision == "DISPATCH":
        subprocess.run(
            ["gh", "workflow", "run", WORKFLOW, "--ref", "main"],
            check=True, text=True, capture_output=True, timeout=30,
        )
        print("CBOT_MONITOR_RESTART_DISPATCHED", flush=True)


if __name__ == "__main__":
    main()

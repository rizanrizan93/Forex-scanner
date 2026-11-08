"""Read-only BUY050 publication watchdog; never contacts cTrader or changes VPS services.

Runs in the existing dashboard watchdog and requests a *read-only* publisher
workflow_dispatch only when its sanitized GitHub snapshot is stale and no
publisher has started recently. It does not infer that the cBot is disconnected.
"""
from __future__ import annotations

from datetime import UTC, datetime
import json
import os
import subprocess

PUBLISHER = "buy050-dashboard-readonly.yml"
BRANCH = "buy050-monitor-snapshots"
SNAPSHOT = "runtime/buy050_live_snapshot.json"


def age_seconds(value, now):
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            return None
        age = (now - stamp).total_seconds()
        return age if age >= -30 else None
    except (ValueError, TypeError, OverflowError):
        return None


def decide(age, runs):
    """No duplicate dispatches while a queued, running or recently started job exists."""
    if age is not None and age <= 600:
        return "FRESH"
    if any(run.get("status") in {"queued", "pending", "waiting", "in_progress", "requested"}
           for run in runs):
        return "PUBLISHER_ACTIVE"
    if any(run.get("start_age") is not None and run["start_age"] <= 600
           for run in runs):
        return "RECENT_ATTEMPT_BACKOFF"
    return "DISPATCH_READONLY"


def gh(*args):
    return subprocess.check_output(["gh", *args], text=True, stderr=subprocess.PIPE)


def main():
    repo = os.environ["GITHUB_REPOSITORY"]
    now = datetime.now(UTC)
    try:
        raw = gh("api", f"repos/{repo}/contents/{SNAPSHOT}?ref={BRANCH}",
                 "-H", "Accept: application/vnd.github.raw+json")
        snapshot = json.loads(raw)
        age = age_seconds(snapshot.get("observed_at"), now)
    except (subprocess.CalledProcessError, ValueError, TypeError) as exc:
        age = None
        print("BUY050_WATCHDOG snapshot_unavailable", type(exc).__name__)

    try:
        response = json.loads(gh("api", f"repos/{repo}/actions/workflows/{PUBLISHER}/runs?branch=main&per_page=12"))
        runs = [
            {"status": run.get("status"),
             "start_age": age_seconds(run.get("created_at"), now)}
            for run in response.get("workflow_runs", [])
        ]
    except (subprocess.CalledProcessError, ValueError, TypeError) as exc:
        # Fail closed: no dispatch when concurrency state cannot be inspected.
        print("BUY050_WATCHDOG publisher_history_unavailable", type(exc).__name__)
        return

    decision = decide(age, runs)
    print(f"BUY050_WATCHDOG publication_age_seconds={age} action={decision}")
    if decision == "DISPATCH_READONLY":
        gh("workflow", "run", "-R", repo, PUBLISHER, "--ref", "main")


if __name__ == "__main__":
    main()

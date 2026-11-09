"""Read-only recovery for BUY050 shadow and event evidence publications.

GitHub cron is best-effort; this independent supervisor dispatches a single
new read-only job when the last publication has aged out. Never touches VPS
services, cTrader orders, trading parameters, or isolated snapshot branches.
"""
from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, datetime

FEEDS = (
    ("SHADOW", "buy050-shadow-readonly.yml", "buy050-shadow-snapshots",
     "runtime/buy050_shadow_snapshot.json", "as_of"),
    ("EVENT", "buy050-event-audit-readonly.yml", "buy050-event-audit",
     "runtime/buy050_event_timeline.json", "ended_at"),
)
ACTIVE = frozenset(("queued", "pending", "waiting", "requested", "in_progress"))


def age_seconds(value, now):
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            return None
        age = (now - stamp).total_seconds()
        return age if age >= -30 else None
    except (TypeError, ValueError, OverflowError):
        return None


def decide(age, runs, *, freshness_seconds=600, backoff_seconds=600):
    """Never create a second run during active or recent publisher attempts."""
    if age is not None and age <= freshness_seconds:
        return "FRESH"
    if any(r.get("status") in ACTIVE for r in runs):
        return "PUBLISHER_ACTIVE"
    if any(r.get("start_age") is not None and 0 <= r["start_age"] <= backoff_seconds
           for r in runs):
        return "RECENT_ATTEMPT_BACKOFF"
    return "DISPATCH_READONLY"


def gh(*args):
    return subprocess.check_output(["gh", *args], text=True, stderr=subprocess.PIPE)


def inspect_one(repo, now, feed):
    label, workflow, branch, path, clock = feed
    try:
        raw = gh("api", f"repos/{repo}/contents/{path}?ref={branch}",
                 "-H", "Accept: application/vnd.github.raw+json")
        payload = json.loads(raw)
        # Wrong branch/source must never be treated as a healthy observation.
        if payload.get("read_only") is not True or payload.get("execution_authority") is not False:
            raise ValueError("INVALID_READONLY_PROVENANCE")
        age = age_seconds(payload.get(clock), now)
    except (subprocess.CalledProcessError, ValueError, TypeError) as exc:
        age = None
        print(f"BUY050_{label}_WATCHDOG snapshot_unavailable={type(exc).__name__}")

    try:
        runs_obj = json.loads(gh(
            "api", f"repos/{repo}/actions/workflows/{workflow}/runs?branch=main&per_page=15"))
        if not isinstance(runs_obj.get("workflow_runs"), list):
            raise ValueError("RUN_HISTORY_UNAVAILABLE")
        runs = [
            {"status": r.get("status"), "start_age": age_seconds(r.get("created_at"), now)}
            for r in runs_obj["workflow_runs"]
        ]
    except (subprocess.CalledProcessError, ValueError, TypeError) as exc:
        # Never dispatch blindly when runner history is unavailable.
        print(f"BUY050_{label}_WATCHDOG run_history_unavailable={type(exc).__name__}")
        return "UNVERIFIED"

    action = decide(age, runs)
    print(f"BUY050_{label}_WATCHDOG age_seconds={age} active="
          f"{sum(r['status'] in ACTIVE for r in runs)} action={action}")
    if action == "DISPATCH_READONLY":
        gh("workflow", "run", "-R", repo, workflow, "--ref", "main")
    return action


def main():
    repo = os.environ["GITHUB_REPOSITORY"]
    now = datetime.now(UTC)
    for feed in FEEDS:
        try:
            inspect_one(repo, now, feed)
        except subprocess.CalledProcessError as exc:
            # One failed dispatch must not hide the other feed's recovery.
            print(f"BUY050_{feed[0]}_WATCHDOG dispatch_failed={type(exc).__name__}")


if __name__ == "__main__":
    main()

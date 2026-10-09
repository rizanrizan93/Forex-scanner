"""Recover publication failures without restarting healthy/warming publishers."""
from __future__ import annotations
from datetime import UTC, datetime
import json
import os
import subprocess

WORKFLOW = "forexrizan-dashboard-bridge-v254.yml"
SNAPSHOT_BRANCH = "dashboard-snapshots-v344"


def age_seconds(value, now):
    try:
        timestamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            return None
        return max(0.0, (now - timestamp).total_seconds())
    except (TypeError, ValueError):
        return None


def recovery_action(age, publishers):
    if age is not None and age <= 150:
        return "HEALTHY", []
    if not publishers:
        return "DISPATCH", []
    # Unknown publication state is not evidence of a zombie. Preserve startup
    # grace independently of snapshot age so a new runner can install packages.
    zombies = [p["id"] for p in publishers
               if age is not None and age > 300 and p["status"] == "in_progress"
               and p.get("run_age") is not None and p["run_age"] > 300]
    return ("RESTART", zombies) if zombies else ("WAIT_ACTIVE_PUBLISHER", [])


def gh(*args):
    return subprocess.check_output(["gh", *args], text=True)


def main():
    repo = os.environ["GITHUB_REPOSITORY"]
    now = datetime.now(UTC)
    weekday = now.isoweekday()
    if weekday == 6 or (weekday == 7 and now.hour < 21) or (weekday == 5 and now.hour >= 22):
        print("RIZAN_BRIDGE_WATCHDOG market=closed action=SKIP")
        return
    # REST contents reads the current branch publication rather than a CDN copy
    # or the commit author date retained by git commit --amend.
    try:
        payload = json.loads(gh("api", f"repos/{repo}/contents/runtime/xau_dashboard_snapshot.json?ref={SNAPSHOT_BRANCH}",
                                "-H", "Accept: application/vnd.github.raw+json"))
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        payload = {}
    age = age_seconds(payload.get("as_of"), now)
    runs = json.loads(gh("api", f"repos/{repo}/actions/workflows/{WORKFLOW}/runs?branch=main&per_page=20"))
    active = [{"id": r["id"], "status": r["status"],
               "run_age": age_seconds(r.get("run_started_at"), now)}
              for r in runs.get("workflow_runs", [])
              if r["status"] in {"queued", "pending", "waiting", "in_progress"}]
    action, cancel = recovery_action(age, active)
    print(f"RIZAN_BRIDGE_WATCHDOG publication_age_seconds={age} active={len(active)} action={action}")
    for worker in ("ctrader_demo_xau_sd_liquidity_v342", "ctrader_demo_eurusd_frozen_dd37"):
        rows = [r for r in payload.get("backend", {}).get("heartbeats", []) if r.get("worker_name") == worker]
        observed = max((r.get("observed_at", "") for r in rows), default=None)
        print(f"RIZAN_ENGINE_FRESHNESS worker={worker} age_seconds={age_seconds(observed, now)}")
    for run_id in cancel:
        subprocess.run(["gh", "run", "cancel", "-R", repo, str(run_id)], check=False)
    if action in {"DISPATCH", "RESTART"}:
        gh("workflow", "run", "-R", repo, WORKFLOW, "--ref", "main")


if __name__ == "__main__":
    main()

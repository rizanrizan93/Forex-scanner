"""Read-only XAU M15 forecast feed freshness supervisor.

Dispatches only the independent market publisher. Never accesses broker account,
cBots, secrets, positions or orders. GitHub scheduled runs may be delayed.
"""
from __future__ import annotations
from datetime import UTC, datetime
import json
import os
import subprocess

WORKFLOW = "xau-m15-market-readonly.yml"
BRANCH = "xau-m15-market-snapshots"
PATH = "runtime/xau_m15_market.json"
ACTIVE = frozenset({"queued", "pending", "waiting", "requested", "in_progress"})


def age(value, now):
    try:
        t = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if t.tzinfo is None:
            return None
        result = (now - t).total_seconds()
        return result if result >= -30 else None
    except (ValueError, TypeError, OverflowError):
        return None


def decision(price_age, runs):
    if price_age is not None and price_age <= 150:
        return "FRESH"
    if any(r["status"] in ACTIVE for r in runs):
        return "ACTIVE_PUBLISHER"
    if any(r["age"] is not None and r["age"] <= 300 for r in runs):
        return "RECENT_RUN_BACKOFF"
    return "DISPATCH_READONLY"


def gh(*args):
    return subprocess.check_output(["gh", *args], text=True, stderr=subprocess.PIPE)


def main():
    repo = os.environ["GITHUB_REPOSITORY"]
    now = datetime.now(UTC)
    try:
        snap = json.loads(gh("api", f"repos/{repo}/contents/{PATH}?ref={BRANCH}",
                             "-H", "Accept: application/vnd.github.raw+json"))
        if snap.get("contract") != "RIZAN_XAU_M15_BROKER_READONLY_V1" or snap.get("execution_authority") is not False:
            raise ValueError("M15_SOURCE_INVALID")
        quote_age = age(snap.get("price_observed_at"), now)
    except (subprocess.CalledProcessError, ValueError, TypeError) as exc:
        quote_age = None
        print("XAU_M15_WATCHDOG snapshot_unavailable=" + type(exc).__name__)
    try:
        raw = json.loads(gh("api", f"repos/{repo}/actions/workflows/{WORKFLOW}/runs?branch=main&per_page=20"))
        if not isinstance(raw.get("workflow_runs"), list):
            raise ValueError("RUN_HISTORY_INVALID")
        runs = [{"status": r.get("status"), "age": age(r.get("created_at"), now)}
                for r in raw["workflow_runs"]]
    except (subprocess.CalledProcessError, ValueError, TypeError) as exc:
        print("XAU_M15_WATCHDOG run_history_unavailable=" + type(exc).__name__)
        return
    action = decision(quote_age, runs)
    print(f"XAU_M15_WATCHDOG price_age_s={quote_age} runs={len(runs)} action={action}")
    if action == "DISPATCH_READONLY":
        gh("workflow", "run", "-R", repo, WORKFLOW, "--ref", "main")


if __name__ == "__main__":
    main()

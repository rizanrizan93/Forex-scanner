"""Continuous bounded XAU M15 read-only publisher on isolated GitHub branch.

Only sanitized broker M1/M15 closes are published. No order/position access,
cBot service changes, token refresh, or price-time fabrication.
"""
from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from fx_scanner.xau_m15_macro_forecast import validate_fast_m15_snapshot

REPO = "rizanrizan93/Forex-scanner"
BRANCH = "xau-m15-market-snapshots"
DEST = "runtime/xau_m15_market.json"
LOCAL = Path("artifacts/xau_m15_market.json")


def api(method, endpoint, payload=None):
    if os.environ.get("GITHUB_REPOSITORY") != REPO:
        raise ValueError("WRONG_REPOSITORY")
    url = "https://api.github.com/repos/" + REPO + "/" + endpoint
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Authorization": "Bearer " + os.environ["GITHUB_TOKEN"],
               "Accept": "application/vnd.github+json",
               "User-Agent": "RIZAN-XAU-M15-Readonly/1"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    with urlopen(Request(url, data=data, headers=headers, method=method), timeout=20) as response:
        return json.load(response)


def ensure_branch():
    try:
        api("GET", "git/ref/heads/" + BRANCH)
    except HTTPError as exc:
        if exc.code != 404:
            raise
        api("POST", "git/refs", {"ref": "refs/heads/" + BRANCH,
                                 "sha": os.environ["GITHUB_SHA"]})


def publish(snapshot):
    validate_fast_m15_snapshot(snapshot)
    ensure_branch()
    sha = None
    try:
        old = api("GET", "contents/" + DEST + "?ref=" + BRANCH)
        sha = old.get("sha")
    except HTTPError as exc:
        if exc.code != 404:
            raise
    content = json.dumps(snapshot, allow_nan=False, separators=(",", ":")).encode()
    kwargs = {"message": "monitor(xau): publish fresh closed broker M15 + M1",
              "branch": BRANCH, "content": base64.b64encode(content).decode()}
    if sha:
        kwargs["sha"] = sha
    api("PUT", "contents/" + DEST, kwargs)


def cycle():
    LOCAL.parent.mkdir(parents=True, exist_ok=True)
    LOCAL.unlink(missing_ok=True)
    subprocess.run([sys.executable, "scripts/collect_xau_m15_readonly.py", str(LOCAL)],
                   check=True, timeout=65)
    data = json.loads(LOCAL.read_text(encoding="utf-8"))
    validate_fast_m15_snapshot(data)
    publish(data)
    print("XAU_M15_PUBLISHED closed=" + data["latest_closed_m15"]["closed_at"]
          + " price_at=" + data["price_observed_at"], flush=True)


def main():
    seconds = min(3300, max(60, int(os.environ.get("XAU_M15_LOOP_SECONDS", "3300"))))
    until = time.monotonic() + seconds
    count = 0
    while time.monotonic() < until:
        started = time.monotonic()
        count += 1
        try:
            cycle()
        except (ValueError, RuntimeError, subprocess.CalledProcessError,
                subprocess.TimeoutExpired, OSError, KeyError, HTTPError, URLError) as exc:
            # No old candle ever inherits a fresh publication time.
            print("XAU_M15_CYCLE_SKIPPED index=" + str(count)
                  + " reason=" + type(exc).__name__, flush=True)
        remaining = min(max(0, 60 - (time.monotonic() - started)), until - time.monotonic())
        if remaining > 0:
            time.sleep(remaining)


if __name__ == "__main__":
    main()

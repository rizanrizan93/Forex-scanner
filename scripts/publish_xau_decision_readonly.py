"""Publish validated XAUUSD closed candles to an isolated GitHub-only branch.

The collector is MARKET DATA READ ONLY. No token refresh, orders, positions,
account balance, cBot state, bridge or VPS modifications.
"""
from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from datetime import UTC, datetime

from fx_scanner.xau_decision_candle_feed_v1 import (
    BRANCH, PATH, REPOSITORY, validate_candle_snapshot,
)

ARTIFACT = Path("artifacts/xau_decision_candles.json")


def request(method: str, endpoint: str, body: dict | None = None) -> dict:
    if os.environ.get("GITHUB_REPOSITORY") != REPOSITORY:
        raise ValueError("PUBLISHER_REPO_MISMATCH")
    data = None if body is None else json.dumps(body).encode()
    headers = {
        "Authorization": "Bearer " + os.environ["GITHUB_TOKEN"],
        "Accept": "application/vnd.github+json",
        "User-Agent": "RIZAN-XAU-Decision-ReadOnlyPublisher",
    }
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = Request(
        "https://api.github.com/repos/" + REPOSITORY + "/" + endpoint,
        data=data, method=method, headers=headers,
    )
    with urlopen(req, timeout=20) as response:
        return json.load(response)


def ensure_branch() -> None:
    try:
        request("GET", "git/ref/heads/" + BRANCH)
    except HTTPError as exc:
        if exc.code != 404:
            raise
        # This operation creates only the independent snapshot branch.
        request("POST", "git/refs", {
            "ref": "refs/heads/" + BRANCH, "sha": os.environ["GITHUB_SHA"],
        })


def publish(data: dict) -> None:
    validate_candle_snapshot(data, now=datetime.now(UTC))
    ensure_branch()
    sha = None
    try:
        sha = request("GET", "contents/" + PATH + "?ref=" + BRANCH).get("sha")
    except HTTPError as exc:
        if exc.code != 404:
            raise
    payload = json.dumps(data, allow_nan=False, separators=(",", ":")).encode()
    args = {
        "branch": BRANCH,
        "message": "market(xau): publish latest CLOSED H1 M15 M5 read-only candles",
        "content": base64.b64encode(payload).decode(),
    }
    if sha:
        args["sha"] = sha
    request("PUT", "contents/" + PATH, args)
    print("XAU_DECISION_READONLY_PUBLISHED original_at=" + data["as_of"], flush=True)


def cycle():
    """Collect a new source observation every time; never redate an old file."""
    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACT.unlink(missing_ok=True)
    subprocess.run(
        [sys.executable, "scripts/collect_xau_decision_readonly.py", str(ARTIFACT)],
        check=True, timeout=90,
    )
    payload = json.loads(ARTIFACT.read_text())
    publish(payload)
    return payload["as_of"]


def run_loop(*, duration_seconds=3300, cycle_fn=cycle, clock=time.monotonic,
             wait=time.sleep):
    """Bounded runner, retried collection, then workflow queues a replacement."""
    duration_seconds = min(3300, max(1, int(duration_seconds)))
    until = clock() + duration_seconds
    successes = 0
    while clock() < until:
        started = clock()
        try:
            observed = cycle_fn()
            successes += 1
            print("XAU_DECISION_CYCLE_OK original_at=" + observed, flush=True)
        except (ValueError, RuntimeError, OSError, KeyError,
                subprocess.SubprocessError) as exc:
            print("XAU_DECISION_CYCLE_SKIPPED reason=" + type(exc).__name__, flush=True)
        delay = min(max(0, 45-(clock()-started)), max(0, until-clock()))
        if delay > 0:
            wait(delay)
    if not successes:
        raise RuntimeError("XAU_DECISION_NO_FRESH_PUBLICATIONS")
    return successes


def main():
    run_loop(duration_seconds=int(os.environ.get("XAU_DECISION_LOOP_SECONDS", "3300")))


if __name__ == "__main__":
    main()

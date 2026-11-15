"""Publish validated XAUUSD closed candles to an isolated GitHub-only branch.

The collector is MARKET DATA READ ONLY. No token refresh, orders, positions,
account balance, cBot state, bridge or VPS modifications.
"""
from __future__ import annotations

import base64
import json
import os
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


def main():
    if not ARTIFACT.exists():
        raise ValueError("MISSING_CTRADER_READONLY_COLLECTOR_OUTPUT")
    payload = json.loads(ARTIFACT.read_text())
    publish(payload)


if __name__ == "__main__":
    main()

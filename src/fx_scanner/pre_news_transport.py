"""Dedicated public pre-news feed, independent of trading-engine heartbeats."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from urllib.request import Request, urlopen

from .pre_news_expectation import EVENT_WORKER, MACRO_WORKER, fresh

CONTRACT = "RIZAN_PRE_NEWS_SNAPSHOT_V1"
ROOT_URL = "https://raw.githubusercontent.com/rizanrizan93/Forex-scanner/"
BRANCH = "scanner-pre-news-snapshots"
MAX_BYTES = 256 * 1024


def _get(url, opener, timeout):
    request = Request(url, headers={"Cache-Control": "no-cache", "User-Agent": "RIZAN-Pre-News/1.0"})
    with opener(request, timeout=timeout) as response:
        raw = response.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("pre-news snapshot too large")
    return json.loads(raw)


def validate_snapshot(data, *, now):
    if data.get("contract") != CONTRACT:
        raise ValueError("pre-news snapshot contract mismatch")
    if data.get("execution_authority") is not False or data.get("execution_influence") is not False:
        raise ValueError("pre-news snapshot read-only contract mismatch")
    if not fresh(data.get("published_at"), now, 900):
        raise ValueError("pre-news publication stale or invalid")
    rows = data.get("heartbeats")
    if not isinstance(rows, list) or any(row.get("worker_name") not in {EVENT_WORKER, MACRO_WORKER} for row in rows):
        raise ValueError("pre-news worker contract mismatch")
    return data


def fetch_pre_news_snapshot(*, now=None, opener=urlopen, timeout_seconds=15):
    current = now or datetime.now(UTC)
    data = _get(ROOT_URL + BRANCH + "/runtime/pre_news_snapshot.json", opener, timeout_seconds)
    try:
        return validate_snapshot(data, now=current)
    except ValueError as exc:
        if str(exc) != "pre-news publication stale or invalid":
            raise
        # Re-read immutable latest revision when the mutable CDN lane is old.
        ref = _get("https://api.github.com/repos/rizanrizan93/Forex-scanner/git/ref/heads/" + BRANCH, opener, timeout_seconds)
        sha = str((ref.get("object") or {}).get("sha") or "")
        if len(sha) != 40 or any(c not in "0123456789abcdef" for c in sha):
            raise ValueError("pre-news reference invalid")
        return validate_snapshot(_get(ROOT_URL + sha + "/runtime/pre_news_snapshot.json", opener, timeout_seconds), now=current)

"""Read-only XAU M15 market source with verified GitHub API fallback.

Do not silently substitute the unrelated/stale reversal monitor. Validate the
original cTrader market timestamps against the current M15 interval.
"""
from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from urllib.request import Request, urlopen

from .xau_m15_macro_forecast import validate_fast_m15_snapshot

ROOT = "https://raw.githubusercontent.com/rizanrizan93/Forex-scanner/"
API = "https://api.github.com/repos/rizanrizan93/Forex-scanner/contents/"
BRANCH = "xau-m15-market-snapshots"
PATH = "runtime/xau_m15_market.json"
MAX_BYTES = 20_000


def read_json(url, *, api=False):
    headers = {"Cache-Control": "no-cache",
               "User-Agent": "RIZAN-M15-LIVE-Readonly"}
    if api:
        headers["Accept"] = "application/vnd.github+json"
    req = Request(url, headers=headers)
    with urlopen(req, timeout=5) as response:
        raw = response.read(MAX_BYTES * 2 + 1)
    if len(raw) > MAX_BYTES * 2:
        raise ValueError("XAU_M15_SOURCE_TOO_LARGE")
    parsed = json.loads(raw)
    if api:
        if parsed.get("encoding") != "base64":
            raise ValueError("XAU_M15_GITHUB_CONTENT_ENCODING_INVALID")
        content = base64.b64decode(parsed["content"], validate=False)
        if len(content) > MAX_BYTES:
            raise ValueError("XAU_M15_SNAPSHOT_TOO_LARGE")
        parsed = json.loads(content)
    if not isinstance(parsed, dict):
        raise ValueError("XAU_M15_SOURCE_NOT_AN_OBJECT")
    return parsed


def fetch_fast_m15(*, now=None):
    now = now or datetime.now(UTC)
    slot = int(now.timestamp() // 20)
    try:
        primary = read_json(ROOT + BRANCH + "/" + PATH + "?slot=" + str(slot))
        return validate_fast_m15_snapshot(primary, now=now)
    except (OSError, ValueError, KeyError, TypeError):
        # GitHub raw CDN may lag the snapshot branch despite a new commit.
        # Use the GitHub Contents API independently before reporting WAIT_DATA.
        pass
    try:
        fallback = read_json(API + PATH + "?ref=" + BRANCH, api=True)
        return validate_fast_m15_snapshot(fallback, now=now)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ValueError("XAU_M15_BROKER_FEED_UNAVAILABLE_OR_STALE") from exc

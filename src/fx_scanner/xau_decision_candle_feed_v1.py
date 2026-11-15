"""Strict independent public GitHub transport for XAU CLOSED H1/M15/M5 cTrader bars.

The snapshot producer uses a separate read-only market-data cTrader session.
This module has no access to positions, orders, broker credentials or bridge.
"""
from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from urllib.request import Request, urlopen

from .xau_decision_checklist_v1 import CANDLE_CONTRACT, REQUIRED_BARS, closed_bars, stamp

REPOSITORY = "rizanrizan93/Forex-scanner"
BRANCH = "xau-decision-candles-snapshots"
PATH = "runtime/xau_decision_candles.json"
ROOT = "https://raw.githubusercontent.com/" + REPOSITORY + "/"
CONTENTS = "https://api.github.com/repos/" + REPOSITORY + "/contents/"
MAX_PAYLOAD_BYTES = 196608
MAX_SNAPSHOT_AGE_SECONDS = 750


def validate_candle_snapshot(payload, *, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    if now.tzinfo is None:
        raise ValueError("NOW_MUST_BE_TIMEZONE_AWARE")
    if not isinstance(payload, dict) or payload.get("contract") != CANDLE_CONTRACT:
        raise ValueError("XAU_DECISION_CONTRACT_INVALID")
    at = stamp(payload.get("as_of"))
    if at is None or not 0 <= (now - at).total_seconds() <= MAX_SNAPSHOT_AGE_SECONDS:
        raise ValueError("XAU_DECISION_SNAPSHOT_STALE")
    for tf in REQUIRED_BARS:
        rows, reason = closed_bars(payload, tf, now)
        if reason or len(rows) < REQUIRED_BARS[tf]:
            raise ValueError("XAU_DECISION_" + tf + "_CANDLES_INVALID:" + str(reason))
    return payload


def _read(url: str, *, opener, timeout: float, api: bool) -> dict:
    req = Request(url, headers={
        "User-Agent": "RIZAN-XAU-Decision-ReadOnly/1",
        "Cache-Control": "no-cache",
        "Accept": "application/vnd.github+json" if api else "application/json",
    })
    with opener(req, timeout=timeout) as response:
        raw = response.read(MAX_PAYLOAD_BYTES * 2 + 1)
    if len(raw) > MAX_PAYLOAD_BYTES * 2:
        raise ValueError("XAU_DECISION_PAYLOAD_TOO_LARGE")
    obj = json.loads(raw)
    if api:
        if obj.get("encoding") != "base64":
            raise ValueError("XAU_DECISION_GITHUB_ENCODING_INVALID")
        data = base64.b64decode(obj["content"])
        if len(data) > MAX_PAYLOAD_BYTES:
            raise ValueError("XAU_DECISION_PAYLOAD_TOO_LARGE")
        obj = json.loads(data)
    if not isinstance(obj, dict):
        raise ValueError("XAU_DECISION_PAYLOAD_NOT_OBJECT")
    return obj


def fetch_decision_candles(*, now: datetime | None = None, opener=urlopen,
                           timeout_seconds: float = 6.) -> dict:
    now = now or datetime.now(UTC)
    try:
        source = _read(
            ROOT + BRANCH + "/" + PATH + "?slot=" +
            str(int(now.timestamp() // 60)),
            opener=opener, timeout=timeout_seconds, api=False,
        )
        return validate_candle_snapshot(source, now=now)
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        pass
    try:
        source = _read(
            CONTENTS + PATH + "?ref=" + BRANCH,
            opener=opener, timeout=timeout_seconds, api=True,
        )
        return validate_candle_snapshot(source, now=now)
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        raise ValueError("XAU_DECISION_CLOSED_CANDLE_FEED_STALE_OR_UNAVAILABLE") from exc

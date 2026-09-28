from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Callable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

CONTRACT = "XAU_RIZAN_STANDALONE_V253"
DEFAULT_SNAPSHOT_URL = (
    "https://raw.githubusercontent.com/rizanrizan93/Forex-scanner/"
    "runtime-snapshots/runtime/xau_standalone_snapshot.json"
)


def _cache_busted_url(url: str, *, now: datetime | None = None) -> str:
    current = (now or datetime.now(tz=UTC)).astimezone(UTC)
    bucket = int(current.timestamp() // 30)
    parts = urlsplit(str(url))
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["_rizan"] = str(bucket)
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)
    )


def _timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def validate_snapshot(
    payload: dict[str, Any],
    *,
    now: datetime | None = None,
    fresh_seconds: float = 180.0,
) -> dict[str, Any]:
    data = dict(payload or {})
    if str(data.get("contract") or "") != CONTRACT:
        raise ValueError("standalone snapshot contract mismatch")
    safety = dict(data.get("safety") or {})
    if not bool(safety.get("manual_analysis_only")):
        raise ValueError("standalone snapshot safety contract missing")
    if bool(safety.get("execution_authority")):
        raise ValueError("standalone snapshot must not have execution authority")
    observed = _timestamp(data.get("as_of"))
    current = (now or datetime.now(tz=UTC)).astimezone(UTC)
    age = None if observed is None else max(0.0, (current - observed).total_seconds())
    data["bridge"] = {
        "source": "GITHUB_RUNTIME_SNAPSHOT",
        "observed_at": None if observed is None else observed.isoformat(),
        "age_seconds": age,
        "fresh": bool(age is not None and age <= float(fresh_seconds)),
        "fresh_seconds": float(fresh_seconds),
    }
    return data


def fetch_snapshot(
    url: str = DEFAULT_SNAPSHOT_URL,
    *,
    timeout_seconds: float = 8.0,
    now: datetime | None = None,
    opener: Callable[..., Any] = urlopen,
) -> dict[str, Any]:
    request = Request(
        _cache_busted_url(str(url), now=now),
        headers={
            "Accept": "application/json",
            "User-Agent": "RIZAN-XAU-Scanner/1.0",
            "Cache-Control": "no-cache",
        },
    )
    with opener(request, timeout=float(timeout_seconds)) as response:
        raw = response.read()
    payload = json.loads(raw.decode("utf-8"))
    return validate_snapshot(payload, now=now)

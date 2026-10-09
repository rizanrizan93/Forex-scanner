"""Resolve stale mutable publications without changing engine timestamps."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Callable
from urllib.request import urlopen

from .xau_dashboard_bridge_v254 import DEFAULT_SNAPSHOT_URL, fetch_snapshot
from .xau_turso_hot_snapshot_v407 import _latest_snapshot_commit

EURUSD_WORKER = "ctrader_demo_eurusd_frozen_dd37"


def worker_age(payload: dict[str, Any], worker: str, now: datetime) -> float | None:
    timestamps = []
    for row in (payload.get("backend") or {}).get("heartbeats") or []:
        if row.get("worker_name") != worker:
            continue
        try:
            observed = datetime.fromisoformat(str(row.get("observed_at")).replace("Z", "+00:00"))
            if observed.tzinfo is not None:
                timestamps.append(observed.astimezone(UTC))
        except (TypeError, ValueError):
            pass
    return None if not timestamps else max(0.0, (now - max(timestamps)).total_seconds())


def fetch_eurusd_snapshot(
    *, now: datetime | None = None, opener: Callable[..., Any] = urlopen,
    timeout_seconds: float = 20.0,
) -> dict[str, Any]:
    current = (now or datetime.now(UTC)).astimezone(UTC)
    original = None
    try:
        original = fetch_snapshot(DEFAULT_SNAPSHOT_URL, now=current, opener=opener,
                                  timeout_seconds=timeout_seconds, require_fresh=False)
        age = worker_age(original, EURUSD_WORKER, current)
        if (original["bridge"]["fresh"] and original["bridge"]["age_seconds"] <= 60
                and age is not None and age <= 180):
            return original
    except Exception:
        # Try the exact latest published commit if the mutable URL is unavailable.
        pass
    try:
        sha = _latest_snapshot_commit(int(current.timestamp() // 90), opener, timeout_seconds)
        url = "https://raw.githubusercontent.com/rizanrizan93/Forex-scanner/" + sha + "/runtime/xau_dashboard_snapshot.json"
        latest = fetch_snapshot(url, now=current, opener=opener,
                                timeout_seconds=timeout_seconds, require_fresh=False)
        latest["bridge"]["resolved_commit"] = sha
        # Prefer the newer publication, even if the worker itself is still stale.
        if original is None or (latest["bridge"]["age_seconds"] is not None and
                                (original["bridge"]["age_seconds"] is None or
                                 latest["bridge"]["age_seconds"] <= original["bridge"]["age_seconds"])):
            return latest
    except Exception as exc:
        if original is None:
            raise
        original["bridge"]["latest_read_error"] = type(exc).__name__
    return original

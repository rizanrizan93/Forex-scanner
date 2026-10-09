"""Canonical read-only Turso transport for every XAU dashboard page."""
from __future__ import annotations
from datetime import UTC, datetime
from functools import lru_cache
import json
import re
from typing import Any, Callable
from urllib.request import Request, urlopen
from .xau_public_hot_v362 import CONTRACT, validate_public_hot_snapshot


@lru_cache(maxsize=4)
def _latest_snapshot_commit(bucket: int, opener: Callable[..., Any], timeout: float) -> str:
    """Resolve only on stale CDN reads, at most once per 90s per process."""
    request = Request(
        "https://api.github.com/repos/rizanrizan93/Forex-scanner/git/ref/heads/dashboard-snapshots-v344",
        headers={"Accept": "application/vnd.github+json", "Cache-Control": "no-cache",
                 "User-Agent": "RIZAN-Turso-Dashboard/1.0"},
    )
    with opener(request, timeout=timeout) as response:
        raw = response.read()
    if len(raw) > 65536:
        raise ValueError("snapshot reference response too large")
    sha = str(dict(json.loads(raw).get("object") or {}).get("sha") or "")
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("invalid snapshot commit reference")
    return sha

def fetch_public_hot_snapshot(
    url: str | None = None,
    *,
    timeout_seconds: float = 20.0,
    now: datetime | None = None,
    opener: Callable[..., Any] = urlopen,
) -> dict[str, Any]:
    """Read the sanitized Turso bridge; dashboard readers need no DB credentials.

    Never fall back to the retired Supabase RPC. A fresh publication does not
    make an old primary-engine heartbeat fresh.
    """
    from .xau_dashboard_bridge_v254 import DEFAULT_SNAPSHOT_URL, fetch_snapshot

    try:
        bridge = fetch_snapshot(
            url or DEFAULT_SNAPSHOT_URL, timeout_seconds=timeout_seconds,
            now=now, opener=opener, require_fresh=True,
            resolve_stale=False,
        )
        return _project_turso_snapshot(bridge, now=now)
    except ValueError as exc:
        stale_errors = {
            "dashboard bridge snapshot stale",
            "Turso primary XAU engine heartbeat stale or missing",
        }
        if url is not None or str(exc) not in stale_errors:
            raise
        # The mutable URL may cache either an old publication or old engine rows.
        current = now or datetime.now(UTC)
        sha = _latest_snapshot_commit(int(current.timestamp() // 90), opener, float(timeout_seconds))
        immutable_url = (
            "https://raw.githubusercontent.com/rizanrizan93/Forex-scanner/"
            + sha + "/runtime/xau_dashboard_snapshot.json"
        )
        bridge = fetch_snapshot(immutable_url, timeout_seconds=timeout_seconds,
                                now=now, opener=opener, require_fresh=True)
        return _project_turso_snapshot(bridge, now=now)


def _project_turso_snapshot(bridge: dict[str, Any], *, now: datetime | None) -> dict[str, Any]:
    if dict(bridge.get("source") or {}).get("database_backend") != "turso":
        raise ValueError("dashboard snapshot is not from Turso")
    backend = dict(bridge.get("backend") or {})
    rows = list(backend.get("heartbeats") or [])
    by_worker = {row.get("worker_name"): row for row in rows}
    primary = by_worker.get("ctrader_demo_xau_sd_liquidity_v342", {})
    executor = by_worker.get("ctrader_demo_xau_v351_executor", {})
    out = validate_public_hot_snapshot({
        "contract": CONTRACT,
        "primary_observed_at": primary.get("observed_at"),
        "executor_observed_at": executor.get("observed_at"),
        "heartbeats": rows,
        "control": backend.get("control") or {},
    }, now=now)
    out["hot_transport"].update({
        "source": "TURSO_DASHBOARD_BRIDGE",
        "database_backend": "turso",
        "published_at": bridge.get("as_of"),
        "publication_age_seconds": bridge["bridge"].get("age_seconds"),
    })
    if not out["hot_transport"]["fresh"]:
        raise ValueError("Turso primary XAU engine heartbeat stale or missing")
    if not primary.get("healthy"):
        raise ValueError("Turso primary XAU engine heartbeat unhealthy")
    return out

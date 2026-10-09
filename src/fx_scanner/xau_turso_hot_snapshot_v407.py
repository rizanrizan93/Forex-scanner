"""Canonical read-only Turso transport for every XAU dashboard page."""
from __future__ import annotations
from datetime import datetime
from typing import Any, Callable
from urllib.request import urlopen
from .xau_public_hot_v362 import CONTRACT, validate_public_hot_snapshot

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

    bridge = fetch_snapshot(
        url or DEFAULT_SNAPSHOT_URL,
        timeout_seconds=timeout_seconds,
        now=now,
        opener=opener,
        require_fresh=True,
    )
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

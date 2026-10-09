from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Callable
from urllib.request import Request, urlopen

CONTRACT = "XAU_RIZAN_PUBLIC_HOT_V362"
PROJECT_REF = "naxvdtvlfatljzzwhrmo"
DEFAULT_RPC_URL = (
    f"https://{PROJECT_REF}.supabase.co/rest/v1/rpc/get_xau_dashboard_hot_v362"
)
# Supabase publishable keys are intentionally safe for client-side distribution.
# This key can be rotated independently from all server-side/service-role secrets.
DEFAULT_PUBLISHABLE_KEY = "sb_publishable_Wc4eAjiNfsbXyeDLSuT8Xw_kZmG9mPz"
FRESH_SECONDS = 150.0


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


def validate_public_hot_snapshot(
    payload: dict[str, Any],
    *,
    now: datetime | None = None,
    fresh_seconds: float = FRESH_SECONDS,
) -> dict[str, Any]:
    data = dict(payload or {})
    if str(data.get("contract") or "") != CONTRACT:
        raise ValueError("public hot snapshot contract mismatch")
    rows = list(data.get("heartbeats") or [])
    if not rows:
        raise ValueError("public hot snapshot has no heartbeats")

    observed = _timestamp(data.get("primary_observed_at"))
    current = (now or datetime.now(tz=UTC)).astimezone(UTC)
    age = None if observed is None else max(
        0.0, (current - observed).total_seconds()
    )
    fresh = bool(age is not None and age <= float(fresh_seconds))
    data["hot_transport"] = {
        "source": "SUPABASE_PUBLIC_RPC",
        "observed_at": None if observed is None else observed.isoformat(),
        "age_seconds": age,
        "fresh_seconds": float(fresh_seconds),
        "fresh": fresh,
    }
    return data


def fetch_supabase_public_hot_snapshot(
    url: str = DEFAULT_RPC_URL,
    *,
    publishable_key: str = DEFAULT_PUBLISHABLE_KEY,
    timeout_seconds: float = 10.0,
    now: datetime | None = None,
    opener: Callable[..., Any] = urlopen,
) -> dict[str, Any]:
    request = Request(
        str(url),
        data=b"{}",
        method="POST",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "apikey": str(publishable_key),
            "Cache-Control": "no-cache",
            "User-Agent": "RIZAN-XAU-Public-Hot/1.0",
        },
    )
    with opener(request, timeout=float(timeout_seconds)) as response:
        raw = response.read()
    payload = json.loads(raw.decode("utf-8"))
    # Defensive compatibility if a PostgREST proxy wraps the scalar JSON result.
    if isinstance(payload, list):
        if len(payload) != 1 or not isinstance(payload[0], dict):
            raise ValueError("unexpected public hot RPC response")
        payload = payload[0]
    if not isinstance(payload, dict):
        raise ValueError("public hot RPC response is not an object")
    return validate_public_hot_snapshot(payload, now=now)



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

def overlay_public_hot_backend(
    backend: dict[str, Any] | None,
    hot: dict[str, Any],
) -> dict[str, Any]:
    out = dict(backend or {})
    by_worker: dict[str, dict[str, Any]] = {}
    for raw in list(out.get("heartbeats") or []):
        row = dict(raw or {})
        worker = str(row.get("worker_name") or "")
        if worker:
            by_worker[worker] = row
    for raw in list(hot.get("heartbeats") or []):
        row = dict(raw or {})
        worker = str(row.get("worker_name") or "")
        if worker:
            by_worker[worker] = row
    out["heartbeats"] = sorted(
        by_worker.values(),
        key=lambda row: str(row.get("observed_at") or ""),
        reverse=True,
    )
    control = dict(hot.get("control") or {})
    if control:
        out["control"] = control
    return out

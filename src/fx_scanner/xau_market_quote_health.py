"""Vendor timestamp health for read-only XAU macro panels."""
from __future__ import annotations
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo
QUOTE_MAX_AGE_SECONDS = 300

def _parse(value: Any):
    try:
        d = datetime.fromisoformat(str(value).replace("Z","+00:00"))
        return d.replace(tzinfo=UTC) if d.tzinfo is None else d.astimezone(UTC)
    except (ValueError, TypeError):
        return None

def quote_freshness(data: dict[str, Any] | None, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    if now.tzinfo is None:
        raise ValueError("now must have timezone")
    now = now.astimezone(UTC)
    row = data or {}
    at = _parse(row.get("observed"))
    source = str(row.get("source") or "")
    if at is None:
        return {"status":"UNAVAILABLE","age_minutes":None,"observed_wib":None,"eligible":False}
    age = (now-at).total_seconds()
    if age < 0:
        status = "INVALID_TIMESTAMP"
    elif source.startswith("FRED"):
        status = "HARIAN — BUKAN LIVE"
    elif row.get("fresh") is True and age <= QUOTE_MAX_AGE_SECONDS:
        status = "FRESH ≤5m"
    else:
        status = "DELAYED"
    return {"status":status,"age_minutes":round(age/60,1) if age >=0 else None,
            "observed_wib":at.astimezone(ZoneInfo("Asia/Jakarta")).strftime("%d/%m %H:%M:%S"),
            "eligible":status=="FRESH ≤5m"}

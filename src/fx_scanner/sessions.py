from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

from .models import ensure_utc


def _parse_hhmm(value: str) -> time:
    h, m = value.split(":")
    return time(int(h), int(m))


def active_sessions(ts: datetime, session_config: dict) -> tuple[str, ...]:
    ts_utc = ensure_utc(ts)
    active: list[str] = []
    for name, cfg in session_config["sessions"].items():
        zone = ZoneInfo(cfg["timezone"])
        local = ts_utc.astimezone(zone)
        start = _parse_hhmm(cfg["start"])
        end = _parse_hhmm(cfg["end"])
        local_t = local.timetz().replace(tzinfo=None)
        if start <= end:
            is_active = start <= local_t < end
        else:
            is_active = local_t >= start or local_t < end
        if is_active:
            active.append(name)
    return tuple(active)


def session_label(ts: datetime, session_config: dict) -> str:
    active = active_sessions(ts, session_config)
    if "LONDON" in active and "NEW_YORK" in active:
        return "LONDON_NY_OVERLAP"
    if active:
        return "+".join(active)
    return "OFF_SESSION"

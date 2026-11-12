"""Select the latest *published* official H.15 / FRED Treasury observations.

Both are distribution channels for the same Federal Reserve H.15 series.
A fresh worker timestamp or provider TTL is not an observation date.
Selection is read-only; no intraday market proxy is ever written as H.15.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from math import isfinite
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from .xau_treasury_schedule import is_treasury_session_day

OFFICIAL_YIELD_KEYS = ("US2Y", "US10Y", "REAL_YIELD_10Y")
H15_RELEASE_ET = time(16, 15)
H15_INGEST_GRACE = timedelta(hours=2)
NY = ZoneInfo("America/New_York")


def _dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo else None
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.astimezone(UTC) if parsed.tzinfo else None
    except (TypeError, ValueError, OverflowError):
        return None


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        num = float(value)
        return num if isfinite(num) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _row_usable(row: Mapping[str, Any] | None, now: datetime) -> bool:
    item = dict(row or {})
    observation = _dt(item.get("observed_at"))
    previous = _dt(item.get("previous_observed_at"))
    return bool(
        observation and previous and previous < observation <= now
        and _number(item.get("current")) is not None
        and _number(item.get("previous")) is not None
        and _number(item.get("delta")) is not None
        and str(item.get("freshness") or "").upper() == "FRESH"
    )


def _expected_h15_date(now: datetime) -> tuple[date, datetime]:
    """Last scheduled release boundary, not proof an observation is published."""
    local = now.astimezone(NY)
    candidate = local.date()
    release_at = datetime.combine(candidate, H15_RELEASE_ET, tzinfo=NY)
    if not is_treasury_session_day(candidate) or local < release_at:
        candidate -= timedelta(days=1)
    for _ in range(12):
        if is_treasury_session_day(candidate):
            break
        candidate -= timedelta(days=1)
    last_release_at = datetime.combine(candidate, H15_RELEASE_ET, tzinfo=NY)
    return candidate, last_release_at.astimezone(UTC)


def _release_state(observed: datetime | None, now: datetime) -> tuple[str, str]:
    expected, released_at = _expected_h15_date(now)
    if observed is None:
        return "OFFICIAL_DATA_MISSING", expected.isoformat()
    if observed.astimezone(UTC).date() >= expected:
        return "CURRENT_PUBLISHED", expected.isoformat()
    if now - released_at <= H15_INGEST_GRACE:
        return "RELEASE_PENDING", expected.isoformat()
    return "DAILY_DELAYED", expected.isoformat()


def select_official_yield_rows(
    fred_rows: Mapping[str, Mapping[str, Any]],
    h15_rows: Mapping[str, Mapping[str, Any]] | None,
    *,
    now: datetime,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """Prefer the newer official observation; tie -> FRED.

    No downgrade to older H.15 and no assumption that a release happened.
    Delayed-but-still-within-FRED-TTL rows remain usable as *daily regime*,
    with an explicit release-state label so they cannot masquerade as live.
    """
    if now.tzinfo is None:
        raise ValueError("now must be timezone aware")
    primary = dict(fred_rows or {})
    alternative = dict(h15_rows or {})
    selected = {key: dict(value or {}) for key, value in primary.items()}
    diagnostics: dict[str, Any] = {
        "chosen_providers": {}, "fallback_used": [],
        "release_states": {}, "expected_observation_dates": {},
        "h15_observed_dates": {}, "fred_observed_dates": {},
    }
    for name in OFFICIAL_YIELD_KEYS:
        fred = dict(primary.get(name) or {})
        h15 = dict(alternative.get(name) or {})
        fdt = _dt(fred.get("observed_at"))
        hdt = _dt(h15.get("observed_at"))
        f_ok = _row_usable(fred, now)
        h_ok = _row_usable(h15, now)
        # Only a valid official observation may replace existing data.
        # FRED is preferred at identical dates to avoid provider oscillation.
        if h_ok and (not f_ok or fdt is None or hdt > fdt):
            chosen = dict(h15)
            diagnostics["fallback_used"].append(name)
        else:
            chosen = dict(fred)
        observed = _dt(chosen.get("observed_at"))
        state, expected = _release_state(observed, now)
        chosen["release_state"] = state
        chosen["expected_observation_date"] = expected
        chosen["observation_freshness"] = (
            "RELEASE_CURRENT" if state == "CURRENT_PUBLISHED"
            else "RELEASE_PENDING" if state == "RELEASE_PENDING"
            else "DAILY_DELAYED"
        )
        # A provider cache TTL is not evidence that the daily observation is current.
        # Preserve it separately, and expose observation-aware freshness to consumers.
        chosen["provider_cache_freshness"] = chosen.get("freshness")
        if state != "CURRENT_PUBLISHED":
            chosen["freshness"] = "STALE"
            chosen["provider_status"] = state
        selected[name] = chosen
        diagnostics["chosen_providers"][name] = chosen.get("provider")
        diagnostics["release_states"][name] = state
        diagnostics["expected_observation_dates"][name] = expected
        diagnostics["h15_observed_dates"][name] = hdt.date().isoformat() if hdt else None
        diagnostics["fred_observed_dates"][name] = fdt.date().isoformat() if fdt else None
    return selected, diagnostics

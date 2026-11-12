"""Select newest published US Treasury / H.15 / FRED daily yield observations.

Official sources are daily observations, never intraday quotations.
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
    current_value = _number(item.get("current"))
    prior_value = _number(item.get("previous"))
    delta = _number(item.get("delta"))
    if not (observation and previous and previous < observation <= now):
        return False
    if current_value is None or prior_value is None or delta is None:
        return False
    if not (-10 < current_value < 30 and -10 < prior_value < 30):
        return False
    return bool(
        str(item.get("freshness") or "").upper() == "FRESH"
        and str(item.get("delta_unit") or "BPS").upper() == "BPS"
        and abs(delta - (current_value - prior_value) * 100.0) <= 0.05
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
    treasury_rows: Mapping[str, Mapping[str, Any]] | None = None,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """Select newest valid OFFICIAL daily observation, Treasury wins equal-date ties.

    A valid newer FRED/H.15 value can supersede an older Treasury publication.
    When a source is delayed, never relabel its fetch/heartbeat as a new release.
    All results remain read-only and cannot authorize broker execution.
    """
    if now.tzinfo is None:
        raise ValueError("now must be timezone aware")
    primary = dict(fred_rows or {})
    federal = dict(h15_rows or {})
    treasury = dict(treasury_rows or {})
    selected = {key: dict(value or {}) for key, value in primary.items()}
    diagnostics: dict[str, Any] = {
        "chosen_providers": {}, "fallback_used": [],
        "treasury_primary_used": [], "h15_fallback_used": [],
        "release_states": {}, "expected_observation_dates": {},
        "treasury_observed_dates": {}, "h15_observed_dates": {},
        "fred_observed_dates": {},
    }
    for name in OFFICIAL_YIELD_KEYS:
        fred = dict(primary.get(name) or {})
        h15 = dict(federal.get(name) or {})
        direct = dict(treasury.get(name) or {})
        candidates = [
            (_dt(row.get("observed_at")), priority, row, label)
            for priority, row, label in (
                (2, fred, "FRED"),
                (1, h15, "H15"),
                (3, direct, "TREASURY"),
            )
            if _row_usable(row, now)
        ]
        # Source rank breaks ONLY same-observation-date ties.
        if candidates:
            _, _, chosen, provider_label = max(candidates, key=lambda x: (x[0], x[1]))
            chosen = dict(chosen)
        else:
            chosen, provider_label = dict(fred), "FRED"
        observed = _dt(chosen.get("observed_at"))
        state, expected = _release_state(observed, now)
        chosen["release_state"] = state
        chosen["expected_observation_date"] = expected
        chosen["observation_freshness"] = (
            "RELEASE_CURRENT" if state == "CURRENT_PUBLISHED"
            else "RELEASE_PENDING" if state == "RELEASE_PENDING"
            else "DAILY_DELAYED"
        )
        chosen["provider_cache_freshness"] = chosen.get("freshness")
        if state != "CURRENT_PUBLISHED":
            chosen["freshness"] = "STALE"
            chosen["provider_status"] = state
        selected[name] = chosen
        if provider_label != "FRED":
            diagnostics["fallback_used"].append(name)
        if provider_label == "TREASURY":
            diagnostics["treasury_primary_used"].append(name)
        if provider_label == "H15":
            diagnostics["h15_fallback_used"].append(name)
        diagnostics["chosen_providers"][name] = chosen.get("provider")
        diagnostics["release_states"][name] = state
        diagnostics["expected_observation_dates"][name] = expected
        diagnostics["treasury_observed_dates"][name] = (
            _dt(direct.get("observed_at")).date().isoformat()
            if _dt(direct.get("observed_at")) else None
        )
        diagnostics["h15_observed_dates"][name] = (
            _dt(h15.get("observed_at")).date().isoformat()
            if _dt(h15.get("observed_at")) else None
        )
        diagnostics["fred_observed_dates"][name] = (
            _dt(fred.get("observed_at")).date().isoformat()
            if _dt(fred.get("observed_at")) else None
        )
    return selected, diagnostics

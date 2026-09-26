"""Pure validation for an immutable, already-created DEMO depth parent."""
from __future__ import annotations

from datetime import UTC, datetime
from math import isfinite
from typing import Any, Iterator

ALLOWED_ENTRY_SOURCES = frozenset({"H1_NESTED_LOCATOR", "M15_NESTED_LOCATOR"})
MAX_ATLAS_AGE_SECONDS = 600


def _dt(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo is not None else None


def _f(value: Any) -> float | None:
    try:
        result = float(value)
    except (ValueError, TypeError):
        return None
    return result if isfinite(result) else None


def _zones(value: Any) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        if value.get("zone_id") and "low" in value and "high" in value:
            yield value
        for child in value.values():
            if isinstance(child, (dict, list)):
                yield from _zones(child)
    elif isinstance(value, list):
        for child in value:
            yield from _zones(child)


def atlas_reason(heartbeat: dict[str, Any], *, now: datetime) -> str | None:
    observed = _dt(heartbeat.get("observed_at"))
    if not heartbeat.get("healthy") or observed is None:
        return "ATLAS_UNHEALTHY_OR_UNTIMED"
    age = (now - observed).total_seconds()
    if age < -1 or age > MAX_ATLAS_AGE_SECONDS:
        return "ATLAS_STALE_OR_FUTURE"
    return None


def parent_status(
    plan: dict[str, Any], signal: dict[str, Any], atlas: dict[str, Any],
    *, now: datetime, live_price: float,
) -> tuple[str, str]:
    """Return ACTIVE, WAIT (unknown evidence), or CANCEL (known invalidation).

    First-touch freshness is a creation condition. Continuation uses the frozen
    H4 identity and geometry even when V226 selects a different fresh candidate.
    """
    state = str(signal.get("state") or "").upper()
    expiry = _dt(signal.get("expires_at"))
    if state not in {"EXECUTION_READY", "COOLDOWN"}:
        return "CANCEL", "PARENT_STATE_INVALID"
    if expiry is None:
        return "WAIT", "PARENT_EXPIRY_UNKNOWN"
    if now >= expiry:
        return "CANCEL", "PARENT_EXPIRED"
    if plan.get("source_layer") not in ALLOWED_ENTRY_SOURCES:
        return "CANCEL", "H4_ONLY_WATCH_COHORT"
    side = str(plan.get("direction") or "")
    stop, price = _f(plan.get("sl")), _f(live_price)
    if side not in {"LONG", "SHORT"} or stop is None or price is None:
        return "WAIT", "PARENT_GEOMETRY_UNKNOWN"
    if (side == "LONG" and price <= stop) or (side == "SHORT" and price >= stop):
        return "CANCEL", "PARENT_STOP_BREACHED"
    zone_id = str(plan.get("h4_zone_id") or "")
    matches = [z for z in _zones(atlas) if zone_id and str(z.get("zone_id")) == zone_id]
    if not matches:
        # Atlas is a bounded display selection. Absence alone is not a break.
        return "WAIT", "PARENT_ZONE_NOT_IN_CURRENT_ATLAS"
    for zone in matches:
        lifecycle = dict(zone.get("lifecycle") or {})
        status = str(zone.get("status") or "").upper()
        if lifecycle.get("active") is False or "BROKEN" in status or "INVALID" in status:
            return "CANCEL", "PARENT_ZONE_INVALIDATED"
    zone = matches[0]
    if dict(zone.get("lifecycle") or {}).get("active") is not True:
        return "WAIT", "PARENT_LIFECYCLE_UNKNOWN"
    if str(zone.get("direction") or "") != side or str(zone.get("timeframe") or "") != "H4":
        return "CANCEL", "PARENT_ZONE_IDENTITY_MISMATCH"
    frozen = dict(plan.get("h4_zone_snapshot") or {})
    for key in ("low", "high"):
        value, original = _f(zone.get(key)), _f(frozen.get(key))
        if value is None or original is None or abs(value - original) > 1e-8:
            return "WAIT", "PARENT_FROZEN_GEOMETRY_UNVERIFIED"
    return "ACTIVE", "FROZEN_PARENT_VALID"


def pretouch_allowed(plan: dict[str, Any], atlas: dict[str, Any]) -> bool:
    matches = [z for z in _zones(atlas) if str(z.get("zone_id") or "") == str(plan.get("h4_zone_id") or "")]
    if not matches:
        return False
    # Do not submit previously unsent L1/L2 after first touch. Existing pending
    # L1/L2 remain owned by the parent and are cancelled only on invalidation.
    return all(
        dict(z.get("lifecycle") or {}).get("active") is True
        and dict(z.get("lifecycle") or {}).get("touch_count") == 0
        and dict(z.get("lifecycle") or {}).get("freshness") == "FRESH"
        for z in matches
    )


def micro_reason(
    plan: dict[str, Any], micro: dict[str, Any], *, slot: int,
    parent_at: datetime, evaluation_at: datetime,
) -> str | None:
    """Bind confirmation to this parent's H1 source and post-capture sweep."""
    state = str(micro.get("state") or "")
    allowed = {"M5_MSS_WAIT_DISPLACEMENT", "M5_REFINEMENT_CONFIRMED_SHADOW"}
    if state not in allowed or (slot == 4 and state != "M5_REFINEMENT_CONFIRMED_SHADOW"):
        return "M5_SOURCE_NOT_VALID_FOR_SLOT"
    source = dict(plan.get("precision_source_snapshot") or {})
    if (
        not source.get("zone_id")
        or str(micro.get("source_zone_id") or "") != str(source["zone_id"])
        or str(micro.get("source_timeframe") or "") != "H1"
        or str(micro.get("direction") or "") != str(plan.get("direction") or "")
    ):
        return "M5_PARENT_SOURCE_MISMATCH"
    source_at = _dt(source.get("available_at"))
    micro_source_at = _dt(micro.get("source_available_at"))
    sweep_at = _dt(dict(micro.get("sweep") or {}).get("at"))
    if source_at is None or micro_source_at != source_at or source_at > parent_at:
        return "M5_SOURCE_AVAILABILITY_MISMATCH"
    if sweep_at is None or not parent_at <= sweep_at <= evaluation_at:
        return "M5_SWEEP_OUTSIDE_PARENT_EPISODE"
    for key in ("reclaim_at", "mss_at") + (("displacement_at",) if slot == 4 else ()):
        confirmation_at = _dt(micro.get(key))
        if confirmation_at is None or not sweep_at <= confirmation_at <= evaluation_at:
            return "M5_CONFIRMATION_UNTIMED_OR_OUTSIDE_EPISODE"
    pocket = dict(micro.get("refined_entry_pocket" if slot == 4 else "candidate_entry_pocket") or {})
    low, high = _f(pocket.get("low")), _f(pocket.get("high"))
    stop = _f(plan.get("sl"))
    if None in {low, high, stop}:
        return "M5_POCKET_GEOMETRY_UNKNOWN"
    if not 0 < low < high:
        return "M5_POCKET_GEOMETRY_INVALID"
    entry = high if plan.get("direction") == "LONG" else low
    if (plan.get("direction") == "LONG" and entry <= stop) or (plan.get("direction") == "SHORT" and entry >= stop):
        return "M5_ENTRY_BEYOND_PARENT_STOP"
    return None

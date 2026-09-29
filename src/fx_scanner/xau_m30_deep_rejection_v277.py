from __future__ import annotations

from datetime import datetime, timedelta
from math import isfinite
from typing import Any, Sequence

from .models import Bar, ensure_utc

CONTRACT = "XAU_M30_DEEP_REJECTION_V277"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_AUTHORITY = False

DEEP_TOUCH_MIN_DEPTH = 0.60
REJECTION_CONFIRM_MAX_DEPTH = 0.55
MIN_REJECTION_RETREAT = 0.20
LOOKBACK_M5_BARS = 48


def _f(value: Any) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _completed_m5(
    bars: Sequence[Bar],
    *,
    as_of: datetime,
) -> tuple[Bar, ...]:
    now = ensure_utc(as_of)
    return tuple(
        row
        for row in sorted(tuple(bars), key=lambda x: ensure_utc(x.timestamp))
        if ensure_utc(row.timestamp) + timedelta(minutes=5) <= now
    )


def _depth_from_price(
    *,
    direction: str,
    low: float,
    high: float,
    price: float,
) -> float:
    width = max(float(high) - float(low), 1e-12)
    side = str(direction or "").upper()
    if side == "SHORT":
        return (float(price) - float(low)) / width
    if side == "LONG":
        return (float(high) - float(price)) / width
    raise ValueError("V277_DIRECTION_INVALID")


def _bar_penetration_depth(
    *,
    direction: str,
    low: float,
    high: float,
    bar: Bar,
) -> float:
    side = str(direction or "").upper()
    probe = float(bar.high) if side == "SHORT" else float(bar.low)
    return _depth_from_price(
        direction=side,
        low=low,
        high=high,
        price=probe,
    )


def _bar_close_depth(
    *,
    direction: str,
    low: float,
    high: float,
    bar: Bar,
) -> float:
    return _depth_from_price(
        direction=direction,
        low=low,
        high=high,
        price=float(bar.close),
    )


def _zone_invalidated(
    *,
    direction: str,
    low: float,
    high: float,
    bar: Bar,
) -> bool:
    side = str(direction or "").upper()
    if side == "SHORT":
        return float(bar.close) > float(high)
    if side == "LONG":
        return float(bar.close) < float(low)
    return True


def _selected_parent(
    *,
    m30_shadow: dict[str, Any],
    direction: str,
) -> dict[str, Any]:
    side = str(direction or "").upper()
    key = "nearest_supply" if side == "SHORT" else "nearest_demand"
    zone = dict(m30_shadow.get(key) or {})
    if str(zone.get("direction") or "").upper() != side:
        return {}
    return zone


def evaluate_m30_deep_rejection_v277(
    *,
    m30_shadow: dict[str, Any],
    m5_bars: Sequence[Bar],
    direction: str,
    as_of: datetime,
) -> dict[str, Any]:
    side = str(direction or "").upper()
    if side not in {"LONG", "SHORT"}:
        return {
            "contract": CONTRACT,
            "available": False,
            "state": "NO_DIRECTION",
            "execution_authority": EXECUTION_AUTHORITY,
            "policy_effect": POLICY_EFFECT,
        }

    zone = _selected_parent(m30_shadow=m30_shadow, direction=side)
    low = _f(zone.get("low"))
    high = _f(zone.get("high"))
    available_at_raw = zone.get("available_at")
    if low is None or high is None or high <= low or not zone:
        return {
            "contract": CONTRACT,
            "available": False,
            "state": "NO_M30_PARENT_ZONE",
            "execution_authority": EXECUTION_AUTHORITY,
            "policy_effect": POLICY_EFFECT,
        }

    try:
        available_at = ensure_utc(datetime.fromisoformat(str(available_at_raw)))
    except Exception:
        available_at = None

    completed = _completed_m5(m5_bars, as_of=as_of)
    if available_at is not None:
        completed = tuple(
            row for row in completed if ensure_utc(row.timestamp) >= available_at
        )
    completed = completed[-LOOKBACK_M5_BARS:]
    if not completed:
        return {
            "contract": CONTRACT,
            "available": False,
            "state": "NO_COMPLETED_M5",
            "execution_authority": EXECUTION_AUTHORITY,
            "policy_effect": POLICY_EFFECT,
            "parent_zone": zone,
        }

    max_depth = float("-inf")
    max_depth_at: datetime | None = None
    invalidated = False
    invalidated_at: datetime | None = None
    confirmation_at: datetime | None = None
    confirmation_depth: float | None = None
    confirmation_retreat: float | None = None
    touched = False

    for row in completed:
        penetration = _bar_penetration_depth(
            direction=side,
            low=low,
            high=high,
            bar=row,
        )
        close_depth = _bar_close_depth(
            direction=side,
            low=low,
            high=high,
            bar=row,
        )
        if penetration >= 0.0:
            touched = True
        if penetration > max_depth:
            max_depth = penetration
            max_depth_at = ensure_utc(row.timestamp)
        if _zone_invalidated(
            direction=side,
            low=low,
            high=high,
            bar=row,
        ):
            invalidated = True
            invalidated_at = ensure_utc(row.timestamp)
            confirmation_at = None
            confirmation_depth = None
            confirmation_retreat = None
            break

        retreat = max_depth - close_depth
        if (
            max_depth >= DEEP_TOUCH_MIN_DEPTH
            and close_depth <= REJECTION_CONFIRM_MAX_DEPTH
            and retreat >= MIN_REJECTION_RETREAT
        ):
            confirmation_at = ensure_utc(row.timestamp)
            confirmation_depth = close_depth
            confirmation_retreat = retreat

    latest = completed[-1]
    latest_close_depth = _bar_close_depth(
        direction=side,
        low=low,
        high=high,
        bar=latest,
    )
    latest_penetration = _bar_penetration_depth(
        direction=side,
        low=low,
        high=high,
        bar=latest,
    )
    overlap = _f(zone.get("canonical_overlap_ratio"))
    overlap = 0.0 if overlap is None else max(0.0, min(1.0, overlap))

    if invalidated:
        state = "PARENT_INVALIDATED"
    elif confirmation_at is not None:
        state = "DEEP_REJECTION_CONFIRMED"
    elif max_depth >= DEEP_TOUCH_MIN_DEPTH:
        state = "DEEP_TOUCH_WAIT_REJECTION"
    elif touched:
        state = "SHALLOW_OR_MID_TOUCH"
    else:
        state = "AHEAD_OF_PARENT_ZONE"

    composite_hint = "NONE"
    if state == "DEEP_REJECTION_CONFIRMED":
        composite_hint = "WAIT_M5_RETEST_OR_STRUCTURE_CONFIRM"

    return {
        "contract": CONTRACT,
        "available": True,
        "as_of": ensure_utc(as_of).isoformat(),
        "state": state,
        "direction": side,
        "execution_authority": EXECUTION_AUTHORITY,
        "policy_effect": POLICY_EFFECT,
        "thresholds": {
            "deep_touch_min_depth": DEEP_TOUCH_MIN_DEPTH,
            "rejection_confirm_max_depth": REJECTION_CONFIRM_MAX_DEPTH,
            "minimum_retreat": MIN_REJECTION_RETREAT,
        },
        "parent_zone": {
            "zone_id": zone.get("zone_id"),
            "low": low,
            "high": high,
            "width": high - low,
            "canonical_overlap_ratio": overlap,
            "canonical_match_timeframe": zone.get("canonical_match_timeframe"),
            "canonical_match_zone_id": zone.get("canonical_match_zone_id"),
        },
        "touched": touched,
        "max_depth": None if max_depth == float("-inf") else max_depth,
        "max_depth_at": None if max_depth_at is None else max_depth_at.isoformat(),
        "latest_close_depth": latest_close_depth,
        "latest_penetration_depth": latest_penetration,
        "confirmation_at": (
            None if confirmation_at is None else confirmation_at.isoformat()
        ),
        "confirmation_depth": confirmation_depth,
        "confirmation_retreat": confirmation_retreat,
        "invalidated_at": (
            None if invalidated_at is None else invalidated_at.isoformat()
        ),
        "operational_hint": composite_hint,
        "note": (
            "Deep rejection is a location/confirmation classifier for the M30 parent zone. "
            "It does not grant order authority. Strict execution still requires the existing "
            "M15/M5 structure, pressure and RR gates."
        ),
    }

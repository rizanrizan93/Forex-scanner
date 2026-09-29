from __future__ import annotations

from math import isfinite
from typing import Any

MIN_AT_RISK = 30
NEAR_ZONE_FRACTION = 0.15

PRESSURE_MULTIPLIER = {
    "OPPOSING_REACCELERATION": 0.55,
    "OPPOSING_STILL_ACTIVE": 0.75,
    "OPPOSING_FADING_EARLY": 1.00,
    "OPPOSING_FADING": 1.12,
    "FADING_EARLY": 1.08,
    "BALANCED_ABSORPTION": 1.25,
    "CONTROL_FLIP": 1.40,
    "CONTESTED": 1.00,
}


def _f(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _source_context(
    v226_evaluation: dict[str, Any],
    direction: str,
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    side = dict(v226_evaluation.get(str(direction).lower()) or {})
    candidate = dict(v226_evaluation.get("depth_entry_candidate") or {})
    source = str(candidate.get("source_layer") or "")
    if source.startswith("M15"):
        layer = dict(side.get("m15") or {})
        return "M15", dict(layer.get("zone") or {}), dict(layer.get("standalone_profile_context") or {})
    if source.startswith("H1"):
        layer = dict(side.get("h1") or {})
        return "H1", dict(layer.get("zone") or {}), dict(layer.get("historical_profile") or {})
    layer = dict(side.get("h4") or {})
    return "H4", dict(layer.get("zone") or {}), dict(layer.get("historical_profile") or {})


def normalized_depth(zone: dict[str, Any], price: float) -> float | None:
    low = _f(zone.get("low"))
    high = _f(zone.get("high"))
    direction = str(zone.get("direction") or "").upper()
    px = _f(price)
    if low is None or high is None or px is None or high <= low:
        return None
    width = high - low
    if direction == "LONG":
        return (high - px) / width
    if direction == "SHORT":
        return (px - low) / width
    return None


def price_at_depth(zone: dict[str, Any], depth: float) -> float | None:
    low = _f(zone.get("low"))
    high = _f(zone.get("high"))
    direction = str(zone.get("direction") or "").upper()
    if low is None or high is None or high <= low:
        return None
    d = max(0.0, min(1.0, float(depth)))
    if direction == "LONG":
        return high - d * (high - low)
    if direction == "SHORT":
        return low + d * (high - low)
    return None


def build_geometry_depth_status(
    *,
    zone: dict[str, Any],
    live_price: float,
) -> dict[str, Any]:
    """Describe physical location inside a current structural zone without a hazard prior.

    This is intentionally geometry-only. It is used by the dashboard whenever
    V229/V226 calibrated depth geometry is not aligned with the current V182 path.
    No historical hazard band, execution readiness, or turning-price claim is
    inferred from this status.
    """
    if not zone:
        return {
            "state": "UNAVAILABLE",
            "reason": "NO_CURRENT_STRUCTURAL_ZONE",
            "execution_ready": False,
        }
    depth = normalized_depth(zone, live_price)
    low = _f(zone.get("low"))
    high = _f(zone.get("high"))
    direction = str(zone.get("direction") or "").upper()
    if (
        direction not in {"LONG", "SHORT"}
        or low is None
        or high is None
        or high <= low
        or depth is None
    ):
        return {
            "state": "UNAVAILABLE",
            "reason": "INVALID_CURRENT_STRUCTURAL_ZONE",
            "execution_ready": False,
        }

    lifecycle = dict(zone.get("lifecycle") or {})
    touch_count = int(lifecycle.get("touch_count") or 0)
    if depth < 0.0:
        # A previously touched zone with price back beyond its proximal edge has
        # already produced/attempted a reaction. Calling this "ahead of zone"
        # would be misleading because the market has in fact visited the zone.
        location_state = "AFTER_REACTION" if touch_count > 0 else "AHEAD_OF_ZONE"
        action = "WAIT_NEW_TRIGGER" if touch_count > 0 else "WAIT_ZONE"
    elif depth >= 1.0:
        location_state = "AT_OR_BEYOND_DISTAL"
        action = "WAIT_STRUCTURE_REMAP"
    else:
        location_state = "INSIDE_ZONE"
        action = "WAIT_CONFIRMATION"

    return {
        "state": "GEOMETRY_ONLY",
        "reason": "NO_ALIGNED_V226_HAZARD_PRIOR",
        "direction": direction,
        "timeframe": str(zone.get("timeframe") or "").upper(),
        "source_zone": dict(zone),
        "location_state": location_state,
        "current_depth": float(depth),
        "touch_count": touch_count,
        "action": action,
        "execution_ready": False,
        "recommended_band": {},
        "recommended_depth_low": None,
        "recommended_depth_high": None,
        "recommended_price_low": None,
        "recommended_price_high": None,
        "future_bands": [],
        "historical_prior_scope": "GEOMETRY_ONLY_NO_CALIBRATED_PRIOR",
        "interpretation": (
            "Physical depth only. No V225/V226 hazard prior is applied because "
            "the current V182 structural path is not backed by aligned V229/V226 "
            "entry geometry. This status cannot authorize an order."
        ),
    }



def child_reference_depth(
    *,
    v226_evaluation: dict[str, Any],
    direction: str,
    price: float,
) -> float | None:
    _tf, zone, _profile = _source_context(v226_evaluation, direction)
    return normalized_depth(zone, price)


def build_dynamic_depth_hazard(
    *,
    v226_evaluation: dict[str, Any],
    direction: str,
    live_price: float,
    pressure_transition: dict[str, Any],
) -> dict[str, Any]:
    """Sequential depth-hazard view for the current S/D approach.

    Historical V225 hazard is the prior. True cTrader Level-II pressure
    transition is a live modifier. The engine deliberately returns a band/range,
    not a single turning price, because V250 showed point-depth error remains
    large out of sample.
    """
    side = str(direction or "").upper()
    timeframe, zone, profile = _source_context(v226_evaluation, side)
    zone_low = _f(zone.get("low"))
    zone_high = _f(zone.get("high"))
    depth = normalized_depth(zone, live_price)
    bands = [dict(x) for x in list(profile.get("hazard_bands") or [])]
    if side not in {"LONG", "SHORT"} or zone_low is None or zone_high is None or depth is None or not bands:
        return {
            "state": "UNAVAILABLE",
            "reason": "MISSING_SOURCE_ZONE_OR_HAZARD_PRIOR",
            "execution_ready": False,
        }

    candidate = dict(v226_evaluation.get("depth_entry_candidate") or {})
    reuse = dict(candidate.get("zone_reuse") or {})
    retest_confirmation_required = bool(candidate.get("retest_confirmation_eligible"))
    prior_scope = str(
        reuse.get("historical_prior_scope")
        or "FIRST_TOUCH_CALIBRATED"
    )

    transition_state = str(pressure_transition.get("state") or "UNAVAILABLE")
    hard_block = bool(pressure_transition.get("hard_block"))
    multiplier = float(PRESSURE_MULTIPLIER.get(transition_state, 1.0))

    if depth < 0.0:
        current_index = -1
        location_state = "AHEAD_OF_ZONE"
    elif depth >= 1.0:
        current_index = 9
        location_state = "AT_OR_BEYOND_DISTAL"
    else:
        current_index = min(9, max(0, int(depth * 10.0)))
        location_state = "INSIDE_ZONE"

    if location_state == "AT_OR_BEYOND_DISTAL":
        return {
            "state": "DYNAMIC_DEPTH_HAZARD_AVAILABLE",
            "direction": side,
            "timeframe": timeframe,
            "source_zone": zone,
            "source_profile_touch_count": int(profile.get("touches") or 0),
            "location_state": location_state,
            "current_depth": float(depth),
            "current_band_index": current_index,
            "pressure_transition_state": transition_state,
            "pressure_hard_block": hard_block,
            "historical_prior_scope": prior_scope,
            "retest_confirmation_required": retest_confirmation_required,
            "zone_reuse": reuse,
            "action": "WAIT_STRUCTURE_REMAP",
            "execution_ready": False,
            "recommended_band": {},
            "future_bands": [],
            "interpretation": (
                "Price is at or beyond the distal edge of the selected source zone. "
                "The zone must be structurally remapped before any entry window can exist."
            ),
        }

    enriched: list[dict[str, Any]] = []
    for raw in bands:
        lower = _f(raw.get("lower_depth"))
        upper = _f(raw.get("upper_depth"))
        hazard = _f(raw.get("hazard"))
        at_risk = int(raw.get("at_risk") or 0)
        if lower is None or upper is None or hazard is None:
            continue
        band_index = min(9, max(0, int(round(lower * 10.0))))
        if band_index < max(0, current_index):
            continue

        distance_bands = max(0, band_index - max(0, current_index))
        local_multiplier = multiplier
        if transition_state in {"OPPOSING_REACCELERATION", "OPPOSING_STILL_ACTIVE"}:
            # Strong incoming pressure reduces confidence in shallow reversal
            # and modestly favors waiting one or more bands deeper.
            local_multiplier *= 0.85 if distance_bands == 0 else min(1.20, 1.0 + 0.08 * distance_bands)
        elif transition_state in {"BALANCED_ABSORPTION", "CONTROL_FLIP", "OPPOSING_FADING", "FADING_EARLY"}:
            # When pressure is fading/absorbed, current and next band deserve
            # more weight than distant bands.
            local_multiplier *= max(0.75, 1.0 - 0.06 * distance_bands)

        adjusted = max(0.0, min(0.95, hazard * local_multiplier))
        enriched.append(
            {
                **raw,
                "band_index": band_index,
                "adjusted_hazard": adjusted,
                "distance_bands": distance_bands,
                "eligible": at_risk >= MIN_AT_RISK,
                "price_low": min(
                    float(price_at_depth(zone, lower) or zone_low),
                    float(price_at_depth(zone, upper) or zone_high),
                ),
                "price_high": max(
                    float(price_at_depth(zone, lower) or zone_low),
                    float(price_at_depth(zone, upper) or zone_high),
                ),
            }
        )

    eligible = [row for row in enriched if row.get("eligible")]
    if not eligible:
        return {
            "state": "UNAVAILABLE",
            "reason": "NO_ELIGIBLE_HAZARD_BAND",
            "execution_ready": False,
            "timeframe": timeframe,
            "source_zone": zone,
            "current_depth": depth,
        }

    # Reacceleration requires the recommended band to be at least one band
    # deeper than the current one whenever such a band exists.
    selectable = eligible
    if transition_state in {"OPPOSING_REACCELERATION", "OPPOSING_STILL_ACTIVE"} and current_index >= 0:
        deeper = [row for row in eligible if int(row["band_index"]) >= current_index + 1]
        if deeper:
            selectable = deeper

    best = max(
        selectable,
        key=lambda row: (
            float(row.get("adjusted_hazard") or 0.0),
            float(row.get("wilson_lower_95") or 0.0),
            int(row.get("at_risk") or 0),
            -int(row.get("distance_bands") or 0),
        ),
    )
    min_entry_depth = float(best.get("lower_depth") or 0.0)
    upper_entry_depth = float(best.get("upper_depth") or min_entry_depth)

    if location_state == "AHEAD_OF_ZONE":
        action = "WAIT_ZONE"
        execution_ready = False
    elif location_state == "AT_OR_BEYOND_DISTAL":
        action = "WAIT_STRUCTURE_REMAP"
        execution_ready = False
    elif hard_block:
        action = "WAIT_PRESSURE"
        execution_ready = False
    elif transition_state in {"OPPOSING_FADING_EARLY", "FADING_EARLY"}:
        action = "WAIT_M5_CONFIRM"
        execution_ready = bool(pressure_transition.get("confirmation_entry_allowed"))
    elif transition_state in {"OPPOSING_FADING", "BALANCED_ABSORPTION", "CONTROL_FLIP"}:
        action = "ENTRY_WINDOW"
        execution_ready = bool(
            pressure_transition.get("pre_touch_entry_allowed")
            or pressure_transition.get("confirmation_entry_allowed")
        )
    else:
        action = "WAIT_OR_DEEPER"
        execution_ready = bool(pressure_transition.get("confirmation_entry_allowed"))

    return {
        "state": "DYNAMIC_DEPTH_HAZARD_AVAILABLE",
        "direction": side,
        "timeframe": timeframe,
        "source_zone": zone,
        "source_profile_touch_count": int(profile.get("touches") or 0),
        "location_state": location_state,
        "current_depth": float(depth),
        "current_band_index": current_index,
        "pressure_transition_state": transition_state,
        "pressure_hard_block": hard_block,
        "historical_prior_scope": prior_scope,
        "retest_confirmation_required": retest_confirmation_required,
        "zone_reuse": reuse,
        "action": action,
        "execution_ready": execution_ready,
        "recommended_band": best,
        "recommended_depth_low": min_entry_depth,
        "recommended_depth_high": upper_entry_depth,
        "recommended_price_low": float(best["price_low"]),
        "recommended_price_high": float(best["price_high"]),
        "future_bands": eligible[:],
        "interpretation": (
            "V225 historical hazard supplies the first-touch depth-band prior. On "
            "retested H4/H1 zones it is used as geometry context rather than a calibrated "
            "reuse probability; those entries stay confirmation-only. Current cTrader "
            "Level-II pressure transition updates whether to wait deeper or accept a "
            "reversal band. This is a sequential range estimate, not an exact turning price."
        ),
    }

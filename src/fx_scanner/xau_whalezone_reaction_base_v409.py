from __future__ import annotations

"""V409 reaction-base Whalezone reconstruction for XAUUSD.

This engine reconstructs the observable BUY1/BUY2/SELL1/SELL2 behaviour from
causal zone metadata already published by the scanner. It does not attempt to
copy a proprietary formula. The core hypothesis is:

    reaction base -> displacement -> structural break -> surviving zone

M15 is the preferred reaction-zone timeframe, H1/H4 provide structural parent
context, and M5 remains refinement/timing only. Missing evidence such as an
explicit FVG or liquidity sweep is never fabricated: unavailable components
are removed from the weighted denominator.

Decision-support only. No broker execution authority is granted here.
"""

from math import isfinite
from statistics import median
from typing import Any

CONTRACT = "XAU_RIZAN_WHALEZONE_REACTION_BASE_V409"
MODE = "REACTION_BASE_DISPLACEMENT_BOS"
MAX_TIERS_PER_SIDE = 2
MIN_QUALITY_SCORE = 62.0
MIN_EVIDENCE_WEIGHT = 0.55
WRONG_SIDE_TOLERANCE_ATR = 0.20

WEIGHTS: dict[str, float] = {
    "displacement": 0.25,
    "bos_mss": 0.20,
    "freshness": 0.15,
    "imbalance_fvg": 0.15,
    "base_compression": 0.10,
    "liquidity_sweep": 0.10,
    "htf_alignment": 0.05,
}

_INVALID_CONDITIONS = {"BROKEN", "INVALID", "RETIRED"}


def _d(value: Any) -> dict[str, Any]:
    return dict(value or {})


def _f(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _band(row: dict[str, Any]) -> tuple[float, float] | None:
    low = _f(row.get("low"))
    high = _f(row.get("high"))
    if low is None or high is None:
        low = _f(row.get("distal"))
        high = _f(row.get("proximal"))
    if low is None or high is None:
        return None
    if high < low:
        low, high = high, low
    if high <= low:
        return None
    return float(low), float(high)


def _distance_to_band(price: float, low: float, high: float) -> float:
    if low <= price <= high:
        return 0.0
    if price < low:
        return low - price
    return price - high


def _estimate_atr(sd: dict[str, Any]) -> tuple[float, str]:
    direct = _f(sd.get("atr_reference")) or _f(sd.get("atr"))
    if direct is not None and direct > 0:
        return float(direct), "TOP_LEVEL"

    values: list[float] = []
    for raw in list(sd.get("active_zones") or []):
        atr = _f(_d(raw).get("atr"))
        if atr is not None and atr > 0:
            values.append(float(atr))
    for key in ("main_reversal_zone", "decision_zone"):
        atr = _f(_d(sd.get(key)).get("atr"))
        if atr is not None and atr > 0:
            values.append(float(atr))
    if values:
        return float(median(values)), "ZONE_MEDIAN"

    price = _f(sd.get("price_now")) or 4000.0
    return max(abs(price) * 0.0025, 1.0), "FALLBACK_VOLATILITY_HEURISTIC"


def _bool_evidence(row: dict[str, Any], keys: tuple[str, ...]) -> bool | None:
    for key in keys:
        if key in row and row.get(key) is not None:
            value = row.get(key)
            if isinstance(value, bool):
                return value
            if isinstance(value, (int, float)):
                return bool(value)
            text = str(value).strip().upper()
            if text in {"TRUE", "YES", "Y", "1", "CONFIRMED", "PRESENT"}:
                return True
            if text in {"FALSE", "NO", "N", "0", "ABSENT", "NONE"}:
                return False
    return None


def _numeric_evidence(row: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        value = _f(row.get(key))
        if value is not None:
            return float(value)
    return None


def _displacement(row: dict[str, Any]) -> float | None:
    range_atr = _f(row.get("departure_range_atr"))
    body_fraction = _f(row.get("departure_body_fraction"))
    parts: list[tuple[float, float]] = []
    if range_atr is not None:
        # 2 ATR+ departure is treated as fully impulsive; 0.5 ATR remains weak.
        parts.append((_clamp((range_atr - 0.50) / 1.50), 0.70))
    if body_fraction is not None:
        parts.append((_clamp((body_fraction - 0.45) / 0.45), 0.30))
    if not parts:
        return None
    total = sum(weight for _, weight in parts)
    return sum(value * weight for value, weight in parts) / total


def _bos_mss(row: dict[str, Any]) -> float | None:
    if "structural_bos" in row:
        return 1.0 if bool(row.get("structural_bos")) else 0.0
    state = " ".join(
        str(row.get(key) or "").upper()
        for key in ("zone_class", "pattern", "structure_state", "break_type")
    )
    if "BOS" in state or "MSS" in state or "CHOCH" in state:
        return 1.0
    return None


def _freshness(row: dict[str, Any]) -> float | None:
    lifecycle = _d(row.get("lifecycle"))
    freshness = str(
        lifecycle.get("freshness")
        or row.get("freshness")
        or row.get("condition")
        or row.get("lifecycle_state")
        or ""
    ).upper()
    touch = _f(lifecycle.get("touch_count"))
    if touch is None:
        touch = _f(row.get("touch_count"))

    if not freshness and touch is None:
        return None

    if touch is None:
        touch_score = 1.0
    elif touch <= 0:
        touch_score = 1.0
    elif touch <= 1:
        touch_score = 0.75
    elif touch <= 2:
        touch_score = 0.50
    else:
        touch_score = max(0.15, 0.45 - 0.10 * (touch - 2.0))

    if "FRESH" in freshness:
        state_cap = 1.0
    elif "CONFIRMED" in freshness or "RETEST" in freshness or "ACTIVE" in freshness:
        state_cap = 0.78
    elif "DEGRADED" in freshness or "MITIGATED" in freshness:
        state_cap = 0.45
    elif freshness in _INVALID_CONDITIONS:
        state_cap = 0.0
    else:
        state_cap = 0.70
    return min(touch_score, state_cap)


def _base_compression(row: dict[str, Any]) -> float | None:
    width_atr = _f(row.get("base_range_atr"))
    bars = _f(row.get("base_bars"))
    parts: list[tuple[float, float]] = []
    if width_atr is not None:
        if width_atr <= 0.45:
            width_score = 1.0
        elif width_atr >= 1.25:
            width_score = 0.05
        else:
            width_score = 1.0 - 0.95 * ((width_atr - 0.45) / 0.80)
        parts.append((_clamp(width_score), 0.75))
    if bars is not None:
        if 1 <= bars <= 4:
            bar_score = 1.0
        elif bars <= 6:
            bar_score = 0.55
        else:
            bar_score = 0.20
        parts.append((bar_score, 0.25))
    if not parts:
        return None
    total = sum(weight for _, weight in parts)
    return sum(value * weight for value, weight in parts) / total


def _imbalance_fvg(row: dict[str, Any]) -> float | None:
    explicit = _bool_evidence(
        row,
        (
            "has_fvg",
            "fvg_confirmed",
            "imbalance_confirmed",
            "has_imbalance",
            "clean_imbalance",
        ),
    )
    if explicit is not None:
        return 1.0 if explicit else 0.0
    ratio = _numeric_evidence(
        row,
        ("fvg_overlap_ratio", "fvg_ratio", "imbalance_ratio", "imbalance_fraction"),
    )
    if ratio is not None:
        return _clamp(ratio)
    return None


def _liquidity_sweep(row: dict[str, Any]) -> float | None:
    explicit = _bool_evidence(
        row,
        (
            "liquidity_sweep",
            "liquidity_sweep_confirmed",
            "swept_liquidity",
            "sweep_confirmed",
            "has_sweep",
        ),
    )
    if explicit is not None:
        return 1.0 if explicit else 0.0
    nested = _d(row.get("liquidity"))
    explicit_nested = _bool_evidence(
        nested,
        ("sweep_confirmed", "liquidity_sweep", "confirmed", "swept"),
    )
    if explicit_nested is not None:
        return 1.0 if explicit_nested else 0.0
    return None


def _htf_alignment(row: dict[str, Any]) -> float | None:
    tf = str(row.get("timeframe") or "").upper()
    parent_overlap = _f(row.get("parent_overlap_ratio"))
    parent_id = row.get("parent_zone_id")
    if tf == "M15":
        # Preferred reaction-base timeframe. Parent overlap lifts confidence.
        if parent_overlap is not None:
            return _clamp(0.75 + 0.25 * parent_overlap)
        return 0.85 if parent_id else 0.75
    if tf == "M30":
        return 0.85
    if tf == "H1":
        return 1.0
    if tf == "H4":
        return 0.90
    if tf == "M5":
        # M5 is refinement only, not a primary Whalezone anchor.
        return 0.45 if not parent_id else 0.60
    return None


def _quality(row: dict[str, Any]) -> tuple[float, float, dict[str, Any]]:
    values: dict[str, float | None] = {
        "displacement": _displacement(row),
        "bos_mss": _bos_mss(row),
        "freshness": _freshness(row),
        "imbalance_fvg": _imbalance_fvg(row),
        "base_compression": _base_compression(row),
        "liquidity_sweep": _liquidity_sweep(row),
        "htf_alignment": _htf_alignment(row),
    }
    denominator = 0.0
    numerator = 0.0
    breakdown: dict[str, Any] = {}
    for name, weight in WEIGHTS.items():
        value = values[name]
        available = value is not None
        if available:
            assert value is not None
            denominator += weight
            numerator += weight * _clamp(float(value))
        breakdown[name] = {
            "available": available,
            "value": None if value is None else round(float(value), 4),
            "weight": weight,
        }
    score = 100.0 * numerator / denominator if denominator > 0 else 0.0
    return round(score, 2), round(denominator, 4), breakdown


def _raw_zones(sd: dict[str, Any]) -> list[dict[str, Any]]:
    rows = [_d(raw) for raw in list(sd.get("active_zones") or [])]
    for key in ("main_reversal_zone", "decision_zone", "parent_zone"):
        row = _d(sd.get(key))
        if row:
            rows.append(row)
    return rows


def _candidate(raw: dict[str, Any], *, price: float, atr: float) -> dict[str, Any] | None:
    row = _d(raw)
    direction = str(row.get("direction") or "").upper()
    if direction not in {"LONG", "SHORT"}:
        return None
    condition = str(row.get("condition") or row.get("lifecycle_state") or "ACTIVE").upper()
    if condition in _INVALID_CONDITIONS or bool(row.get("intraday_quarantined")):
        return None
    band = _band(row)
    if band is None:
        return None
    low, high = band
    center = (low + high) / 2.0

    wrong_side = (
        direction == "LONG" and center > price + WRONG_SIDE_TOLERANCE_ATR * atr
    ) or (
        direction == "SHORT" and center < price - WRONG_SIDE_TOLERANCE_ATR * atr
    )
    if wrong_side:
        return None

    quality, evidence_weight, breakdown = _quality(row)
    if evidence_weight < MIN_EVIDENCE_WEIGHT or quality < MIN_QUALITY_SCORE:
        return None

    distance = _distance_to_band(price, low, high)
    item = dict(row)
    item.update(
        {
            "direction": direction,
            "low": low,
            "high": high,
            "center": center,
            "distance_points": round(distance, 4),
            "distance_atr": round(distance / atr, 4) if atr > 0 else None,
            "quality_score": quality,
            "evidence_weight": evidence_weight,
            "quality_components": breakdown,
            "reaction_base_model": "BASE_TO_DISPLACEMENT_TO_BOS",
            "validation_timeframe": "M15",
            "refinement_timeframe": "M5",
        }
    )
    return item


def _overlap(a: dict[str, Any], b: dict[str, Any], *, tolerance: float) -> bool:
    ab = _band(a)
    bb = _band(b)
    if ab is None or bb is None:
        return False
    alo, ahi = ab
    blo, bhi = bb
    return not (ahi + tolerance < blo or bhi + tolerance < alo)


def _dedupe(rows: list[dict[str, Any]], *, atr: float) -> list[dict[str, Any]]:
    tolerance = max(0.04 * atr, 0.35)
    ordered = sorted(
        rows,
        key=lambda row: (
            -float(row.get("quality_score") or 0.0),
            float(row.get("distance_atr") or 999.0),
        ),
    )
    selected: list[dict[str, Any]] = []
    for row in ordered:
        duplicate = False
        for existing in selected:
            if row.get("direction") == existing.get("direction") and _overlap(
                row, existing, tolerance=tolerance
            ):
                duplicate = True
                break
        if not duplicate:
            selected.append(dict(row))
    return selected


def _tiers(
    rows: list[dict[str, Any]],
    *,
    direction: str,
    price: float,
    atr: float,
) -> list[dict[str, Any]]:
    side = [row for row in rows if row.get("direction") == direction]
    side = _dedupe(side, atr=atr)
    side.sort(
        key=lambda row: (
            float(row.get("distance_atr") or 0.0),
            -float(row.get("quality_score") or 0.0),
            -float(row.get("score") or 0.0),
        )
    )
    result: list[dict[str, Any]] = []
    for row in side[:MAX_TIERS_PER_SIDE]:
        item = dict(row)
        tier = len(result) + 1
        side_name = "BUY" if direction == "LONG" else "SELL"
        item["tier"] = tier
        item["label"] = f"{side_name}_{tier}"
        item["visual_label"] = f"WHALEZONE {side_name} {tier}"
        result.append(item)
    return result


def _focus(buy_zones: list[dict[str, Any]], sell_zones: list[dict[str, Any]]) -> tuple[str, str]:
    candidates: list[tuple[str, dict[str, Any]]] = []
    if buy_zones:
        candidates.append(("LONG", buy_zones[0]))
    if sell_zones:
        candidates.append(("SHORT", sell_zones[0]))
    if not candidates:
        return "WAIT", "NO_QUALIFIED_REACTION_BASE"
    candidates.sort(
        key=lambda pair: (
            float(pair[1].get("distance_atr") or 0.0),
            -float(pair[1].get("quality_score") or 0.0),
        )
    )
    direction, row = candidates[0]
    return direction, f"NEAREST_QUALIFIED_{row.get('label','ZONE')}"


def evaluate_whalezone_reaction_base_v409(
    sd_eval: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build quality-gated stacked Whalezone tiers from V342 reaction metadata."""
    sd = _d(sd_eval)
    price = _f(sd.get("price_now"))
    if price is None:
        return {
            "contract": CONTRACT,
            "mode": MODE,
            "state": "UNAVAILABLE",
            "direction": "WAIT",
            "reason": "PRICE_UNAVAILABLE",
            "buy_zones": [],
            "sell_zones": [],
            "execution_authority": False,
            "demo_auto_execution": False,
            "live_execution_enabled": False,
            "proprietary_formula_claimed": False,
        }

    atr, atr_source = _estimate_atr(sd)
    candidates: list[dict[str, Any]] = []
    rejected = 0
    for raw in _raw_zones(sd):
        candidate = _candidate(raw, price=price, atr=atr)
        if candidate is None:
            rejected += 1
            continue
        candidates.append(candidate)

    buy_zones = _tiers(candidates, direction="LONG", price=price, atr=atr)
    sell_zones = _tiers(candidates, direction="SHORT", price=price, atr=atr)
    direction, reason = _focus(buy_zones, sell_zones)

    if buy_zones and sell_zones:
        state = "TWO_SIDED_WHALEZONE_MAP"
    elif buy_zones:
        state = "BUY_SIDE_ONLY"
    elif sell_zones:
        state = "SELL_SIDE_ONLY"
    else:
        state = "NO_QUALIFIED_REACTION_BASE"

    return {
        "contract": CONTRACT,
        "mode": MODE,
        "state": state,
        "direction": direction,
        "reason": reason,
        "price_now": float(price),
        "atr_reference": round(float(atr), 6),
        "atr_source": atr_source,
        "quality_threshold": MIN_QUALITY_SCORE,
        "minimum_evidence_weight": MIN_EVIDENCE_WEIGHT,
        "candidate_count": len(candidates),
        "rejected_candidate_count": rejected,
        "buy_zones": buy_zones,
        "sell_zones": sell_zones,
        "model": {
            "sequence": ["REACTION_BASE", "DISPLACEMENT", "BOS_MSS", "SURVIVING_ZONE"],
            "primary_zone_timeframe": "M15",
            "parent_context_timeframes": ["H1", "H4"],
            "refinement_timeframe": "M5",
            "tier_rule": "QUALITY_GATE_THEN_NEAREST_OUTWARD",
            "missing_evidence_policy": "RENORMALIZE_AVAILABLE_COMPONENTS_DO_NOT_INVENT",
            "weights": dict(WEIGHTS),
        },
        "validation_status": "RECONSTRUCTION_REQUIRES_REPLAY_AND_FORWARD_VALIDATION",
        "execution_authority": False,
        "demo_auto_execution": False,
        "live_execution_enabled": False,
        "proprietary_formula_claimed": False,
    }


__all__ = [
    "CONTRACT",
    "MODE",
    "WEIGHTS",
    "MIN_QUALITY_SCORE",
    "MIN_EVIDENCE_WEIGHT",
    "evaluate_whalezone_reaction_base_v409",
]

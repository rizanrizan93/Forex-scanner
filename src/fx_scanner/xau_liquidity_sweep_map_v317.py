from __future__ import annotations

from math import isfinite
from typing import Any, Iterable

CONTRACT = "XAU_LIQUIDITY_SWEEP_MAP_V317_1"
POLICY_EFFECT = "STRUCTURAL_CONTEXT_ONLY"
EXECUTION_INFLUENCE = False
EXECUTION_AUTHORITY = False
PROMOTION_AUTHORITY = False

_TIMEFRAME_RANK = {"M5": 0, "M15": 1, "M30": 2, "H1": 3, "H4": 4, "D1": 5}


def _f(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _active(zone: dict[str, Any]) -> bool:
    lifecycle = dict(zone.get("lifecycle") or {})
    if lifecycle.get("active") is False:
        return False
    return not bool(lifecycle.get("invalidated_at"))


def _valid_zone(zone: dict[str, Any]) -> bool:
    low = _f(zone.get("low"))
    high = _f(zone.get("high"))
    return bool(
        low is not None
        and high is not None
        and high > low
        and str(zone.get("direction") or "").upper() in {"LONG", "SHORT"}
        and _active(zone)
    )


def _gap(a: dict[str, Any], b: dict[str, Any]) -> float:
    a_low = float(a["low"])
    a_high = float(a["high"])
    b_low = float(b["low"])
    b_high = float(b["high"])
    if a_high >= b_low and b_high >= a_low:
        return 0.0
    if a_high < b_low:
        return b_low - a_high
    return a_low - b_high


def _overlap(a: dict[str, Any], b: dict[str, Any]) -> float:
    a_low = float(a["low"])
    a_high = float(a["high"])
    b_low = float(b["low"])
    b_high = float(b["high"])
    intersection = max(0.0, min(a_high, b_high) - max(a_low, b_low))
    denominator = max(min(a_high - a_low, b_high - b_low), 1e-12)
    return intersection / denominator


def _compact_zone(zone: dict[str, Any]) -> dict[str, Any]:
    return {
        key: zone.get(key)
        for key in (
            "zone_id",
            "timeframe",
            "zone_class",
            "pattern",
            "direction",
            "low",
            "high",
            "proximal",
            "distal",
            "atr_points",
            "status",
            "research_score",
            "nested_in",
            "liquidity",
            "lifecycle",
        )
        if zone.get(key) is not None
    }


def _level_rows(zones: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[tuple[str, float]] = set()
    for zone in zones:
        liquidity = dict(zone.get("liquidity") or {})
        for raw in list(liquidity.get("nearby_levels") or []):
            item = dict(raw or {})
            price = _f(item.get("price"))
            if price is None:
                continue
            source = str(item.get("source") or "LIQUIDITY")
            key = (source, round(price, 5))
            if key in seen:
                continue
            seen.add(key)
            output.append(
                {
                    "price": price,
                    "source": source,
                    "distance_atr": item.get("distance_atr"),
                    "zone_id": zone.get("zone_id"),
                    "timeframe": zone.get("timeframe"),
                }
            )
    return output


def _decision_zone(
    *,
    atlas_evaluation: dict[str, Any],
    style_path: dict[str, Any],
) -> dict[str, Any] | None:
    for raw in (
        style_path.get("next_decision_zone"),
        dict(style_path.get("primary_path") or {}).get("destination_stack", [None])[0]
        if list(dict(style_path.get("primary_path") or {}).get("destination_stack") or [])
        else None,
        dict(atlas_evaluation.get("path_map") or {}).get("active_path", {}).get(
            "primary_opposing_zone"
        ),
    ):
        zone = dict(raw or {})
        if _valid_zone(zone):
            return zone
    nearest_supply = dict(atlas_evaluation.get("nearest_supply") or {})
    nearest_demand = dict(atlas_evaluation.get("nearest_demand") or {})
    candidates = [z for z in (nearest_supply, nearest_demand) if _valid_zone(z)]
    if not candidates:
        return None
    candidates.sort(key=lambda z: float(z.get("distance_points") or 1e12))
    return candidates[0]


def build_liquidity_sweep_map(
    *,
    atlas_evaluation: dict[str, Any],
    style_path: dict[str, Any] | None = None,
    price_now: float | None = None,
) -> dict[str, Any]:
    """Map liquidity beyond a structural decision zone before reversal.

    This is intentionally context-only. It answers: "If this decision zone is
    swept, where is the next same-side structural/liquidity envelope?" It does
    not declare that price must sweep it, nor does it authorize an entry.
    """
    atlas = dict(atlas_evaluation or {})
    style = dict(style_path or {})
    decision = _decision_zone(atlas_evaluation=atlas, style_path=style)
    if not decision:
        return {
            "contract": CONTRACT,
            "state": "NO_DECISION_ZONE",
            "policy_effect": POLICY_EFFECT,
            "execution_influence": False,
            "execution_authority": False,
        }

    direction = str(decision.get("direction") or "").upper()
    low = float(decision["low"])
    high = float(decision["high"])
    atr = _f(decision.get("atr_points"))
    if atr is None:
        atr = max(high - low, 1.0)

    # Nearby same-direction zones may form the real sweep envelope around a
    # narrower decision zone. This is the failure mode seen when a compact H1
    # zone is swept into a broader H1/H4 parent before the actual reversal.
    max_gap = max(0.50 * atr, 0.50 * (high - low), 2.0)
    decision_rank = _TIMEFRAME_RANK.get(str(decision.get("timeframe") or "").upper(), 0)
    relatives: list[dict[str, Any]] = []
    for raw in list(atlas.get("zones") or []):
        zone = dict(raw or {})
        if not _valid_zone(zone):
            continue
        if str(zone.get("direction") or "").upper() != direction:
            continue
        if str(zone.get("zone_id") or "") == str(decision.get("zone_id") or ""):
            continue
        gap = _gap(decision, zone)
        overlap = _overlap(decision, zone)
        rank = _TIMEFRAME_RANK.get(str(zone.get("timeframe") or "").upper(), 0)
        # Admit direct overlap, nesting, or a very small gap to an equal/higher
        # structural frame. Far unrelated zones are not allowed to inflate the band.
        if not (
            overlap > 0.0
            or str(zone.get("zone_id") or "") in set(decision.get("nested_in") or [])
            or str(decision.get("zone_id") or "") in set(zone.get("nested_in") or [])
            or (gap <= max_gap and rank >= decision_rank)
        ):
            continue
        relatives.append(
            {
                **_compact_zone(zone),
                "gap_to_decision": gap,
                "overlap_ratio": overlap,
            }
        )

    band_low = low
    band_high = high
    if direction == "SHORT":
        for zone in relatives:
            if float(zone["high"]) >= high - 1e-9:
                band_high = max(band_high, float(zone["high"]))
    else:
        for zone in relatives:
            if float(zone["low"]) <= low + 1e-9:
                band_low = min(band_low, float(zone["low"]))

    level_zones = [decision] + relatives
    levels = _level_rows(level_zones)
    sweep_side_levels: list[dict[str, Any]] = []
    for item in levels:
        price = float(item["price"])
        if direction == "SHORT" and price >= high - 1e-9:
            sweep_side_levels.append(item)
            band_high = max(band_high, price)
        elif direction == "LONG" and price <= low + 1e-9:
            sweep_side_levels.append(item)
            band_low = min(band_low, price)

    # Keep structural envelope bounded: levels far beyond the admitted same-side
    # structural cluster are reported as targets but cannot expand the danger band
    # by more than one decision-zone ATR.
    if direction == "SHORT":
        band_high = min(band_high, high + atr)
        sweep_depth = max(0.0, band_high - high)
    else:
        band_low = max(band_low, low - atr)
        sweep_depth = max(0.0, low - band_low)

    sweep_depth_atr = sweep_depth / max(atr, 1e-12)
    liquidity_sources = sorted({str(row.get("source") or "") for row in sweep_side_levels})
    confluence = len(liquidity_sources)
    parent_extension = bool(
        (direction == "SHORT" and band_high > high + 1e-9)
        or (direction == "LONG" and band_low < low - 1e-9)
    )

    risk_score = 0
    if parent_extension:
        risk_score += 2
    if sweep_depth_atr >= 0.25:
        risk_score += 2
    elif sweep_depth_atr > 0:
        risk_score += 1
    if confluence >= 2:
        risk_score += 2
    elif confluence == 1:
        risk_score += 1
    risk_grade = "HIGH" if risk_score >= 4 else "MEDIUM" if risk_score >= 2 else "LOW"

    price = _f(price_now)
    relation = "UNKNOWN"
    if price is not None:
        if low <= price <= high:
            relation = "INSIDE_DECISION_ZONE"
        elif band_low <= price <= band_high:
            relation = "INSIDE_LIQUIDITY_SWEEP_BAND"
        elif price < low:
            relation = "BELOW_MAP"
        else:
            relation = "ABOVE_MAP"

    levels_sorted = sorted(
        sweep_side_levels,
        key=lambda row: float(row["price"]),
        reverse=direction == "LONG",
    )
    return {
        "contract": CONTRACT,
        "state": "LIQUIDITY_SWEEP_MAP_AVAILABLE",
        "direction": direction,
        "decision_zone": _compact_zone(decision),
        "sweep_side": "ABOVE_SUPPLY" if direction == "SHORT" else "BELOW_DEMAND",
        "sweep_band": {
            "low": band_low,
            "high": band_high,
            "depth_usd": sweep_depth,
            "depth_atr": sweep_depth_atr,
        },
        "same_direction_parent_zones": relatives[:8],
        "liquidity_levels": levels_sorted[:12],
        "liquidity_sources": liquidity_sources,
        "liquidity_confluence_count": confluence,
        "parent_extension_present": parent_extension,
        "risk_grade": risk_grade,
        "price_relation": relation,
        "first_touch_warning": bool(risk_grade in {"HIGH", "MEDIUM"} and parent_extension),
        "confirmation_required": (
            "DO_NOT_ASSUME_REVERSAL_AT_ZONE_EDGE; WAIT_SWEEP_EXHAUSTION_AND_"
            "M5_M15_RECLAIM_MSS_OR_DISPLACEMENT"
        ),
        "interpretation": (
            "Sweep band is a structural/liquidity danger envelope beyond the narrow "
            "decision zone. It is not a predicted exact reversal price."
        ),
        "policy_effect": POLICY_EFFECT,
        "execution_influence": EXECUTION_INFLUENCE,
        "execution_authority": EXECUTION_AUTHORITY,
        "promotion_authority": PROMOTION_AUTHORITY,
    }

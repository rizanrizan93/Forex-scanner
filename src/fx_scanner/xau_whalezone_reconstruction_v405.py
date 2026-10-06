from __future__ import annotations

"""V405 causal reconstruction of tiered XAUUSD reaction zones.

This module reconstructs the *observable behaviour* of the supplied "Whalezone"
example: grey BUY boxes below/around price and tiered pink SELL boxes above/around
price.  It does not claim to reproduce a proprietary indicator or private order
flow feed.

Inputs are limited to the scanner's current causal supply/demand,
support/resistance, liquidity and lifecycle snapshot.  H4/H1 provide structural
anchors; local support/resistance may refine the nearest tier.  M15 solid-close
acceptance is represented only when the upstream snapshot actually supplies the
required close/acceptance evidence.

Decision-support/research only.  It has no LIVE or DEMO order authority.
"""

from math import isfinite
from typing import Any

CONTRACT = "XAU_RIZAN_WHALEZONE_RECONSTRUCTION_V405"
MODE = "RESEARCH_MAPPING"
MAX_TIERS_PER_SIDE = 3
WRONG_SIDE_TOLERANCE_ATR = 0.20
NEAR_LIQUIDITY_ATR = 0.40


def _d(value: Any) -> dict[str, Any]:
    return dict(value or {})


def _f(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _estimate_atr(sd: dict[str, Any]) -> float:
    for raw in (
        sd.get("main_reversal_zone"),
        sd.get("decision_zone"),
        *list(sd.get("active_zones") or []),
    ):
        atr = _f(_d(raw).get("atr"))
        if atr is not None and atr > 0:
            return atr
    main = _d(sd.get("main_reversal_zone") or sd.get("decision_zone"))
    low, high = _f(main.get("low")), _f(main.get("high"))
    if low is not None and high is not None and high > low:
        return max(high - low, 1.0)
    return 10.0


def _role_direction(row: dict[str, Any]) -> str | None:
    explicit = str(row.get("direction") or "").upper()
    if explicit in {"LONG", "BUY"}:
        return "BUY"
    if explicit in {"SHORT", "SELL"}:
        return "SELL"
    text = " ".join(
        str(row.get(key) or "").upper()
        for key in (
            "current_role",
            "base_kind",
            "kind",
            "lifecycle_state",
            "condition",
        )
    )
    if "SUPPORT" in text or "DEMAND" in text or "DOWNSIDE_SWEEP" in text:
        return "BUY"
    if "RESISTANCE" in text or "SUPPLY" in text or "UPSIDE_SWEEP" in text:
        return "SELL"
    return None


def _band(row: dict[str, Any], *, atr: float) -> tuple[float, float] | None:
    low = _f(row.get("low"))
    high = _f(row.get("high"))
    if low is None or high is None:
        low = _f(row.get("band_low"))
        high = _f(row.get("band_high"))
    if low is None or high is None:
        center = _f(row.get("price"))
        if center is None:
            return None
        half = max(0.08 * atr, 0.75)
        low, high = center - half, center + half
    if high < low:
        low, high = high, low
    if high <= low:
        return None
    return float(low), float(high)


def _source_priority(row: dict[str, Any], source_type: str) -> float:
    timeframe = str(row.get("timeframe") or "").upper()
    score = 0.0
    if timeframe == "H4":
        score += 5.0
    elif timeframe == "H1":
        score += 4.0
    elif timeframe == "M15":
        score += 2.5
    elif source_type == "SR":
        score += 2.0
    strength = _f(row.get("score"))
    if strength is None:
        strength = _f(row.get("strength"))
    if strength is not None:
        score += min(max(strength, 0.0), 3.0)
    lifecycle = str(row.get("lifecycle_state") or row.get("condition") or "").upper()
    if any(token in lifecycle for token in ("CONFIRMED", "REJECTION", "ACTIVE", "RETEST")):
        score += 2.0
    if bool(row.get("confirmed_flip")):
        score += 2.0
    return score


def _liquidity_near(
    sd: dict[str, Any], *, side: str, center: float, atr: float
) -> list[dict[str, Any]]:
    wanted = "SELL_SIDE" if side == "BUY" else "BUY_SIDE"
    out: list[dict[str, Any]] = []
    for raw in list(sd.get("liquidity_candidates") or []):
        row = _d(raw)
        price = _f(row.get("price"))
        liq_side = str(row.get("side") or "").upper()
        if price is None or liq_side not in {wanted, "BOTH"}:
            continue
        if abs(price - center) <= NEAR_LIQUIDITY_ATR * atr:
            out.append(
                {
                    "side": liq_side,
                    "price": price,
                    "kind": row.get("kind") or row.get("type"),
                }
            )
    out.sort(key=lambda row: abs(float(row["price"]) - center))
    return out[:4]


def _m15_acceptance(row: dict[str, Any]) -> dict[str, Any]:
    count = None
    for key in (
        "m15_acceptance_closes",
        "acceptance_closes",
        "consecutive_closes",
    ):
        value = row.get(key)
        if value is not None:
            try:
                count = int(value)
            except (TypeError, ValueError):
                count = None
            break
    explicit = row.get("acceptance_confirmed")
    if explicit is None:
        explicit = row.get("accepted_break")
    if explicit is not None:
        confirmed = bool(explicit)
        status = "CONFIRMED" if confirmed else "NOT_CONFIRMED"
    elif count is not None:
        confirmed = count >= 1
        status = "CONFIRMED" if confirmed else "NOT_CONFIRMED"
    else:
        confirmed = None
        status = "UNKNOWN_NO_M15_CLOSE_INPUT"
    return {
        "status": status,
        "confirmed": confirmed,
        "close_count": count,
        "source_available": explicit is not None or count is not None,
    }


def _zone_state(side: str, *, price: float, low: float, high: float) -> str:
    if low <= price <= high:
        return "IN_ZONE"
    if side == "SELL":
        return "AHEAD" if price < low else "BREACHED_PENDING_ACCEPTANCE"
    return "AHEAD" if price > high else "BREACHED_PENDING_ACCEPTANCE"


def _candidate(
    sd: dict[str, Any],
    raw: dict[str, Any],
    *,
    source_type: str,
    price: float,
    atr: float,
) -> dict[str, Any] | None:
    side = _role_direction(raw)
    if side not in {"BUY", "SELL"}:
        return None
    condition = str(raw.get("condition") or "").upper()
    lifecycle = str(raw.get("lifecycle_state") or condition or "ACTIVE").upper()
    if condition in {"BROKEN", "INVALID", "RETIRED"} or lifecycle in {
        "BROKEN",
        "INVALID",
        "RETIRED",
    }:
        return None
    if bool(raw.get("intraday_quarantined")):
        return None
    band = _band(raw, atr=atr)
    if band is None:
        return None
    low, high = band
    center = (low + high) / 2.0
    if side == "SELL" and center < price - WRONG_SIDE_TOLERANCE_ATR * atr:
        return None
    if side == "BUY" and center > price + WRONG_SIDE_TOLERANCE_ATR * atr:
        return None
    distance = 0.0 if low <= price <= high else min(abs(price - low), abs(price - high))
    liquidity = _liquidity_near(sd, side=side, center=center, atr=atr)
    acceptance = _m15_acceptance(raw)
    score = _source_priority(raw, source_type)
    if liquidity:
        score += 2.0
    if _zone_state(side, price=price, low=low, high=high) == "IN_ZONE":
        score += 1.0
    return {
        "side": side,
        "low": low,
        "high": high,
        "center": center,
        "width": high - low,
        "source_type": source_type,
        "timeframe": str(raw.get("timeframe") or ("LOCAL" if source_type == "SR" else "HTF")).upper(),
        "zone_id": raw.get("zone_id"),
        "condition": condition or None,
        "lifecycle_state": lifecycle,
        "confirmed_flip": bool(raw.get("confirmed_flip")),
        "reclaim_required": bool(raw.get("reclaim_required")),
        "distance_points": distance,
        "distance_atr": distance / atr,
        "state": _zone_state(side, price=price, low=low, high=high),
        "structural_score": round(score, 4),
        "liquidity": liquidity,
        "m15_acceptance": acceptance,
    }


def _collect(sd: dict[str, Any], *, price: float, atr: float) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw in list(sd.get("active_zones") or []):
        item = _candidate(sd, _d(raw), source_type="SD", price=price, atr=atr)
        if item:
            rows.append(item)

    sr = _d(sd.get("support_resistance_map"))
    sr_rows = [_d(row) for row in list(sr.get("levels") or [])]
    for key in ("nearest_support", "nearest_resistance"):
        fallback = _d(sr.get(key))
        if fallback:
            sr_rows.append(fallback)
    for raw in sr_rows:
        item = _candidate(sd, raw, source_type="SR", price=price, atr=atr)
        if item:
            rows.append(item)
    return rows


def _overlap_ratio(a: dict[str, Any], b: dict[str, Any]) -> float:
    left = max(float(a["low"]), float(b["low"]))
    right = min(float(a["high"]), float(b["high"]))
    if right <= left:
        return 0.0
    overlap = right - left
    narrow = min(float(a["width"]), float(b["width"]))
    return overlap / narrow if narrow > 0 else 0.0


def _dedupe(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(
        rows,
        key=lambda row: (-float(row.get("structural_score") or 0.0), float(row["width"])),
    )
    kept: list[dict[str, Any]] = []
    for row in ordered:
        duplicate = next(
            (
                existing
                for existing in kept
                if existing["side"] == row["side"] and _overlap_ratio(existing, row) >= 0.60
            ),
            None,
        )
        if duplicate is None:
            kept.append(dict(row))
            continue
        sources = list(duplicate.get("merged_sources") or [])
        sources.append(
            {
                "source_type": row.get("source_type"),
                "timeframe": row.get("timeframe"),
                "zone_id": row.get("zone_id"),
            }
        )
        duplicate["merged_sources"] = sources
    return kept


def _tier(rows: list[dict[str, Any]], *, side: str, price: float) -> list[dict[str, Any]]:
    selected = [dict(row) for row in rows if row.get("side") == side]
    if side == "SELL":
        selected.sort(
            key=lambda row: (
                0 if float(row["high"]) >= price else 1,
                abs(float(row["low"]) - price),
                -float(row.get("structural_score") or 0.0),
            )
        )
    else:
        selected.sort(
            key=lambda row: (
                0 if float(row["low"]) <= price else 1,
                abs(price - float(row["high"])),
                -float(row.get("structural_score") or 0.0),
            )
        )
    selected = selected[:MAX_TIERS_PER_SIDE]
    for index, row in enumerate(selected, start=1):
        row["tier"] = index
        row["label"] = f"WHALEZONE {side} {index}"
    return selected


def evaluate_whalezone_reconstruction_v405(
    sd_eval: dict[str, Any] | None,
) -> dict[str, Any]:
    """Return a tiered BUY/SELL reaction-zone map from causal scanner geometry."""

    sd = _d(sd_eval)
    price = _f(sd.get("price_now"))
    if price is None:
        return {
            "contract": CONTRACT,
            "mode": MODE,
            "state": "UNAVAILABLE",
            "reason": "PRICE_NOW_UNAVAILABLE",
            "execution_authority": False,
            "demo_auto_execution": False,
            "live_execution_enabled": False,
        }

    atr = _estimate_atr(sd)
    candidates = _dedupe(_collect(sd, price=price, atr=atr))
    buy_zones = _tier(candidates, side="BUY", price=price)
    sell_zones = _tier(candidates, side="SELL", price=price)

    nearest_buy = buy_zones[0] if buy_zones else {}
    nearest_sell = sell_zones[0] if sell_zones else {}
    if nearest_buy and nearest_sell:
        buy_high = float(nearest_buy["high"])
        sell_low = float(nearest_sell["low"])
        if buy_high <= price <= sell_low:
            structure_state = "SIDEWAYS_STRUCTURED_RANGE"
        elif nearest_buy.get("state") == "IN_ZONE":
            structure_state = "IN_BUY_REACTION_ZONE"
        elif nearest_sell.get("state") == "IN_ZONE":
            structure_state = "IN_SELL_REACTION_ZONE"
        else:
            structure_state = "BETWEEN_STRUCTURAL_ZONES"
    elif nearest_buy:
        structure_state = "BUY_STRUCTURE_ONLY"
    elif nearest_sell:
        structure_state = "SELL_STRUCTURE_ONLY"
    else:
        structure_state = "NO_VALID_ZONE"

    active_side = "WAIT"
    active_zone: dict[str, Any] = {}
    in_buy = next((row for row in buy_zones if row.get("state") == "IN_ZONE"), None)
    in_sell = next((row for row in sell_zones if row.get("state") == "IN_ZONE"), None)
    if in_buy and not in_sell:
        active_side, active_zone = "BUY", dict(in_buy)
    elif in_sell and not in_buy:
        active_side, active_zone = "SELL", dict(in_sell)
    elif in_buy and in_sell:
        active_zone = max(
            (in_buy, in_sell), key=lambda row: float(row.get("structural_score") or 0.0)
        )
        active_side = str(active_zone.get("side") or "WAIT")

    return {
        "contract": CONTRACT,
        "mode": MODE,
        "state": structure_state,
        "price_now": price,
        "atr_reference": atr,
        "active_side": active_side,
        "active_zone": active_zone,
        "buy_zones": buy_zones,
        "sell_zones": sell_zones,
        "primary_buy": nearest_buy,
        "primary_sell": nearest_sell,
        "candidate_count": len(candidates),
        "mapping_basis": [
            "H4_H1_SUPPLY_DEMAND",
            "LOCAL_SUPPORT_RESISTANCE_REFINEMENT",
            "LIQUIDITY_PROXIMITY",
            "ZONE_LIFECYCLE",
            "M15_SOLID_CLOSE_ONLY_WHEN_UPSTREAM_EVIDENCE_EXISTS",
        ],
        "reconstruction_note": (
            "Behavioural reconstruction from observed mapping; not a claim of the proprietary Whalezone formula."
        ),
        "execution_authority": False,
        "demo_auto_execution": False,
        "live_execution_enabled": False,
        "validation_status": "V405_RESEARCH_MAPPING_REQUIRES_REPLAY_AND_FORWARD_CALIBRATION",
    }

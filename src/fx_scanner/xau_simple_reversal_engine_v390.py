from __future__ import annotations

"""V390 simple XAU reversal engine.

Purpose: answer the user's daily question without forcing price to travel to a
far H4 destination first:

    where is the nearest tradeable reversal zone, and which way should price
    reverse from it?

The engine evaluates LONG and SHORT sides independently from the same causal
S/D + support/resistance + liquidity snapshot.  A distant H4 zone remains a
structural fallback/destination only; it cannot suppress a closer local zone.

This module is decision support only.  It does not grant LIVE or DEMO order
authority.  Promotion to auto-execution requires separate replay validation.
"""

from math import isfinite
from typing import Any

CONTRACT = "XAU_RIZAN_SIMPLE_REVERSAL_V390"
MAX_ACTIONABLE_DISTANCE_ATR = 2.25
PREPARE_DISTANCE_ATR = 0.35
WRONG_SIDE_TOLERANCE_ATR = 0.20


def _f(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _d(value: Any) -> dict[str, Any]:
    return dict(value or {})


def _distance_to_band(price: float, low: float, high: float) -> float:
    if low <= price <= high:
        return 0.0
    if price < low:
        return low - price
    return price - high


def _estimate_atr(sd: dict[str, Any]) -> float:
    for source in (
        _d(sd.get("main_reversal_zone")),
        _d(sd.get("decision_zone")),
        *[_d(row) for row in list(sd.get("active_zones") or [])],
    ):
        atr = _f(source.get("atr"))
        if atr is not None and atr > 0:
            return atr
    main = _d(sd.get("main_reversal_zone") or sd.get("decision_zone"))
    low = _f(main.get("low"))
    high = _f(main.get("high"))
    if low is not None and high is not None and high > low:
        return max(high - low, 1.0)
    return 10.0


def _role(row: dict[str, Any]) -> str:
    return str(
        row.get("current_role")
        or row.get("base_kind")
        or row.get("kind")
        or row.get("lifecycle_state")
        or ""
    ).upper()


def _sr_direction(row: dict[str, Any]) -> str | None:
    text = " ".join(
        str(row.get(key) or "").upper()
        for key in ("current_role", "base_kind", "kind", "lifecycle_state")
    )
    if "SUPPORT" in text or "DOWNSIDE_SWEEP" in text:
        return "LONG"
    if "RESISTANCE" in text or "UPSIDE_SWEEP" in text:
        return "SHORT"
    return None


def _band_from_sr(row: dict[str, Any], atr: float) -> tuple[float, float] | None:
    low = _f(row.get("band_low"))
    high = _f(row.get("band_high"))
    center = _f(row.get("price"))
    if low is None or high is None:
        if center is None:
            return None
        half = max(0.08 * atr, 0.75)
        low, high = center - half, center + half
    if high < low:
        low, high = high, low
    return float(low), float(high)


def _liquidity_near(sd: dict[str, Any], *, direction: str, center: float, atr: float) -> list[dict[str, Any]]:
    wanted = "SELL_SIDE" if direction == "LONG" else "BUY_SIDE"
    rows: list[dict[str, Any]] = []
    for raw in list(sd.get("liquidity_candidates") or []):
        row = _d(raw)
        px = _f(row.get("price"))
        side = str(row.get("side") or "").upper()
        if px is None or side not in {wanted, "BOTH"}:
            continue
        if abs(px - center) <= 0.35 * atr:
            rows.append(row)
    rows.sort(key=lambda row: abs(float(row.get("price") or center) - center))
    return rows[:4]


def _strong_state(direction: str, state: str) -> bool:
    state = state.upper()
    if direction == "LONG":
        return state in {
            "DOWNSIDE_SWEEP_LIKE_REJECTION",
            "CONFIRMED_SUPPORT_FLIP",
            "BULL_RETEST_IN_PROGRESS",
        }
    return state in {
        "UPSIDE_SWEEP_LIKE_REJECTION",
        "CONFIRMED_RESISTANCE_FLIP",
        "BEAR_RETEST_IN_PROGRESS",
    }


def _watch_state(direction: str, state: str) -> bool:
    state = state.upper()
    if _strong_state(direction, state):
        return True
    if direction == "LONG":
        return state in {"ACTIVE_SUPPORT", "ACTIVE_FLIP_CONTEXT"}
    return state in {"ACTIVE_RESISTANCE", "ACTIVE_FLIP_CONTEXT"}


def _candidate_score(candidate: dict[str, Any]) -> float:
    score = 0.0
    source_type = str(candidate.get("source_type") or "")
    timeframe = str(candidate.get("timeframe") or "")
    state = str(candidate.get("lifecycle_state") or "")
    direction = str(candidate.get("direction") or "")
    distance_atr = float(candidate.get("distance_atr") or 0.0)

    if source_type == "SR":
        score += 5.0
    elif timeframe == "H1":
        score += 4.0
    elif timeframe == "H4":
        score += 2.0

    if _strong_state(direction, state):
        score += 4.0
    elif _watch_state(direction, state):
        score += 2.0

    if candidate.get("confirmed_flip"):
        score += 3.0
    if candidate.get("liquidity"):
        score += 3.0

    strength = _f(candidate.get("strength")) or 0.0
    score += min(max(strength, 0.0), 2.0)

    if distance_atr == 0.0:
        score += 2.0
    score -= 2.0 * distance_atr
    if candidate.get("reclaim_required"):
        score -= 1.5
    return score


def _collect_candidates(sd: dict[str, Any], *, direction: str, price: float, atr: float) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    sr = _d(sd.get("support_resistance_map"))
    sr_levels = [_d(row) for row in list(sr.get("levels") or [])]
    fallback = _d(sr.get("nearest_support" if direction == "LONG" else "nearest_resistance"))
    if fallback:
        sr_levels.append(fallback)

    seen_sr: set[tuple[float, float]] = set()
    for row in sr_levels:
        if _sr_direction(row) != direction:
            continue
        band = _band_from_sr(row, atr)
        if band is None:
            continue
        low, high = band
        key = (round(low, 4), round(high, 4))
        if key in seen_sr:
            continue
        seen_sr.add(key)
        center = (low + high) / 2.0
        distance = _distance_to_band(price, low, high)
        distance_atr = distance / atr
        wrong_side = (
            direction == "LONG" and center > price + WRONG_SIDE_TOLERANCE_ATR * atr
        ) or (
            direction == "SHORT" and center < price - WRONG_SIDE_TOLERANCE_ATR * atr
        )
        if wrong_side:
            continue
        state = str(row.get("lifecycle_state") or "UNKNOWN").upper()
        candidate = {
            "direction": direction,
            "low": low,
            "high": high,
            "center": center,
            "source_type": "SR",
            "timeframe": str(row.get("timeframe") or "LOCAL"),
            "lifecycle_state": state,
            "confirmed_flip": bool(row.get("confirmed_flip")),
            "reclaim_required": bool(row.get("reclaim_required")),
            "strength": _f(row.get("strength")),
            "distance_points": distance,
            "distance_atr": distance_atr,
            "liquidity": _liquidity_near(sd, direction=direction, center=center, atr=atr),
            "sources": list(row.get("sources") or []),
            "zone_id": row.get("zone_id"),
        }
        candidate["score"] = round(_candidate_score(candidate), 4)
        candidate["actionable"] = distance_atr <= MAX_ACTIONABLE_DISTANCE_ATR
        rows.append(candidate)

    for raw in list(sd.get("active_zones") or []):
        row = _d(raw)
        if str(row.get("direction") or "").upper() != direction:
            continue
        if bool(row.get("intraday_quarantined")):
            continue
        if str(row.get("condition") or "").upper() in {"BROKEN", "INVALID", "RETIRED"}:
            continue
        low = _f(row.get("low"))
        high = _f(row.get("high"))
        if low is None or high is None or high <= low:
            continue
        center = (low + high) / 2.0
        wrong_side = (
            direction == "LONG" and center > price + WRONG_SIDE_TOLERANCE_ATR * atr
        ) or (
            direction == "SHORT" and center < price - WRONG_SIDE_TOLERANCE_ATR * atr
        )
        if wrong_side:
            continue
        distance = _distance_to_band(price, low, high)
        distance_atr = distance / atr
        life = _d(row.get("lifecycle"))
        state = str(row.get("lifecycle_state") or row.get("condition") or "ACTIVE").upper()
        candidate = {
            "direction": direction,
            "low": float(low),
            "high": float(high),
            "center": center,
            "source_type": "SD",
            "timeframe": str(row.get("timeframe") or "HTF"),
            "lifecycle_state": state,
            "confirmed_flip": False,
            "reclaim_required": False,
            "strength": _f(row.get("score")),
            "distance_points": distance,
            "distance_atr": distance_atr,
            "liquidity": _liquidity_near(sd, direction=direction, center=center, atr=atr),
            "sources": ["SUPPLY_DEMAND"],
            "zone_id": row.get("zone_id"),
            "touch_count": life.get("touch_count"),
            "mitigation_depth": life.get("mitigation_depth"),
        }
        candidate["score"] = round(_candidate_score(candidate), 4)
        candidate["actionable"] = distance_atr <= MAX_ACTIONABLE_DISTANCE_ATR
        rows.append(candidate)

    # Prefer tradeable quality first. Distance is a tiebreaker, not the only rule.
    rows.sort(
        key=lambda row: (
            not bool(row.get("actionable")),
            -float(row.get("score") or 0.0),
            float(row.get("distance_atr") or 999.0),
        )
    )
    return rows


def _best(rows: list[dict[str, Any]]) -> dict[str, Any]:
    for row in rows:
        if row.get("actionable"):
            return dict(row)
    return {}


def _zone_state(candidate: dict[str, Any], *, price: float, atr: float) -> str:
    if not candidate:
        return "UNAVAILABLE"
    low = float(candidate["low"])
    high = float(candidate["high"])
    if low <= price <= high:
        return "IN_ZONE"
    distance_atr = _distance_to_band(price, low, high) / atr
    if distance_atr <= PREPARE_DISTANCE_ATR:
        return "APPROACHING"
    return "AWAY"


def _readiness(candidate: dict[str, Any], *, price: float, atr: float) -> str:
    if not candidate:
        return "NONE"
    zone_state = _zone_state(candidate, price=price, atr=atr)
    direction = str(candidate.get("direction") or "")
    state = str(candidate.get("lifecycle_state") or "")
    evidence = 0
    if _strong_state(direction, state):
        evidence += 1
    if candidate.get("confirmed_flip"):
        evidence += 1
    if candidate.get("liquidity"):
        evidence += 1

    if zone_state == "IN_ZONE" and evidence >= 2 and not candidate.get("reclaim_required"):
        return "READY_EARLY"
    if zone_state == "IN_ZONE":
        return "WATCH_REACTION"
    if zone_state == "APPROACHING":
        return "PREPARE"
    return "WAIT"


def _invalidation(candidate: dict[str, Any], *, atr: float) -> float | None:
    if not candidate:
        return None
    low = float(candidate["low"])
    high = float(candidate["high"])
    buffer = max(0.12 * atr, 0.15 * (high - low))
    if candidate.get("direction") == "LONG":
        return low - buffer
    return high + buffer


def evaluate_simple_reversal(sd_eval: dict[str, Any] | None) -> dict[str, Any]:
    """Return a two-sided local reversal map and one current action state."""
    sd = _d(sd_eval)
    price = _f(sd.get("price_now"))
    if price is None:
        return {
            "contract": CONTRACT,
            "state": "UNAVAILABLE",
            "direction": "WAIT",
            "execution_authority": False,
            "live_execution_enabled": False,
        }

    atr = _estimate_atr(sd)
    long_rows = _collect_candidates(sd, direction="LONG", price=price, atr=atr)
    short_rows = _collect_candidates(sd, direction="SHORT", price=price, atr=atr)
    long_zone = _best(long_rows)
    short_zone = _best(short_rows)
    long_ready = _readiness(long_zone, price=price, atr=atr)
    short_ready = _readiness(short_zone, price=price, atr=atr)

    state = "WAIT_NO_LOCAL_ZONE"
    direction = "WAIT"
    selected: dict[str, Any] = {}

    if long_ready == "READY_EARLY" and short_ready != "READY_EARLY":
        state, direction, selected = "READY_LONG", "LONG", long_zone
    elif short_ready == "READY_EARLY" and long_ready != "READY_EARLY":
        state, direction, selected = "READY_SHORT", "SHORT", short_zone
    elif long_ready == "READY_EARLY" and short_ready == "READY_EARLY":
        selected = max((long_zone, short_zone), key=lambda row: float(row.get("score") or 0.0))
        direction = str(selected.get("direction") or "WAIT")
        state = f"READY_{direction}"
    elif long_ready in {"WATCH_REACTION", "PREPARE"} and short_ready not in {"WATCH_REACTION", "PREPARE"}:
        direction, selected = "LONG", long_zone
        state = "WATCH_LONG" if long_ready == "WATCH_REACTION" else "PREPARE_LONG"
    elif short_ready in {"WATCH_REACTION", "PREPARE"} and long_ready not in {"WATCH_REACTION", "PREPARE"}:
        direction, selected = "SHORT", short_zone
        state = "WATCH_SHORT" if short_ready == "WATCH_REACTION" else "PREPARE_SHORT"
    elif long_zone and short_zone:
        state = "RANGE_WAIT"
        direction = "WAIT"
    elif long_zone:
        state = "WAIT_LONG_ZONE"
        direction, selected = "LONG", long_zone
    elif short_zone:
        state = "WAIT_SHORT_ZONE"
        direction, selected = "SHORT", short_zone

    range_payload: dict[str, Any] = {}
    if long_zone and short_zone:
        floor = float(long_zone["high"])
        ceiling = float(short_zone["low"])
        if floor < ceiling:
            range_payload = {
                "state": "LOCAL_RANGE",
                "floor_zone": long_zone,
                "ceiling_zone": short_zone,
                "floor": floor,
                "ceiling": ceiling,
                "mid": (floor + ceiling) / 2.0,
                "width_points": ceiling - floor,
            }

    entry_low = selected.get("low") if selected else None
    entry_high = selected.get("high") if selected else None
    invalidation = _invalidation(selected, atr=atr) if selected else None
    tp1 = None
    if direction == "LONG" and short_zone:
        tp1 = short_zone.get("low")
    elif direction == "SHORT" and long_zone:
        tp1 = long_zone.get("high")

    if state == "READY_LONG":
        action = "LONG reversal candidate aktif di demand lokal. Entry hanya di band; jangan chase di atas zona."
    elif state == "READY_SHORT":
        action = "SHORT reversal candidate aktif di supply lokal. Entry hanya di band; jangan chase di bawah zona."
    elif state == "PREPARE_LONG":
        action = "Harga mendekati demand lokal. Bersiap LONG bila zona bereaksi; H4 jauh hanya fallback."
    elif state == "PREPARE_SHORT":
        action = "Harga mendekati supply lokal. Bersiap SHORT bila zona bereaksi; H4 jauh hanya fallback."
    elif state == "WATCH_LONG":
        action = "Harga berada di demand lokal; tunggu rejection/sweep/reclaim awal untuk LONG."
    elif state == "WATCH_SHORT":
        action = "Harga berada di supply lokal; tunggu rejection/sweep/reclaim awal untuk SHORT."
    elif state == "RANGE_WAIT":
        action = "Harga berada di antara demand dan supply lokal. Jangan entry di tengah; tunggu salah satu reversal zone."
    else:
        action = "Belum ada local reversal trigger yang cukup dekat. Tetap tampilkan kedua zona terdekat, bukan menunggu H4 jauh."

    main = _d(sd.get("main_reversal_zone") or sd.get("decision_zone"))
    return {
        "contract": CONTRACT,
        "state": state,
        "direction": direction,
        "price_now": price,
        "atr_reference": atr,
        "long_zone": long_zone,
        "short_zone": short_zone,
        "long_readiness": long_ready,
        "short_readiness": short_ready,
        "selected_zone": selected,
        "range": range_payload,
        "entry": {
            "low": entry_low,
            "high": entry_high,
            "invalidation": invalidation,
            "tp1_opposite_local_zone": tp1,
        },
        "action": action,
        "deep_htf_fallback": main,
        "deep_htf_is_entry_trigger": False,
        "candidate_counts": {
            "long": len(long_rows),
            "short": len(short_rows),
        },
        "execution_authority": False,
        "demo_auto_execution": False,
        "live_execution_enabled": False,
        "validation_status": "RESEARCH_AND_SHADOW_BEFORE_AUTO_EXECUTION",
    }

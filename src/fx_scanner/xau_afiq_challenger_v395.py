from __future__ import annotations

"""V395 AFIQ-pattern challenger for XAUUSD research/shadow evaluation.

This module reconstructs a behavioral hypothesis from the V394 reference
corpus without copying AFIQ prices into runtime logic. It intentionally has no
LIVE/DEMO execution authority.

Core hypothesis:
    effective HTF zone -> bounded liquidity sweep -> anticipatory entry ->
    reclaim/acceptance confidence upgrade -> opposing HTF destination.

Reclaim/MSS is therefore not a mandatory first-entry trigger. It is a
post-entry validation signal when a high-quality effective zone, structural
invalidation and reward/risk already exist.
"""

from math import isfinite
from typing import Any

CONTRACT = "XAU_RIZAN_AFIQ_CHALLENGER_V395"
REFERENCE_CORPUS = "AFIQ_REFERENCE_CORPUS_V394"
MIN_EFFECTIVE_SCORE = 7.0
MIN_RR = 1.50
EVENT_BLACKOUT_MINUTES = 60.0
PREPARE_DISTANCE_ZONE_WIDTHS = 0.35


def _f(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if isfinite(out) else None


def _d(value: Any) -> dict[str, Any]:
    return dict(value or {})


def _direction(value: Any) -> str:
    raw = str(value or "").upper()
    if raw in {"LONG", "BUY", "DEMAND", "SUPPORT"}:
        return "LONG"
    if raw in {"SHORT", "SELL", "SUPPLY", "RESISTANCE"}:
        return "SHORT"
    return ""


def _band(row: dict[str, Any]) -> tuple[float, float] | None:
    low = _f(row.get("low") if row.get("low") is not None else row.get("band_low"))
    high = _f(row.get("high") if row.get("high") is not None else row.get("band_high"))
    if low is None or high is None:
        center = _f(row.get("price"))
        width = _f(row.get("width"))
        if center is None or width is None or width <= 0:
            return None
        low, high = center - width / 2.0, center + width / 2.0
    if high < low:
        low, high = high, low
    if high <= low:
        return None
    return float(low), float(high)


def _role_text(row: dict[str, Any]) -> str:
    return " ".join(
        str(row.get(key) or "").upper()
        for key in (
            "role",
            "zone_role",
            "current_role",
            "base_kind",
            "kind",
            "lifecycle_state",
            "condition",
        )
    )


def _candidate_direction(row: dict[str, Any]) -> str:
    direct = _direction(row.get("direction"))
    if direct:
        return direct
    text = _role_text(row)
    if "DEMAND" in text or "SUPPORT" in text or "DOWNSIDE" in text:
        return "LONG"
    if "SUPPLY" in text or "RESISTANCE" in text or "UPSIDE" in text:
        return "SHORT"
    return ""


def _event_block(event_risk: dict[str, Any]) -> tuple[bool, str]:
    risk = _d(event_risk)
    if not risk:
        return False, "NO_EVENT_VETO"
    if bool(risk.get("blackout_active") or risk.get("blocked") or risk.get("veto")):
        return True, "EVENT_BLACKOUT_ACTIVE"
    level = str(risk.get("level") or risk.get("impact") or risk.get("risk") or "").upper()
    minutes = _f(risk.get("minutes_to_event"))
    if level in {"HIGH", "CRITICAL", "RED"} and minutes is not None and 0 <= minutes <= EVENT_BLACKOUT_MINUTES:
        return True, f"HIGH_IMPACT_EVENT_IN_{minutes:.0f}M"
    return False, "NO_EVENT_VETO"


def _liquidity_near(context: dict[str, Any], direction: str, low: float, high: float) -> list[dict[str, Any]]:
    width = max(high - low, 0.01)
    wanted = "SELL_SIDE" if direction == "LONG" else "BUY_SIDE"
    lower = low - 0.75 * width
    upper = high + 0.75 * width
    found: list[dict[str, Any]] = []
    for raw in list(context.get("liquidity_candidates") or []):
        row = _d(raw)
        px = _f(row.get("price"))
        side = str(row.get("side") or "").upper()
        if px is None or side not in {wanted, "BOTH"}:
            continue
        if lower <= px <= upper:
            found.append(row)
    found.sort(key=lambda row: abs(float(row.get("price") or 0.0) - ((low + high) / 2.0)))
    return found[:5]


def _targets(row: dict[str, Any], context: dict[str, Any], direction: str) -> list[float]:
    raw_targets = list(row.get("targets") or context.get("opposing_targets") or [])
    out: list[float] = []
    for raw in raw_targets:
        if isinstance(raw, dict):
            target_dir = _direction(raw.get("direction"))
            if target_dir and target_dir != direction:
                continue
            value = _f(raw.get("price"))
            if value is None:
                low = _f(raw.get("low"))
                high = _f(raw.get("high"))
                if low is not None and high is not None:
                    value = (low + high) / 2.0
        else:
            value = _f(raw)
        if value is not None:
            out.append(float(value))
    out = sorted(set(out), reverse=direction == "SHORT")
    return out


def _structural_invalidation(row: dict[str, Any], direction: str, low: float, high: float) -> float:
    for key in ("structural_invalidation", "invalidation", "structural_floor", "structural_ceiling"):
        raw = row.get(key)
        if isinstance(raw, dict):
            value = _f(raw.get("price") if raw.get("price") is not None else raw.get("level"))
            if value is None:
                value = _f(raw.get("low") if direction == "LONG" else raw.get("high"))
        else:
            value = _f(raw)
        if value is not None:
            return float(value)
    buffer = max(0.15 * (high - low), 0.25)
    return low - buffer if direction == "LONG" else high + buffer


def _reclaim_level(row: dict[str, Any]) -> float | None:
    for key in ("validation_level", "reclaim_level", "acceptance_level", "confirmation_level"):
        raw = row.get(key)
        if isinstance(raw, dict):
            value = _f(raw.get("price") if raw.get("price") is not None else raw.get("level"))
        else:
            value = _f(raw)
        if value is not None:
            return float(value)
    return None


def _planned_entry(direction: str, price: float, low: float, high: float, row: dict[str, Any]) -> float:
    explicit = _f(row.get("reference_entry") if row.get("reference_entry") is not None else row.get("planned_entry"))
    if explicit is not None:
        return float(explicit)
    if low <= price <= high:
        return price
    return high if direction == "LONG" else low


def _rr(entry: float, invalidation: float, targets: list[float], direction: str) -> float | None:
    if not targets:
        return None
    risk = entry - invalidation if direction == "LONG" else invalidation - entry
    if risk <= 0:
        return None
    valid = [t for t in targets if (t > entry if direction == "LONG" else t < entry)]
    if not valid:
        return None
    first = min(valid) if direction == "LONG" else max(valid)
    reward = first - entry if direction == "LONG" else entry - first
    return reward / risk if reward > 0 else None


def _score(row: dict[str, Any], *, context: dict[str, Any], direction: str, low: float, high: float, price: float) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []
    timeframe = str(row.get("timeframe") or "").upper()
    role = _role_text(row)
    condition = str(row.get("condition") or row.get("lifecycle_state") or "ACTIVE").upper()

    if timeframe == "H4":
        score += 3.0
        reasons.append("H4_LOCATION")
    elif timeframe == "H1":
        score += 2.5
        reasons.append("H1_LOCATION")
    elif timeframe in {"H2", "M30"}:
        score += 1.0

    if any(token in role for token in ("MAIN", "REVERSAL", "SOURCE", "ORIGIN")):
        score += 2.0
        reasons.append("MAIN_REVERSAL_ROLE")
    if condition in {"ACTIVE", "FRESH", "UNTOUCHED", "VALID", "RETEST"}:
        score += 1.0
        reasons.append("STRUCTURALLY_ACTIVE")
    if condition in {"BROKEN", "INVALID", "RETIRED"}:
        score -= 8.0
        reasons.append("BROKEN_ZONE")

    strength = _f(row.get("strength") if row.get("strength") is not None else row.get("score"))
    if strength is not None:
        score += min(max(strength, 0.0), 2.0)
        if strength >= 1.0:
            reasons.append("ZONE_STRENGTH")

    liquidity = _liquidity_near(context, direction, low, high)
    if liquidity:
        score += 2.0
        reasons.append("INTERNAL_LIQUIDITY")

    if low <= price <= high:
        score += 2.0
        reasons.append("PRICE_IN_EFFECTIVE_ZONE")
    else:
        width = max(high - low, 0.01)
        distance = low - price if price < low else price - high
        if distance / width <= PREPARE_DISTANCE_ZONE_WIDTHS:
            score += 0.5
            reasons.append("PRICE_APPROACHING_ZONE")

    touch_count = _f(row.get("touch_count"))
    if touch_count is not None and touch_count >= 3:
        score -= 1.0
        reasons.append("MULTIPLE_TOUCH_PENALTY")

    return round(score, 4), reasons


def _collect_candidates(context: dict[str, Any], price: float) -> list[dict[str, Any]]:
    raw_rows: list[dict[str, Any]] = []
    for key in ("effective_zones", "active_zones"):
        raw_rows.extend(_d(row) for row in list(context.get(key) or []))
    for key in ("main_reversal_zone", "decision_zone"):
        row = _d(context.get(key))
        if row:
            raw_rows.append(row)

    sr = _d(context.get("support_resistance_map"))
    raw_rows.extend(_d(row) for row in list(sr.get("levels") or []))

    seen: set[tuple[str, float, float]] = set()
    candidates: list[dict[str, Any]] = []
    for row in raw_rows:
        direction = _candidate_direction(row)
        band = _band(row)
        if not direction or band is None:
            continue
        low, high = band
        key = (direction, round(low, 4), round(high, 4))
        if key in seen:
            continue
        seen.add(key)

        score, reasons = _score(row, context=context, direction=direction, low=low, high=high, price=price)
        invalidation = _structural_invalidation(row, direction, low, high)
        targets = _targets(row, context, direction)
        entry = _planned_entry(direction, price, low, high, row)
        rr = _rr(entry, invalidation, targets, direction)
        reclaim = _reclaim_level(row)
        liquidity = _liquidity_near(context, direction, low, high)
        candidates.append(
            {
                "zone_id": row.get("zone_id"),
                "direction": direction,
                "timeframe": str(row.get("timeframe") or "HTF").upper(),
                "low": low,
                "high": high,
                "entry_reference": entry,
                "structural_invalidation": invalidation,
                "validation_level": reclaim,
                "targets": targets,
                "liquidity": liquidity,
                "score": score,
                "score_reasons": reasons,
                "rr_first_target": None if rr is None else round(rr, 4),
                "raw_role": _role_text(row),
            }
        )

    candidates.sort(
        key=lambda row: (
            -float(row.get("score") or 0.0),
            -(float(row.get("rr_first_target") or 0.0)),
        )
    )
    return candidates


def _acceptance_closes(context: dict[str, Any]) -> list[float]:
    closes: list[float] = []
    for raw in list(context.get("acceptance_closes") or context.get("recent_closes") or []):
        value = _f(raw.get("close") if isinstance(raw, dict) else raw)
        if value is not None:
            closes.append(float(value))
    return closes


def _structurally_invalidated(candidate: dict[str, Any], context: dict[str, Any]) -> bool:
    if bool(context.get("accepted_beyond_invalidation")):
        return True
    level = float(candidate["structural_invalidation"])
    closes = _acceptance_closes(context)
    if len(closes) < 2:
        return False
    last_two = closes[-2:]
    if candidate["direction"] == "LONG":
        return all(close < level for close in last_two)
    return all(close > level for close in last_two)


def _reclaim_confirmed(candidate: dict[str, Any], context: dict[str, Any]) -> bool:
    explicit = context.get("reclaim_confirmed")
    if explicit is not None:
        return bool(explicit)
    level = _f(candidate.get("validation_level"))
    if level is None:
        return False
    closes = _acceptance_closes(context)
    if not closes:
        return False
    close = closes[-1]
    if candidate["direction"] == "LONG":
        return close >= level
    return close <= level


def _zone_state(candidate: dict[str, Any], price: float) -> str:
    low = float(candidate["low"])
    high = float(candidate["high"])
    if low <= price <= high:
        return "IN_ZONE"
    width = max(high - low, 0.01)
    distance = low - price if price < low else price - high
    if distance / width <= PREPARE_DISTANCE_ZONE_WIDTHS:
        return "APPROACHING"
    return "AWAY"


def _paths(candidate: dict[str, Any]) -> dict[str, Any]:
    direction = candidate["direction"]
    liquidity = [float(row["price"]) for row in candidate.get("liquidity") or [] if _f(row.get("price")) is not None]
    return {
        "primary": {
            "sequence": ["EFFECTIVE_HTF_ZONE", "EARLY_TAKE_RISK", "RECLAIM_VALIDATION", "OPPOSING_HTF_DESTINATION"],
            "direction": direction,
            "entry_band": {"low": candidate["low"], "high": candidate["high"]},
            "validation_level": candidate.get("validation_level"),
            "destination_ladder": list(candidate.get("targets") or []),
        },
        "alternative": {
            "sequence": ["DEEPER_LIQUIDITY_SWEEP", "NO_STRUCTURAL_ACCEPTANCE_BEYOND_INVALIDATION", "RECLAIM_OR_RETURN_TO_ZONE"],
            "liquidity_levels": liquidity,
        },
        "invalidation": {
            "rule": "TWO_ACCEPTANCE_CLOSES_BEYOND_STRUCTURAL_INVALIDATION_OR_EXPLICIT_ACCEPTANCE_FLAG",
            "level": candidate["structural_invalidation"],
        },
    }


def evaluate_afiq_challenger_v395(
    context: dict[str, Any] | None,
    *,
    event_risk: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate V395 challenger state from causal market geometry only."""
    ctx = _d(context)
    price = _f(ctx.get("price_now"))
    base = {
        "contract": CONTRACT,
        "reference_corpus": REFERENCE_CORPUS,
        "execution_authority": False,
        "demo_auto_execution": False,
        "live_execution_enabled": False,
        "live_execution_influence": False,
        "policy": "RESEARCH_SHADOW_ONLY",
    }
    if price is None:
        return {**base, "state": "UNAVAILABLE", "direction": "WAIT", "reason": "PRICE_UNAVAILABLE"}

    candidates = _collect_candidates(ctx, price)
    if not candidates:
        return {**base, "state": "WAIT_NO_EFFECTIVE_ZONE", "direction": "WAIT", "candidates": []}

    selected = candidates[0]
    direction = str(selected["direction"])
    zone_state = _zone_state(selected, price)
    event_blocked, event_reason = _event_block(_d(event_risk or ctx.get("event_risk")))
    invalidated = _structurally_invalidated(selected, ctx)
    confirmed = _reclaim_confirmed(selected, ctx)
    score = float(selected.get("score") or 0.0)
    rr = _f(selected.get("rr_first_target"))
    rr_ok = rr is not None and rr >= MIN_RR

    if invalidated:
        state = "INVALIDATED"
        reason = "STRUCTURAL_ACCEPTANCE_BEYOND_INVALIDATION"
    elif event_blocked:
        state = "BLOCKED_EVENT"
        reason = event_reason
    elif confirmed:
        state = "CONFIRMED"
        reason = "RECLAIM_OR_ACCEPTANCE_CONFIRMED"
    elif zone_state == "IN_ZONE" and score >= MIN_EFFECTIVE_SCORE and rr_ok:
        state = "EARLY_TAKE_RISK"
        reason = "EFFECTIVE_ZONE_PLUS_LIQUIDITY_AND_RR_BEFORE_RECLAIM"
    elif zone_state == "IN_ZONE":
        state = "WATCH_ZONE"
        reason = "ZONE_REACHED_BUT_QUALITY_OR_RR_BELOW_THRESHOLD"
    elif zone_state == "APPROACHING":
        state = "PREPARE"
        reason = "APPROACHING_EFFECTIVE_ZONE"
    else:
        state = "WAIT"
        reason = "EFFECTIVE_ZONE_NOT_REACHED"

    return {
        **base,
        "state": state,
        "direction": direction,
        "reason": reason,
        "price_now": price,
        "zone_state": zone_state,
        "effective_zone": selected,
        "effective_score": score,
        "min_effective_score": MIN_EFFECTIVE_SCORE,
        "rr_first_target": rr,
        "min_rr": MIN_RR,
        "event": {"blocked": event_blocked, "reason": event_reason},
        "reclaim_confirmed": confirmed,
        "structurally_invalidated": invalidated,
        "paths": _paths(selected),
        "candidate_count": len(candidates),
        "candidates": candidates[:6],
        "provenance_guard": {
            "afiq_prices_used_as_runtime_inputs": False,
            "reference_data_role": "CALIBRATION_AND_REGRESSION_ONLY",
            "no_lookahead_required": True,
        },
    }

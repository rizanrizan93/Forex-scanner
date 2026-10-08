from __future__ import annotations

"""V406 hierarchy layer for the tiered XAUUSD reaction map.

V405 answers *where are the nearby BUY/SELL reaction zones?*.
V406 adds role semantics so the dashboard can distinguish:

- MAIN_REVERSAL: H1/H4 structural supply/demand expected to matter for a major turn;
- TRANSITION_DECISION: local M15/M30/M5 or SR band that can change the internal leg;
- STRUCTURAL_EXTENSION: the next deeper H1/H4 zone after the main reversal zone;
- REACTION: useful local geometry, but not a major reversal anchor.

The logic is a causal reconstruction from scanner geometry.  It does not claim
access to any proprietary indicator formula and has no broker execution authority.
"""

from math import isfinite
from typing import Any

from .xau_whalezone_reconstruction_v405 import evaluate_whalezone_reconstruction_v405

CONTRACT = "XAU_RIZAN_ZONE_HIERARCHY_V406"
MODE = "ZONE_ROLE_HIERARCHY"
STRUCTURAL_TFS = {"H4", "H1"}
TRANSITION_TFS = {"M30", "M15", "M5", "LOCAL"}


def _d(value: Any) -> dict[str, Any]:
    return dict(value or {})


def _f(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _band(row: dict[str, Any]) -> tuple[float, float] | None:
    low = _f(row.get("low"))
    high = _f(row.get("high"))
    if low is None or high is None:
        low = _f(row.get("band_low"))
        high = _f(row.get("band_high"))
    if low is None or high is None:
        center = _f(row.get("price"))
        if center is None:
            return None
        low = high = center
    if high < low:
        low, high = high, low
    return float(low), float(high)


def _contains(zone: dict[str, Any], price: float) -> bool:
    band = _band(zone)
    if band is None:
        return False
    low, high = band
    return low <= price <= high


def _zone_key(zone: dict[str, Any]) -> tuple[str, float, float, str]:
    band = _band(zone) or (0.0, 0.0)
    return (
        str(zone.get("direction") or "").upper(),
        round(float(band[0]), 4),
        round(float(band[1]), 4),
        str(zone.get("zone_id") or ""),
    )


def _is_structural(zone: dict[str, Any]) -> bool:
    tf = str(zone.get("timeframe") or "").upper()
    source = str(zone.get("source_type") or "").upper()
    return tf in STRUCTURAL_TFS and source == "SD"


def _pick_main(zones: list[dict[str, Any]]) -> dict[str, Any]:
    for row in zones:
        if _is_structural(row):
            return dict(row)
    return dict(zones[0]) if zones else {}


def _next_structural(zones: list[dict[str, Any]], main: dict[str, Any]) -> dict[str, Any]:
    main_key = _zone_key(main) if main else None
    passed_main = False
    for row in zones:
        if main_key is not None and _zone_key(row) == main_key:
            passed_main = True
            continue
        if passed_main and _is_structural(row):
            return dict(row)
    return {}


def _infer_direction(row: dict[str, Any]) -> str:
    explicit = str(row.get("direction") or "").upper()
    if explicit in {"LONG", "SHORT"}:
        return explicit
    text = " ".join(
        str(row.get(key) or "").upper()
        for key in (
            "current_role",
            "base_kind",
            "kind",
            "lifecycle_state",
            "role",
        )
    )
    if "SUPPORT" in text or "DEMAND" in text or "DOWNSIDE" in text:
        return "LONG"
    if "RESISTANCE" in text or "SUPPLY" in text or "UPSIDE" in text:
        return "SHORT"
    return "UNKNOWN"


def _candidate_from_raw(raw: dict[str, Any], *, source_type: str) -> dict[str, Any] | None:
    row = _d(raw)
    if str(row.get("condition") or "").upper() in {"BROKEN", "INVALID", "RETIRED"}:
        return None
    if bool(row.get("intraday_quarantined")):
        return None
    band = _band(row)
    if band is None:
        return None
    low, high = band
    if high <= low:
        return None
    direction = _infer_direction(row)
    if direction not in {"LONG", "SHORT"}:
        return None
    return {
        "direction": direction,
        "low": low,
        "high": high,
        "center": (low + high) / 2.0,
        "timeframe": str(row.get("timeframe") or "LOCAL").upper(),
        "source_type": source_type,
        "lifecycle_state": str(row.get("lifecycle_state") or row.get("condition") or "ACTIVE").upper(),
        "zone_id": row.get("zone_id"),
        "strength": _f(row.get("strength")) or _f(row.get("score")),
    }


def _raw_transition_candidates(sd: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    explicit = _d(sd.get("decision_zone"))
    if explicit:
        candidate = _candidate_from_raw(explicit, source_type="DECISION")
        if candidate:
            rows.append(candidate)

    for raw in list(sd.get("active_zones") or []):
        candidate = _candidate_from_raw(_d(raw), source_type="SD")
        if candidate:
            rows.append(candidate)

    sr = _d(sd.get("support_resistance_map"))
    sr_rows = [_d(row) for row in list(sr.get("levels") or [])]
    for name in ("nearest_support", "nearest_resistance"):
        fallback = _d(sr.get(name))
        if fallback:
            sr_rows.append(fallback)
    for raw in sr_rows:
        candidate = _candidate_from_raw(raw, source_type="SR")
        if candidate:
            rows.append(candidate)

    seen: set[tuple[str, float, float]] = set()
    unique: list[dict[str, Any]] = []
    for row in rows:
        key = (
            str(row.get("direction") or ""),
            round(float(row["low"]), 4),
            round(float(row["high"]), 4),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    return unique


def _same_geometry(a: dict[str, Any], b: dict[str, Any], *, tolerance: float = 0.50) -> bool:
    if not a or not b:
        return False
    ab = _band(a)
    bb = _band(b)
    if ab is None or bb is None:
        return False
    return abs(ab[0] - bb[0]) <= tolerance and abs(ab[1] - bb[1]) <= tolerance


def _decision_zone(
    sd: dict[str, Any],
    *,
    price: float,
    main_buy: dict[str, Any],
    main_sell: dict[str, Any],
) -> dict[str, Any]:
    buy_band = _band(main_buy)
    sell_band = _band(main_sell)
    if buy_band is None or sell_band is None:
        return {}

    corridor_low = buy_band[1]
    corridor_high = sell_band[0]
    if corridor_low >= corridor_high:
        return {}

    candidates: list[dict[str, Any]] = []
    for row in _raw_transition_candidates(sd):
        if _same_geometry(row, main_buy) or _same_geometry(row, main_sell):
            continue
        low, high = float(row["low"]), float(row["high"])
        center = float(row["center"])
        if center < corridor_low or center > corridor_high:
            continue
        tf = str(row.get("timeframe") or "LOCAL").upper()
        source = str(row.get("source_type") or "").upper()
        score = 0.0
        if low <= price <= high:
            score += 8.0
        else:
            distance = min(abs(price - low), abs(price - high))
            corridor_width = max(corridor_high - corridor_low, 1.0)
            score += max(0.0, 4.0 - 8.0 * distance / corridor_width)
        if tf in {"M15", "M30"}:
            score += 3.0
        elif tf in {"M5", "LOCAL"}:
            score += 1.5
        if source in {"SR", "DECISION"}:
            score += 2.0
        if "ACTIVE" in str(row.get("lifecycle_state") or ""):
            score += 0.5
        item = dict(row)
        item["role_score"] = round(score, 4)
        item["zone_role"] = "TRANSITION_DECISION"
        candidates.append(item)

    if not candidates:
        return {}
    candidates.sort(key=lambda row: (-float(row.get("role_score") or 0.0), abs(float(row["center"]) - price)))
    return candidates[0]


def _m15_close(sd: dict[str, Any]) -> float | None:
    for key in ("m15_close", "latest_m15_close"):
        value = _f(sd.get(key))
        if value is not None:
            return value
    for parent_key in ("m15", "validation", "micro_confirmation"):
        parent = _d(sd.get(parent_key))
        for key in ("m15_close", "close", "last_close"):
            value = _f(parent.get(key))
            if value is not None:
                return value
    return None


def _phase(
    *,
    price: float,
    m15_close: float | None,
    main_buy: dict[str, Any],
    decision: dict[str, Any],
    main_sell: dict[str, Any],
) -> str:
    if main_buy and _contains(main_buy, price):
        return "AT_MAIN_BUY"
    if main_sell and _contains(main_sell, price):
        return "AT_MAIN_SELL"
    if decision and _contains(decision, price):
        return "TESTING_DECISION_ZONE"

    decision_band = _band(decision)
    if decision_band is not None:
        low, high = decision_band
        direction = str(decision.get("direction") or "").upper()
        if direction == "SHORT":
            if m15_close is not None and m15_close > high:
                return "INTERNAL_BULLISH_TRANSITION"
            if price > high:
                return "ABOVE_DECISION_AWAIT_M15_ACCEPTANCE"
            if m15_close is not None and m15_close < low:
                return "BEARISH_REJECTION_FROM_DECISION"
        elif direction == "LONG":
            if m15_close is not None and m15_close < low:
                return "INTERNAL_BEARISH_TRANSITION"
            if price < low:
                return "BELOW_DECISION_AWAIT_M15_ACCEPTANCE"
            if m15_close is not None and m15_close > high:
                return "BULLISH_REJECTION_FROM_DECISION"

    buy_band = _band(main_buy)
    sell_band = _band(main_sell)
    if buy_band is not None and sell_band is not None and buy_band[1] < price < sell_band[0]:
        return "BETWEEN_MAIN_ZONES"
    return "OUTSIDE_STRUCTURAL_CORRIDOR"


def _annotate_roles(
    zones: list[dict[str, Any]],
    *,
    main: dict[str, Any],
    decision: dict[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw in zones:
        row = dict(raw)
        if main and _same_geometry(row, main):
            role = "MAIN_REVERSAL"
        elif decision and _same_geometry(row, decision):
            role = "TRANSITION_DECISION"
        elif _is_structural(row):
            role = "STRUCTURAL_EXTENSION"
        else:
            role = "REACTION"
        row["zone_role"] = role
        rows.append(row)
    return rows


def evaluate_zone_hierarchy_v406(sd_eval: dict[str, Any] | None) -> dict[str, Any]:
    sd = _d(sd_eval)
    base = evaluate_whalezone_reconstruction_v405(sd)
    price = _f(base.get("price_now"))
    if price is None:
        return {
            "contract": CONTRACT,
            "mode": MODE,
            "state": "UNAVAILABLE",
            "phase": "UNAVAILABLE",
            "reason": "PRICE_UNAVAILABLE",
            "execution_authority": False,
            "demo_auto_execution": False,
            "live_execution_enabled": False,
            "proprietary_formula_claimed": False,
        }

    buy_zones = [_d(row) for row in list(base.get("buy_zones") or [])]
    sell_zones = [_d(row) for row in list(base.get("sell_zones") or [])]
    main_buy = _pick_main(buy_zones)
    main_sell = _pick_main(sell_zones)
    next_buy = _next_structural(buy_zones, main_buy)
    next_sell = _next_structural(sell_zones, main_sell)

    if not main_buy or not main_sell:
        return {
            "contract": CONTRACT,
            "mode": MODE,
            "state": "ONE_SIDED_ONLY",
            "phase": "ONE_SIDED_ONLY",
            "reason": "MAIN_BUY_OR_SELL_ZONE_MISSING",
            "price_now": price,
            "main_buy": main_buy,
            "main_sell": main_sell,
            "buy_zones": _annotate_roles(buy_zones, main=main_buy, decision={}),
            "sell_zones": _annotate_roles(sell_zones, main=main_sell, decision={}),
            "execution_authority": False,
            "demo_auto_execution": False,
            "live_execution_enabled": False,
            "proprietary_formula_claimed": False,
        }

    decision = _decision_zone(
        sd,
        price=price,
        main_buy=main_buy,
        main_sell=main_sell,
    )
    m15 = _m15_close(sd)
    phase = _phase(
        price=price,
        m15_close=m15,
        main_buy=main_buy,
        decision=decision,
        main_sell=main_sell,
    )

    buy_band = _band(main_buy)
    sell_band = _band(main_sell)
    decision_band = _band(decision)
    assert buy_band is not None and sell_band is not None

    transition_gate: dict[str, Any] = {"state": "UNAVAILABLE"}
    path: dict[str, Any] = {
        "downside_main_reversal": {"low": buy_band[0], "high": buy_band[1]},
        "upside_main_reversal": {"low": sell_band[0], "high": sell_band[1]},
    }
    if decision_band is not None:
        dlow, dhigh = decision_band
        direction = str(decision.get("direction") or "").upper()
        transition_gate = {
            "state": "MAPPED",
            "direction": direction,
            "low": dlow,
            "high": dhigh,
            "m15_close": m15,
            "bullish_acceptance_above": dhigh,
            "bearish_acceptance_below": dlow,
            "acceptance_required": "M15_CLOSE",
        }
        if direction == "SHORT":
            path.update(
                {
                    "primary_if_rejected": "RETURN_TO_MAIN_BUY",
                    "primary_target": buy_band[1],
                    "alternative_if_accepted_above": "ROTATE_TO_MAIN_SELL",
                    "alternative_target": sell_band[0],
                }
            )
        elif direction == "LONG":
            path.update(
                {
                    "primary_if_rejected": "RETURN_TO_MAIN_SELL",
                    "primary_target": sell_band[0],
                    "alternative_if_accepted_below": "ROTATE_TO_MAIN_BUY",
                    "alternative_target": buy_band[1],
                }
            )

    structural_gate = {
        "bullish_major_reversal_above": sell_band[1],
        "bearish_major_reversal_below": buy_band[0],
        "acceptance_required": "H1_OR_REPEATED_M15_ACCEPTANCE",
        "note": "Decision-zone break changes the internal leg; the opposite MAIN_REVERSAL zone remains the major structural gate.",
    }

    return {
        "contract": CONTRACT,
        "mode": MODE,
        "state": "HIERARCHY_MAPPED",
        "phase": phase,
        "reason": "MAIN_REVERSAL_AND_TRANSITION_ROLES_SEPARATED",
        "price_now": price,
        "m15_close": m15,
        "main_buy": main_buy,
        "decision_zone": decision,
        "main_sell": main_sell,
        "next_buy": next_buy,
        "next_sell": next_sell,
        "buy_zones": _annotate_roles(buy_zones, main=main_buy, decision=decision),
        "sell_zones": _annotate_roles(sell_zones, main=main_sell, decision=decision),
        "transition_gate": transition_gate,
        "structural_gate": structural_gate,
        "path": path,
        "role_model": {
            "MAIN_REVERSAL": "H1/H4 structural S/D anchor",
            "TRANSITION_DECISION": "local band that changes the internal leg after acceptance",
            "STRUCTURAL_EXTENSION": "next H1/H4 structural zone after the main anchor",
            "REACTION": "local reaction geometry; not treated as major reversal by itself",
        },
        "validation_status": "RECONSTRUCTION_REQUIRES_REPLAY_AND_FORWARD_CALIBRATION",
        "reconstruction_basis": "USER_SHARED_VISUAL_HIERARCHY_PLUS_CAUSAL_SD_SR_GEOMETRY",
        "proprietary_formula_claimed": False,
        "execution_authority": False,
        "demo_auto_execution": False,
        "live_execution_enabled": False,
    }


__all__ = ["CONTRACT", "MODE", "evaluate_zone_hierarchy_v406"]

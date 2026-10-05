from __future__ import annotations

"""V403 scanner bridge for the generalized AFIQ-pattern challenger.

The bridge converts the current causal XAU supply/demand + local-reversal
snapshot into the neutral geometry expected by V395. It deliberately does not
load the AFIQ reference corpus and does not copy any benchmark price into
runtime logic.

This is scanner decision-support/shadow integration only. It has no LIVE or
DEMO execution authority.
"""

from math import isfinite
from typing import Any

from .xau_afiq_challenger_v395 import evaluate_afiq_challenger_v395
from .xau_simple_reversal_engine_v390 import evaluate_simple_reversal

CONTRACT = "XAU_RIZAN_AFIQ_SCANNER_BRIDGE_V403"
SOURCE_ENGINE = "XAU_RIZAN_AFIQ_CHALLENGER_V395"
MODE = "SHADOW"


def _d(value: Any) -> dict[str, Any]:
    return dict(value or {})


def _f(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if isfinite(out) else None


def _zone_key(row: dict[str, Any]) -> tuple[str, float | None, float | None]:
    return (
        str(row.get("direction") or "").upper(),
        _f(row.get("low")),
        _f(row.get("high")),
    )


def _matching_raw_zone(sd: dict[str, Any], zone: dict[str, Any]) -> dict[str, Any]:
    zone_id = zone.get("zone_id")
    if zone_id:
        for raw in list(sd.get("active_zones") or []):
            row = _d(raw)
            if row.get("zone_id") == zone_id:
                return row
    wanted = _zone_key(zone)
    for raw in list(sd.get("active_zones") or []):
        row = _d(raw)
        if _zone_key(row) == wanted:
            return row
    return {}


def _invalidation(zone: dict[str, Any], atr: float) -> float | None:
    low = _f(zone.get("low"))
    high = _f(zone.get("high"))
    if low is None or high is None or high <= low:
        return None
    raw = _f(zone.get("structural_invalidation") or zone.get("invalidation"))
    if raw is not None:
        return raw
    buffer = max(0.12 * atr, 0.15 * (high - low))
    return low - buffer if str(zone.get("direction") or "").upper() == "LONG" else high + buffer


def _opposing_target(direction: str, long_zone: dict[str, Any], short_zone: dict[str, Any]) -> float | None:
    if direction == "LONG" and short_zone:
        return _f(short_zone.get("low"))
    if direction == "SHORT" and long_zone:
        return _f(long_zone.get("high"))
    return None


def _validation_level(
    sd: dict[str, Any],
    *,
    direction: str,
    low: float,
    high: float,
    target: float | None,
    raw_zone: dict[str, Any],
) -> float | None:
    for key in ("validation_level", "reclaim_level", "acceptance_level", "confirmation_level"):
        raw = raw_zone.get(key)
        if isinstance(raw, dict):
            value = _f(raw.get("price") if raw.get("price") is not None else raw.get("level"))
        else:
            value = _f(raw)
        if value is not None:
            return value

    candidates: list[float] = []
    if direction == "LONG":
        for raw in list(sd.get("liquidity_candidates") or []):
            row = _d(raw)
            px = _f(row.get("price"))
            side = str(row.get("side") or "").upper()
            if px is None or side not in {"BUY_SIDE", "BOTH"} or px <= high:
                continue
            if target is None or px <= target:
                candidates.append(px)
        return min(candidates) if candidates else None

    for raw in list(sd.get("liquidity_candidates") or []):
        row = _d(raw)
        px = _f(row.get("price"))
        side = str(row.get("side") or "").upper()
        if px is None or side not in {"SELL_SIDE", "BOTH"} or px >= low:
            continue
        if target is None or px >= target:
            candidates.append(px)
    return max(candidates) if candidates else None


def _acceptance_closes(sd: dict[str, Any]) -> list[float]:
    for key in ("acceptance_closes", "recent_closes", "h1_recent_closes"):
        raw_rows = list(sd.get(key) or [])
        if not raw_rows:
            continue
        out: list[float] = []
        for raw in raw_rows:
            value = _f(raw.get("close") if isinstance(raw, dict) else raw)
            if value is not None:
                out.append(value)
        if out:
            return out[-4:]
    return []


def _event_risk(sd: dict[str, Any], override: dict[str, Any] | None) -> dict[str, Any]:
    if override:
        return _d(override)
    for key in ("event_risk", "macro_event_risk", "news_risk"):
        row = _d(sd.get(key))
        if row:
            return row
    return {}


def _synth_zone(
    sd: dict[str, Any],
    *,
    zone: dict[str, Any],
    long_zone: dict[str, Any],
    short_zone: dict[str, Any],
    atr: float,
) -> dict[str, Any]:
    if not zone:
        return {}
    direction = str(zone.get("direction") or "").upper()
    low = _f(zone.get("low"))
    high = _f(zone.get("high"))
    if direction not in {"LONG", "SHORT"} or low is None or high is None or high <= low:
        return {}

    raw_zone = _matching_raw_zone(sd, zone)
    target = _opposing_target(direction, long_zone, short_zone)
    invalidation = _invalidation({**zone, **raw_zone, "direction": direction}, atr)
    validation = _validation_level(
        sd,
        direction=direction,
        low=low,
        high=high,
        target=target,
        raw_zone=raw_zone,
    )
    lifecycle = str(
        zone.get("lifecycle_state")
        or raw_zone.get("lifecycle_state")
        or raw_zone.get("condition")
        or "ACTIVE"
    ).upper()

    return {
        "zone_id": zone.get("zone_id") or raw_zone.get("zone_id"),
        "direction": direction,
        "timeframe": str(zone.get("timeframe") or raw_zone.get("timeframe") or "LOCAL").upper(),
        "low": low,
        "high": high,
        "role": "MAIN_REVERSAL_DEMAND" if direction == "LONG" else "MAIN_REVERSAL_SUPPLY",
        "condition": lifecycle,
        "strength": _f(zone.get("strength") if zone.get("strength") is not None else zone.get("score")) or 1.0,
        "touch_count": raw_zone.get("touch_count") or _d(raw_zone.get("lifecycle")).get("touch_count"),
        "structural_invalidation": invalidation,
        "validation_level": validation,
        "targets": [] if target is None else [target],
        "source_type": zone.get("source_type"),
        "confirmed_flip": bool(zone.get("confirmed_flip") or raw_zone.get("confirmed_flip")),
    }


def build_afiq_scanner_context_v403(sd_eval: dict[str, Any] | None) -> dict[str, Any]:
    """Build a causal V395 context from the scanner's current V342/V390 geometry."""
    sd = _d(sd_eval)
    plan = evaluate_simple_reversal(sd)
    price = _f(plan.get("price_now") if plan.get("price_now") is not None else sd.get("price_now"))
    atr = _f(plan.get("atr_reference")) or 10.0
    long_zone = _d(plan.get("long_zone"))
    short_zone = _d(plan.get("short_zone"))

    rows: list[dict[str, Any]] = []
    for zone in (long_zone, short_zone):
        row = _synth_zone(
            sd,
            zone=zone,
            long_zone=long_zone,
            short_zone=short_zone,
            atr=atr,
        )
        if row:
            rows.append(row)

    context = {
        "price_now": price,
        "effective_zones": rows,
        "liquidity_candidates": list(sd.get("liquidity_candidates") or []),
        "support_resistance_map": _d(sd.get("support_resistance_map")),
        "acceptance_closes": _acceptance_closes(sd),
        "event_risk": _event_risk(sd, None),
        "v390_plan": plan,
    }
    return context


def _same_zone(candidate: dict[str, Any], zone: dict[str, Any]) -> bool:
    if not candidate or not zone:
        return False
    if candidate.get("zone_id") and zone.get("zone_id"):
        return candidate.get("zone_id") == zone.get("zone_id")
    return _zone_key(candidate) == _zone_key(zone)


def evaluate_afiq_scanner_bridge_v403(
    sd_eval: dict[str, Any] | None,
    *,
    event_risk: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return compact AFIQ-style scanner decision state without execution authority."""
    sd = _d(sd_eval)
    context = build_afiq_scanner_context_v403(sd)
    if event_risk:
        context["event_risk"] = _d(event_risk)

    result = evaluate_afiq_challenger_v395(context, event_risk=context.get("event_risk"))
    effective = _d(result.get("effective_zone"))
    plan = _d(context.get("v390_plan"))

    # V403 makes the AFIQ hypothesis explicit: an anticipatory entry requires a
    # nearby sweep/liquidity reference. V395's generic score alone is not enough.
    if result.get("state") == "EARLY_TAKE_RISK" and not list(effective.get("liquidity") or []):
        result = {
            **result,
            "state": "WATCH_ZONE",
            "reason": "V403_NEARBY_LIQUIDITY_REQUIRED_FOR_EARLY_ENTRY",
        }

    # A causal local confirmed flip is accepted as post-entry validation. It is
    # not required for the first anticipatory entry.
    selected_v390 = _d(plan.get("selected_zone"))
    if (
        result.get("state") not in {"INVALIDATED", "BLOCKED_EVENT", "UNAVAILABLE"}
        and _same_zone(effective, selected_v390)
        and bool(selected_v390.get("confirmed_flip"))
    ):
        result = {
            **result,
            "state": "CONFIRMED",
            "reason": "V403_CAUSAL_LOCAL_FLIP_CONFIRMED",
            "reclaim_confirmed": True,
        }

    entry_band = {
        "low": effective.get("low"),
        "high": effective.get("high"),
    } if effective else {}

    return {
        "contract": CONTRACT,
        "mode": MODE,
        "execution_authority": False,
        "demo_auto_execution": False,
        "live_execution_enabled": False,
        "source_engine": SOURCE_ENGINE,
        "state": result.get("state", "UNAVAILABLE"),
        "direction": result.get("direction", "WAIT"),
        "reason": result.get("reason", "NO_RESULT"),
        "price_now": result.get("price_now"),
        "entry_band": entry_band,
        "entry_reference": effective.get("entry_reference") if effective else None,
        "structural_invalidation": effective.get("structural_invalidation") if effective else None,
        "validation_level": effective.get("validation_level") if effective else None,
        "targets": list(effective.get("targets") or []) if effective else [],
        "liquidity": list(effective.get("liquidity") or []) if effective else [],
        "effective_score": result.get("effective_score"),
        "rr_first_target": result.get("rr_first_target"),
        "zone_state": result.get("zone_state"),
        "paths": _d(result.get("paths")),
        "event": _d(result.get("event")),
        "candidate_count": result.get("candidate_count", 0),
        "v390_state": plan.get("state"),
        "v390_direction": plan.get("direction"),
        "validation_status": "SCANNER_SHADOW_INTEGRATED_NOT_EXECUTION_PROMOTED",
        "provenance_guard": {
            "reference_corpus_loaded_at_runtime": False,
            "benchmark_prices_used_at_runtime": False,
            "market_geometry_only": True,
            "no_lookahead_required": True,
        },
        "raw_challenger": result,
    }

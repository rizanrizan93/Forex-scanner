from __future__ import annotations

from math import isfinite
from typing import Any

CONTRACT = "XAU_RIZAN_MACRO_SHOCK_ATTRIBUTION_V252"
CORE_MAX_AGE_SECONDS = 15 * 60
MOVE_THRESHOLD_PCT = 0.15


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if isfinite(out) else None


def _fresh_signal(
    *,
    value: Any,
    age_seconds: Any,
    max_age_seconds: float,
) -> tuple[float | None, str]:
    numeric = _number(value)
    age = _number(age_seconds)
    if numeric is None:
        return None, "MISSING"
    if age is None or age < 0:
        return None, "FRESHNESS_UNKNOWN"
    if age > float(max_age_seconds):
        return None, "STALE"
    return numeric, "FRESH"


def _gold_macro_alignment(source: str, value: float, move_direction: str) -> str:
    if abs(value) < 1e-12:
        return "NEUTRAL"

    # Higher USD / Treasury / real yields are normally a headwind for
    # non-yielding gold; lower readings are normally supportive. This engine
    # treats that relationship as corroboration, never proof of causality.
    macro_gold_direction = "SHORT" if value > 0 else "LONG"
    return "ALIGNED" if macro_gold_direction == move_direction else "OPPOSED"


def evaluate_xau_macro_shock_attribution(
    *,
    xau_change_pct: Any,
    dxy_change_pct: Any = None,
    dxy_age_seconds: Any = None,
    us2y_change_bps: Any = None,
    us2y_age_seconds: Any = None,
    us10y_change_bps: Any = None,
    us10y_age_seconds: Any = None,
    real_yield_change_bps: Any = None,
    real_yield_age_seconds: Any = None,
    event_state: str | None = None,
    technical_evidence: tuple[str, ...] | list[str] = (),
    dom_direction: str | None = None,
    max_age_seconds: float = CORE_MAX_AGE_SECONDS,
    move_threshold_pct: float = MOVE_THRESHOLD_PCT,
) -> dict[str, Any]:
    """Classify XAU shock attribution without converting correlation into cause.

    Positive DXY/yield changes are treated as bearish-gold corroboration and
    negative changes as bullish-gold corroboration. Stale or freshness-unknown
    inputs are excluded from directional evidence.
    """
    xau = _number(xau_change_pct)
    if xau is None:
        return {
            "contract": CONTRACT,
            "state": "XAU_MOVE_UNAVAILABLE",
            "move_detected": False,
            "attribution_confidence": "LOW",
            "claim_mode": "INSUFFICIENT_EVIDENCE_NO_CAUSAL_CLAIM",
            "execution_influence": False,
            "execution_authority": False,
            "promotion_authority": False,
        }

    move_direction = "SHORT" if xau < 0 else "LONG"
    move_detected = abs(xau) >= float(move_threshold_pct)

    raw = {
        "DXY": (dxy_change_pct, dxy_age_seconds),
        "US2Y": (us2y_change_bps, us2y_age_seconds),
        "US10Y": (us10y_change_bps, us10y_age_seconds),
        "REAL_YIELD": (real_yield_change_bps, real_yield_age_seconds),
    }

    sources: dict[str, Any] = {}
    aligned = 0
    opposed = 0
    fresh_count = 0
    for name, (value, age) in raw.items():
        numeric, freshness = _fresh_signal(
            value=value,
            age_seconds=age,
            max_age_seconds=max_age_seconds,
        )
        alignment = None
        if numeric is not None:
            fresh_count += 1
            alignment = _gold_macro_alignment(name, numeric, move_direction)
            if alignment == "ALIGNED":
                aligned += 1
            elif alignment == "OPPOSED":
                opposed += 1
        sources[name] = {
            "value": numeric,
            "freshness": freshness,
            "alignment": alignment,
        }

    technical = tuple(str(item).strip() for item in technical_evidence if str(item).strip())
    event = str(event_state or "UNKNOWN").upper().strip()
    dom = str(dom_direction or "UNKNOWN").upper().strip()
    dom_aligned = (
        (move_direction == "SHORT" and dom in {"SELLER", "SELLER_CONTROL", "BEARISH"})
        or (move_direction == "LONG" and dom in {"BUYER", "BUYER_CONTROL", "BULLISH"})
    )

    if not move_detected:
        state = "NO_MATERIAL_XAU_SHOCK"
        confidence = "LOW"
    elif aligned >= 3 and opposed == 0 and (technical or dom_aligned):
        state = "MACRO_TECHNICAL_CORROBORATED"
        confidence = "HIGH"
    elif aligned >= 2 and opposed <= 1:
        state = "MACRO_CORROBORATED"
        confidence = "MEDIUM"
    elif aligned >= 1 or technical or dom_aligned:
        state = "PARTIAL_CORROBORATION"
        confidence = "LOW"
    else:
        state = "UNATTRIBUTED_MOVE"
        confidence = "LOW"

    event_context = event in {"PRE_EVENT", "EVENT_WINDOW", "POST_EVENT", "HIGH_RISK"}

    return {
        "contract": CONTRACT,
        "state": state,
        "move_detected": bool(move_detected),
        "move_direction": move_direction,
        "xau_change_pct": xau,
        "attribution_confidence": confidence,
        "claim_mode": "CORROBORATION_ONLY_NOT_PROVEN_CAUSE",
        "aligned_macro_sources": aligned,
        "opposed_macro_sources": opposed,
        "fresh_macro_sources": fresh_count,
        "core_sources_expected": 3,
        "source_evidence": sources,
        "technical_evidence": list(technical),
        "dom_direction": dom,
        "dom_aligned": bool(dom_aligned),
        "event_state": event,
        "event_context_present": bool(event_context),
        "execution_influence": False,
        "execution_authority": False,
        "promotion_authority": False,
        "interpretation": (
            "V252 attributes an XAU shock only as corroborated context. DXY and "
            "Treasury/real-yield moves must be fresh to count. Event timing, DOM "
            "and technical structure can strengthen context but cannot by "
            "themselves prove a macro cause."
        ),
    }

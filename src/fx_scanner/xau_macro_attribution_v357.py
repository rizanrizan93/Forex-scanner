from __future__ import annotations

from datetime import UTC, datetime
from math import isfinite
from typing import Any, Mapping

CONTRACT = "XAU_RIZAN_BROADER_MACRO_ATTRIBUTION_V357"

COMPONENT_WEIGHTS = {
    "USD_BROAD_PROXY": 0.25,
    "US2Y": 0.25,
    "US10Y": 0.10,
    "REAL_YIELD_10Y": 0.20,
    "EVENT_CONSENSUS": 0.20,
}

SCALES = {
    "USD_BROAD_PROXY": 0.50,  # daily percent move
    "US2Y": 8.0,             # basis points
    "US10Y": 8.0,            # basis points
    "REAL_YIELD_10Y": 8.0,   # basis points
}


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _clamp(value: float, low: float = -100.0, high: float = 100.0) -> float:
    return max(low, min(high, float(value)))


def _gold_score_from_delta(name: str, delta: Any) -> float | None:
    numeric = _number(delta)
    if numeric is None or name not in SCALES:
        return None
    # Higher USD / nominal yields / real yields are ordinarily gold headwinds.
    return _clamp(-100.0 * numeric / SCALES[name])


def _event_time(value: Any) -> float:
    if not value:
        return float("-inf")
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return float("-inf")
    if parsed.tzinfo is None:
        return float("-inf")
    return parsed.astimezone(UTC).timestamp()


def _event_component(event_context: Mapping[str, Any] | None) -> dict[str, Any]:
    context = dict(event_context or {})
    focal = dict(context.get("focal_event") or {})
    released = [
        dict(item or {})
        for item in list(context.get("upcoming_events") or [])
        if isinstance(item, Mapping)
        and item.get("actual") is not None
        and str(item.get("gold_bias_confidence") or "").upper() == "POST_RELEASE"
    ]
    if released:
        released.sort(
            key=lambda row: (
                _event_time(row.get("scheduled_at_wib") or row.get("scheduled_at")),
                1 if str(row.get("category") or "").upper() == "EMPLOYMENT" else 0,
            ),
            reverse=True,
        )
        focal = released[0]
    bias = str(focal.get("gold_bias") or "NEUTRAL_UNKNOWN").upper()
    confidence = str(focal.get("gold_bias_confidence") or "LOW").upper()
    mapping = {
        "GOLD_BULLISH": 70.0 if confidence == "POST_RELEASE" else 30.0,
        "GOLD_BEARISH": -70.0 if confidence == "POST_RELEASE" else -30.0,
        "NEUTRAL": 0.0,
        "NEUTRAL_UNKNOWN": 0.0,
        "TWO_SIDED": 0.0,
    }
    score = mapping.get(bias, 0.0)
    usable = bool(focal)
    return {
        "name": "EVENT_CONSENSUS",
        "available": usable,
        "score": score if usable else None,
        "bias": bias,
        "confidence": confidence,
        "event": focal.get("title"),
        "scheduled_at": focal.get("scheduled_at"),
        "basis": focal.get("gold_bias_basis"),
        "source": focal.get("source"),
    }


def _direction(score: float | None) -> str:
    if score is None:
        return "UNAVAILABLE"
    if score >= 20.0:
        return "BULLISH_XAU"
    if score <= -20.0:
        return "BEARISH_XAU"
    return "NEUTRAL_MIXED"


def evaluate_broader_macro_bias(
    *,
    cross_asset: Mapping[str, Mapping[str, Any]] | None = None,
    event_context: Mapping[str, Any] | None = None,
    intraday_yield_context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    cross = {str(k): dict(v) for k, v in dict(cross_asset or {}).items()}
    components: dict[str, dict[str, Any]] = {}
    observed_weight = 0.0
    weighted_sum = 0.0

    for name in ("USD_BROAD_PROXY", "US2Y", "US10Y", "REAL_YIELD_10Y"):
        row = dict(cross.get(name) or {})
        freshness = str(row.get("freshness") or "MISSING").upper()
        delta = row.get("delta")
        score = _gold_score_from_delta(name, delta) if freshness == "FRESH" else None
        available = score is not None
        components[name] = {
            **row,
            "name": name,
            "available": available,
            "score": score,
        }
        if available:
            weight = COMPONENT_WEIGHTS[name]
            observed_weight += weight
            weighted_sum += float(score) * weight

    event_component = _event_component(event_context)
    components["EVENT_CONSENSUS"] = event_component
    if event_component["available"]:
        weight = COMPONENT_WEIGHTS["EVENT_CONSENSUS"]
        observed_weight += weight
        weighted_sum += float(event_component["score"]) * weight

    total_weight = sum(COMPONENT_WEIGHTS.values())
    coverage = observed_weight / total_weight if total_weight else 0.0
    score = None if observed_weight <= 0 else weighted_sum / observed_weight
    raw_bias = _direction(score)
    bias = raw_bias if coverage >= 0.35 else "UNAVAILABLE"

    if score is None:
        confidence = "LOW"
        state = "MACRO_DATA_UNAVAILABLE"
    elif coverage < 0.35:
        confidence = "LOW"
        state = "BROAD_MACRO_PARTIAL"
    elif coverage >= 0.75 and abs(score) >= 40.0:
        # Daily cross-asset proxies cap confidence at MEDIUM.
        confidence = "MEDIUM"
        state = "BROAD_MACRO_DIRECTIONAL"
    elif coverage >= 0.55 and abs(score) >= 20.0:
        confidence = "MEDIUM"
        state = "BROAD_MACRO_DIRECTIONAL"
    elif coverage >= 0.35:
        confidence = "LOW"
        state = "BROAD_MACRO_MIXED"
    else:
        confidence = "LOW"
        state = "BROAD_MACRO_PARTIAL"

    us2y = components.get("US2Y") or {}
    us2y_delta = _number(us2y.get("delta")) if us2y.get("available") else None
    if us2y_delta is None:
        fed_proxy = "UNAVAILABLE"
    elif us2y_delta >= 2.0:
        fed_proxy = "HAWKISH_REPRICING_PROXY"
    elif us2y_delta <= -2.0:
        fed_proxy = "DOVISH_REPRICING_PROXY"
    else:
        fed_proxy = "NEUTRAL_REPRICING_PROXY"

    event_score = event_component.get("score")
    event_direction = _direction(_number(event_score)) if event_component.get("available") else "UNAVAILABLE"
    if event_direction in {"UNAVAILABLE", "NEUTRAL_MIXED"} or bias in {"UNAVAILABLE", "NEUTRAL_MIXED"}:
        relationship = "NO_CLEAR_DIRECTIONAL_COMPARISON"
    elif event_direction == bias:
        relationship = "CONSENSUS_ALIGNED_WITH_BROADER_MACRO"
    else:
        relationship = "CONSENSUS_DIVERGENT_FROM_BROADER_MACRO"

    intraday = dict(intraday_yield_context or {})
    intraday_available = bool(intraday.get("available"))
    intraday_state = str(intraday.get("state") or "UNAVAILABLE").upper()
    intraday_implication = str(intraday.get("gold_implication") or "UNAVAILABLE").upper()
    if not intraday_available:
        post_event_macro_state = "INTRADAY_YIELD_UNAVAILABLE"
        post_event_gold_pressure = "UNAVAILABLE"
        event_intraday_relationship = "NO_INTRADAY_COMPARISON"
    elif intraday_implication in {"GOLD_HEADWIND", "GOLD_HEADWIND_CONFIRMED"}:
        post_event_gold_pressure = intraday_implication
        if event_direction == "BULLISH_XAU":
            post_event_macro_state = "POST_NEWS_MACRO_REVERSAL"
            event_intraday_relationship = "EVENT_BULLISH_YIELD_REVERSAL_HEADWIND"
        elif event_direction == "BEARISH_XAU":
            post_event_macro_state = "POST_NEWS_MACRO_CONFIRMATION"
            event_intraday_relationship = "EVENT_BEARISH_YIELD_HEADWIND_ALIGNED"
        else:
            post_event_macro_state = "INTRADAY_YIELD_HEADWIND"
            event_intraday_relationship = "EVENT_DIRECTION_UNCLEAR_YIELD_HEADWIND"
    elif intraday_implication == "GOLD_SUPPORT":
        post_event_gold_pressure = "GOLD_SUPPORT"
        if event_direction == "BEARISH_XAU":
            post_event_macro_state = "POST_NEWS_MACRO_REVERSAL"
            event_intraday_relationship = "EVENT_BEARISH_YIELD_REVERSAL_SUPPORT"
        elif event_direction == "BULLISH_XAU":
            post_event_macro_state = "POST_NEWS_MACRO_CONFIRMATION"
            event_intraday_relationship = "EVENT_BULLISH_YIELD_SUPPORT_ALIGNED"
        else:
            post_event_macro_state = "INTRADAY_YIELD_SUPPORT"
            event_intraday_relationship = "EVENT_DIRECTION_UNCLEAR_YIELD_SUPPORT"
    else:
        post_event_macro_state = "POST_NEWS_PRICE_DISCOVERY"
        post_event_gold_pressure = "MIXED"
        event_intraday_relationship = "NO_CLEAR_EVENT_YIELD_ALIGNMENT"

    available = [name for name, row in components.items() if row.get("available")]
    missing = [name for name, row in components.items() if not row.get("available")]

    return {
        "contract": CONTRACT,
        "state": state,
        "broader_macro_bias": bias,
        "macro_score": score,
        "confidence": confidence,
        "confidence_cap": "MEDIUM_DAILY_PROXY_LIMIT",
        "coverage": coverage,
        "available_components": available,
        "missing_components": missing,
        "components": components,
        "event_consensus_bias": event_direction,
        "consensus_relationship": relationship,
        "intraday_yield_context": intraday,
        "intraday_yield_state": intraday_state,
        "post_event_macro_state": post_event_macro_state,
        "post_event_gold_pressure": post_event_gold_pressure,
        "event_intraday_relationship": event_intraday_relationship,
        "fed_repricing_proxy": {
            "state": fed_proxy,
            "source": "US2Y_DAILY_DELTA_PROXY_NOT_FED_FUNDS_FUTURES",
            "delta_bps": us2y_delta,
        },
        "dxy_note": (
            "USD_BROAD_PROXY uses FRED DTWEXBGS Nominal Broad U.S. Dollar Index; "
            "it is not the proprietary ICE U.S. Dollar Index (DXY)."
        ),
        "execution_influence": False,
        "execution_authority": False,
        "promotion_authority": False,
        "interpretation": (
            "Broader macro attribution is a context layer. Higher USD, nominal yields "
            "and real yields are treated as gold headwinds; lower readings as support. "
            "Missing or stale evidence is excluded rather than converted to neutral. "
            "Event consensus is low-weight before release and stronger only after an "
            "actual-vs-forecast value is available. Intraday US10Y reversal context is "
            "kept separate from the daily weighted score and cannot authorize execution."
        ),
    }

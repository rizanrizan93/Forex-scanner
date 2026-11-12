"""Read-only evidence-quality overlay for the V357/V399 XAU macro attribution.

The existing macro_score is deliberately preserved for comparability. This
module computes a separately named, quality-screened score that:
  * checks original FRED observation timestamps, not just heartbeat freshness;
  * excludes forecast-vs-previous votes and unverified post-news actuals;
  * rejects mixed simultaneous surprises instead of selecting one event;
  * distinguishes daily regime from intraday confirmation;
  * never claims calibrated prediction accuracy or execution authority.

No broker, execution, network, storage, or order imports belong here.
"""
from __future__ import annotations

from datetime import UTC, datetime
from math import isfinite
from typing import Any, Mapping

CONTRACT = "XAU_MACRO_ATTRIBUTION_QUALITY_V400"
DAILY_WEIGHTS = {
    "USD_BROAD_PROXY": .25,
    "US2Y": .25,
    "US10Y": .10,
    "REAL_YIELD_10Y": .20,
}
DAILY_SCALES = {
    "USD_BROAD_PROXY": .50,  # percent change
    "US2Y": 8.0,             # basis points
    "US10Y": 8.0,
    "REAL_YIELD_10Y": 8.0,
}
# FRED H.10 Broad USD is published with a longer lag than Treasury H.15.
# These are conservative MAXIMUM valid ages, not live-market guarantees.
MAX_OBSERVATION_AGE_S = {
    "USD_BROAD_PROXY": 7 * 86400,
    "US2Y": 5 * 86400,
    "US10Y": 5 * 86400,
    "REAL_YIELD_10Y": 5 * 86400,
}
EVENT_WEIGHT = .20
MAX_EVENT_AGE_S = 3600
INTRADAY_MAX_AGE_S = 900


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        out = float(value)
        return out if isfinite(out) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo else None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt.astimezone(UTC) if dt.tzinfo else None
    except (TypeError, ValueError, OverflowError):
        return None


def _score(name: str, delta: Any) -> float | None:
    value = _number(delta)
    if value is None or name not in DAILY_SCALES:
        return None
    return max(-100.0, min(100.0, -100.0 * value / DAILY_SCALES[name]))


def _direction(score: float | None) -> str:
    if score is None:
        return "UNAVAILABLE"
    if score <= -20.0:
        return "BEARISH_XAU"
    if score >= 20.0:
        return "BULLISH_XAU"
    return "NEUTRAL_MIXED"


def _category_sign(category: str, actual: float, forecast: float) -> int | None:
    """Return sign of inflationary/hawkish surprise: +1 = bearish XAU."""
    category = category.upper()
    if category in {"JOBLESS_CLAIMS", "UNEMPLOYMENT_RATE"}:
        multiplier = -1
    elif category in {
        "CPI", "PPI", "NFP", "EMPLOYMENT", "WAGES", "ECI",
        "JOLTS", "OTHER_USD",
    }:
        multiplier = +1
    else:
        return None
    diff = actual - forecast
    return multiplier * (1 if diff > 0 else -1 if diff < 0 else 0)


def _actual_verified(row: Mapping[str, Any]) -> bool:
    if _number(row.get("actual")) is None:
        return False
    if str(row.get("source_tier") or "").upper().startswith("OFFICIAL_ACTUAL"):
        return True
    quotes = row.get("actual_quotes") or []
    distinct: dict[str, float] = {}
    for q in quotes:
        if not isinstance(q, Mapping):
            continue
        vendor = str(q.get("source") or "").strip().upper()
        actual = _number(q.get("actual"))
        if not vendor or actual is None:
            continue
        if vendor in distinct and distinct[vendor] != actual:
            return False
        distinct[vendor] = actual
    if len(distinct) < 2:
        return False
    values = list(distinct.values())
    median = sorted(values)[len(values)//2]
    # Cross-vendor actuals must match to rounding tolerance (not forecasts).
    return max(values) - min(values) <= max(1e-6, abs(median) * .001)


def _post_news_assessment(
    events: Mapping[str, Any] | None, *, now: datetime,
) -> dict[str, Any]:
    context = dict(events or {})
    rows = [dict(row) for row in context.get("upcoming_events") or []
            if isinstance(row, Mapping)]
    for key in ("focal_event", "latest_released_event"):
        row = context.get(key)
        if isinstance(row, Mapping) and row:
            rows.append(dict(row))
    recent = []
    for row in rows:
        at = _dt(row.get("scheduled_at"))
        actual, forecast = _number(row.get("actual")), _number(row.get("forecast"))
        if at is None or actual is None or forecast is None:
            continue
        age = (now-at).total_seconds()
        if 0 <= age <= MAX_EVENT_AGE_S:
            recent.append((at, row))
    out = {"state": "NO_VERIFIED_RECENT_ACTUAL", "component_count": 0,
           "verified_components": 0, "score": None, "event_time": None}
    if not recent:
        return out
    latest = max(at for at, _ in recent)
    # Release component keys prevent duplicate calendars from counting as
    # independent evidence. Prefer official/independently verified row.
    dedup: dict[str, dict[str, Any]] = {}
    for at, row in recent:
        if at != latest:
            continue
        key = str(row.get("event_component") or row.get("title") or "")
        prior = dedup.get(key)
        if prior is None or (_actual_verified(row) and not _actual_verified(prior)):
            dedup[key] = row
    components = list(dedup.values())
    out.update(component_count=len(components), event_time=latest.isoformat())
    if not components:
        return out
    signs: set[int] = set()
    for row in components:
        # One unverifiable component within a simultaneous release is enough
        # to withhold a directional news vote.
        if not _actual_verified(row):
            out["state"] = "ACTUAL_NOT_CORROBORATED"
            return out
        direction = _category_sign(str(row.get("category") or ""),
                                   _number(row["actual"]), _number(row["forecast"]))
        if direction is None:
            out["state"] = "UNMODELED_EVENT"
            return out
        out["verified_components"] += 1
        signs.add(direction)
    if 1 in signs and -1 in signs:
        out["state"] = "MIXED_SURPRISE"
    elif signs == {1}:
        out.update(state="VERIFIED_HOT", score=-70.0)
    elif signs == {-1}:
        out.update(state="VERIFIED_COOL", score=70.0)
    else:
        out["state"] = "INLINE_OR_MIXED_NEUTRAL"
    return out


def evaluate_attribution_quality(
    evaluation: Mapping[str, Any], *,
    event_context: Mapping[str, Any] | None = None,
    intraday_confirmation: Mapping[str, Any] | None = None,
    now: datetime,
) -> dict[str, Any]:
    current = _dt(now)
    if current is None:
        raise ValueError("now must be timezone-aware")
    components = dict(evaluation.get("components") or {})
    valid: dict[str, dict[str, Any]] = {}
    omitted: dict[str, str] = {}
    delayed: list[str] = []
    weighted = 0.0
    observed_weight = 0.0
    for name, weight in DAILY_WEIGHTS.items():
        row = dict(components.get(name) or {})
        at = _dt(row.get("observed_at"))
        age = (current-at).total_seconds() if at else None
        score = _score(name, row.get("delta"))
        if str(row.get("freshness") or "") != "FRESH":
            omitted[name] = "PROVIDER_NOT_FRESH"
        elif age is None or not 0 <= age <= MAX_OBSERVATION_AGE_S[name]:
            omitted[name] = "OBSERVATION_STALE_OR_MISSING"
        elif score is None:
            omitted[name] = "INVALID_DELTA"
        else:
            valid[name] = {"score": round(score, 3), "weight": weight,
                           "observed_at": at.isoformat(),
                           "age_hours": round(age/3600, 2)}
            weighted += score * weight
            observed_weight += weight
            if age > 48 * 3600:
                delayed.append(name)

    news = _post_news_assessment(event_context, now=current)
    if news["score"] is not None:
        weighted += EVENT_WEIGHT * news["score"]
        observed_weight += EVENT_WEIGHT

    screened_score = round(weighted / observed_weight, 2) if observed_weight else None
    screened_bias = _direction(screened_score)
    daily_weight = sum(DAILY_WEIGHTS.values())
    daily_coverage = round(sum(DAILY_WEIGHTS[n] for n in valid) / daily_weight, 3)
    family_count = int("USD_BROAD_PROXY" in valid) + int(any(
        n in valid for n in ("US2Y", "US10Y", "REAL_YIELD_10Y")))
    intraday = dict(intraday_confirmation or {})
    intraday_bias = str(intraday.get("intraday_macro_bias") or "UNAVAILABLE")
    fresh_names = set(intraday.get("fresh_components") or ())
    # Require a current DXY signal plus another independent rate-market signal.
    eligible = bool(intraday.get("confirmation_eligible")) and (
        "DXY" in fresh_names
        and bool(fresh_names & {"US10Y_INTRADAY", "FED_FUNDS_FUTURES"})
    )
    flags = []
    if omitted:
        flags.append("DAILY_INPUT_MISSING_OR_STALE")
    if delayed:
        flags.append("DAILY_CONTEXT_OLDER_THAN_48H")
    if news["state"] in {"ACTUAL_NOT_CORROBORATED", "MIXED_SURPRISE"}:
        flags.append(news["state"])
    if family_count < 2 or daily_coverage < .55:
        state = "WAIT_DAILY_DATA"
    elif not eligible:
        state = "WAIT_INTRADAY_CONFIRMATION"
    elif screened_bias not in {"BEARISH_XAU", "BULLISH_XAU"}:
        state = "WAIT_NON_DIRECTIONAL"
    elif intraday_bias != screened_bias:
        state = "WAIT_MACRO_DIVERGENCE"
        flags.append("DAILY_INTRADAY_OPPOSED")
    else:
        state = "ALIGNED_CONTEXT_ONLY"

    return {
        "contract": CONTRACT,
        "legacy_macro_score": _number(evaluation.get("macro_score")),
        "quality_screened_score": screened_score,
        "quality_screened_bias": screened_bias,
        "quality_state": state,
        "intraday_bias": intraday_bias,
        "intraday_confirmation_eligible": eligible,
        "daily_coverage": daily_coverage,
        "directional_coverage": round(observed_weight, 3),
        "independent_families": family_count,
        "valid_daily_components": valid,
        "excluded_daily_components": omitted,
        "delayed_daily_components": delayed,
        "event_quality": news,
        "flags": flags,
        "confidence": (
            "MEDIUM" if state == "ALIGNED_CONTEXT_ONLY"
            and not delayed and news["state"] != "MIXED_SURPRISE"
            else "LOW"
        ),
        "calibrated_accuracy": None,
        "validation_state": "OUT_OF_SAMPLE_NOT_VALIDATED",
        "entry_permission": False,
        "execution_authority": False,
        "execution_influence": False,
        "interpretation": (
            "A non-executable quality screen. Official daily release data can be "
            "delayed by publication schedule; those observations are regime context, "
            "not intraday evidence. News is scored only from timely, independently "
            "verified actuals; macro-vs-intraday divergence always demands WAIT. "
            "No claimed accuracy until an as-of, walk-forward XAU test is complete."
        ),
    }

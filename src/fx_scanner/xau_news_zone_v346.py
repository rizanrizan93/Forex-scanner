from __future__ import annotations

from datetime import UTC, datetime, timedelta
from math import isfinite
from typing import Any, Iterable

import pandas as pd

from .models import ensure_utc
from .xau_news_zone_source_v346 import NewsZoneEvent

CONTRACT = "XAU_RIZAN_NEWS_ZONE_V346_1"
EXECUTION_AUTHORITY = False
EXECUTION_INFLUENCE = False
LIVE_EXECUTION_ENABLED = False

WINDOWS = {
    "CPI": (30, 10, 45),
    "PCE": (30, 10, 45),
    "NFP": (30, 10, 45),
    "ISM": (20, 10, 45),
    "FOMC": (45, 15, 60),
    "JOBLESS_CLAIMS": (15, 5, 30),
    "FED_SPEECH": (15, 5, 30),
    "GEOPOLITICAL_SHOCK": (0, 0, 120),
}


def _event_blocks_execution(event: NewsZoneEvent | None) -> bool:
    """Only verified calendar evidence may create a hard execution blackout.

    Discovery-only events remain visible as volatility context but cannot
    silently override a fully confirmed structural setup. Missing all economic
    calendar sources still fails closed elsewhere.
    """
    if event is None:
        return False
    return str(event.source_tier or "").upper() != "DISCOVERY_UNVERIFIED"


def _f(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _frame(bars: Iterable[Any]) -> pd.DataFrame:
    rows = []
    for bar in bars:
        ts = getattr(bar, "timestamp", None)
        if ts is None:
            continue
        rows.append(
            {
                "timestamp": pd.Timestamp(ensure_utc(ts)),
                "open": float(getattr(bar, "open")),
                "high": float(getattr(bar, "high")),
                "low": float(getattr(bar, "low")),
                "close": float(getattr(bar, "close")),
            }
        )
    if not rows:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close"])
    return (
        pd.DataFrame(rows)
        .drop_duplicates("timestamp", keep="last")
        .sort_values("timestamp")
        .reset_index(drop=True)
    )


def _distance(price: float, low: float, high: float) -> float:
    if price < low:
        return low - price
    if price > high:
        return price - high
    return 0.0


def _focal_event(
    events: Iterable[NewsZoneEvent],
    *,
    now: datetime,
) -> tuple[NewsZoneEvent | None, str, float | None]:
    current = ensure_utc(now)
    candidates = []
    upcoming = []
    for event in events:
        pre, live, post = WINDOWS.get(event.category, (15, 5, 30))
        delta = (event.scheduled_at - current).total_seconds() / 60.0
        if -post <= delta <= live:
            priority = 4 if -live <= delta <= live else 2
            candidates.append((priority, abs(delta), event, delta))
        elif 0 < delta <= pre:
            candidates.append((3, abs(delta), event, delta))
        elif 0 < delta <= 36 * 60:
            upcoming.append((delta, event))

    if candidates:
        candidates.sort(key=lambda x: (-x[0], x[1], x[2].scheduled_at))
        priority, _, event, delta = candidates[0]
        if priority == 4:
            state = "EVENT_WINDOW"
        elif priority == 3:
            state = "PRE_EVENT"
        else:
            state = "POST_EVENT_DISCOVERY"
        return event, state, delta

    if upcoming:
        upcoming.sort(key=lambda x: x[0])
        delta, event = upcoming[0]
        return event, "CLEAR", delta
    return None, "CLEAR", None


def _next_same_zone(
    active_zones: list[dict[str, Any]],
    *,
    failed_zone: dict[str, Any],
) -> dict[str, Any]:
    direction = str(failed_zone.get("direction") or "")
    low = _f(failed_zone.get("low"))
    high = _f(failed_zone.get("high"))
    if low is None or high is None:
        return {}
    candidates = []
    for zone in active_zones:
        if str(zone.get("direction") or "") != direction:
            continue
        if str(zone.get("zone_id") or "") == str(failed_zone.get("zone_id") or ""):
            continue
        zlow = _f(zone.get("low"))
        zhigh = _f(zone.get("high"))
        if zlow is None or zhigh is None:
            continue
        if direction == "LONG" and zhigh < low:
            candidates.append((low - zhigh, zone))
        elif direction == "SHORT" and zlow > high:
            candidates.append((zlow - high, zone))
    candidates.sort(key=lambda x: x[0])
    return dict(candidates[0][1]) if candidates else {}


def _zone_interaction(
    *,
    zone: dict[str, Any],
    micro: dict[str, Any],
    bars_m5: Iterable[Any],
    event_at: datetime | None,
    now: datetime,
) -> dict[str, Any]:
    if not zone:
        return {"state": "NO_DECISION_ZONE"}
    direction = str(zone.get("direction") or "")
    low = _f(zone.get("low"))
    high = _f(zone.get("high"))
    proximal = _f(zone.get("proximal"))
    distal = _f(zone.get("distal"))
    atr = _f(zone.get("atr"))
    if None in {low, high, proximal, distal, atr}:
        return {"state": "INVALID_ZONE_GEOMETRY"}

    frame = _frame(bars_m5)
    if frame.empty:
        return {"state": "NO_M5_DATA"}
    frame = frame[
        (frame["timestamp"] + pd.Timedelta(minutes=5)) <= pd.Timestamp(ensure_utc(now))
    ].copy()
    if event_at is not None:
        start = pd.Timestamp(ensure_utc(event_at) - timedelta(minutes=5))
        frame = frame[frame["timestamp"] >= start].copy()
    else:
        frame = frame.tail(24).copy()
    if frame.empty:
        return {"state": "NO_POST_EVENT_BARS"}

    closes = frame["close"].astype(float)
    highs = frame["high"].astype(float)
    lows = frame["low"].astype(float)
    buffer = 0.10 * float(atr)

    if direction == "LONG":
        swept = bool((lows < float(distal)).any())
        strong_break = bool((closes < float(distal) - buffer).any())
        consecutive_break = bool(
            len(closes) >= 2
            and ((closes < float(distal)).rolling(2).sum() >= 2).any()
        )
        reclaimed = bool((closes > float(proximal)).any()) if swept else False
    else:
        swept = bool((highs > float(distal)).any())
        strong_break = bool((closes > float(distal) + buffer).any())
        consecutive_break = bool(
            len(closes) >= 2
            and ((closes > float(distal)).rolling(2).sum() >= 2).any()
        )
        reclaimed = bool((closes < float(proximal)).any()) if swept else False

    failed = bool(strong_break or consecutive_break)
    micro_confirmed = bool(micro.get("confirmed"))
    micro_early_confirmed = bool(micro.get("early_confirmed"))
    micro_reclaim_at = str(micro.get("reclaim_at") or "")
    micro_after_event = True
    if event_at is not None and micro_reclaim_at:
        try:
            micro_after_event = (
                datetime.fromisoformat(micro_reclaim_at.replace("Z", "+00:00")).astimezone(UTC)
                >= ensure_utc(event_at)
            )
        except ValueError:
            micro_after_event = False

    if failed:
        state = "ZONE_FAILED_AFTER_NEWS"
    elif swept and reclaimed and micro_confirmed and micro_after_event:
        state = "NEWS_SWEEP_REVERSAL_CONFIRMED"
    elif swept and reclaimed and micro_early_confirmed and micro_after_event:
        state = "NEWS_SWEEP_EARLY_REVERSAL_CONFIRMED"
    elif swept and reclaimed:
        state = "NEWS_SWEEP_RECLAIM_WAIT_LOCAL_MSS"
    elif swept:
        state = "NEWS_SWEEP_WAIT_RECLAIM"
    elif bool(
        ((highs >= float(low)) & (lows <= float(high))).any()
    ):
        state = "NEWS_ZONE_TOUCHED_NO_SWEEP"
    else:
        state = "NEWS_ACTIVE_ZONE_NOT_TOUCHED"

    return {
        "state": state,
        "swept_distal": swept,
        "reclaimed_proximal": reclaimed,
        "strong_close_failure": strong_break,
        "two_close_failure": consecutive_break,
        "micro_confirmed": micro_confirmed,
        "micro_early_confirmed": micro_early_confirmed,
        "micro_after_event": micro_after_event,
        "zone_direction": direction,
    }


def evaluate_news_zone(
    *,
    sd_evaluation: dict[str, Any],
    events: Iterable[NewsZoneEvent],
    bars_m5: Iterable[Any],
    bars_m15: Iterable[Any],
    now: datetime,
    source_status: dict[str, str] | None = None,
) -> dict[str, Any]:
    current = ensure_utc(now)
    zone = dict(sd_evaluation.get("decision_zone") or {})
    micro = dict(sd_evaluation.get("micro_confirmation") or {})
    price = _f(sd_evaluation.get("price_now"))
    event_list = sorted(events, key=lambda x: x.scheduled_at)
    focal, risk_state, delta = _focal_event(event_list, now=current)
    event_execution_blocking = _event_blocks_execution(focal)
    gate_risk_state = risk_state if event_execution_blocking else "CLEAR"
    source_status = dict(source_status or {})
    economic_sources = [
        value for key, value in source_status.items()
        if key != "GEOPOLITICAL_SHOCK_FEED"
    ]
    news_source_available = any(str(value).startswith("OK:") for value in economic_sources)
    if not news_source_available:
        risk_state = "NEWS_SOURCE_UNAVAILABLE"
        gate_risk_state = "NEWS_SOURCE_UNAVAILABLE"

    zone_distance_atr = None
    zone_coupled = False
    if zone and price is not None:
        low = _f(zone.get("low"))
        high = _f(zone.get("high"))
        atr = _f(zone.get("atr"))
        if low is not None and high is not None and atr and atr > 0:
            zone_distance_atr = _distance(price, low, high) / atr
            zone_coupled = zone_distance_atr <= 1.0

    interaction = _zone_interaction(
        zone=zone,
        micro=micro,
        bars_m5=bars_m5,
        event_at=None if focal is None else focal.scheduled_at,
        now=current,
    )

    if focal is None:
        overshoot = "BASELINE"
    elif focal.category == "FOMC" and zone_coupled:
        overshoot = "VERY_HIGH"
    elif focal.impact == "HIGH" and zone_coupled:
        overshoot = "HIGH"
    elif focal.impact in {"HIGH", "MEDIUM"}:
        overshoot = "ELEVATED"
    else:
        overshoot = "BASELINE"

    failed = interaction.get("state") == "ZONE_FAILED_AFTER_NEWS"
    confirmed = interaction.get("state") == "NEWS_SWEEP_REVERSAL_CONFIRMED"
    early_confirmed = interaction.get("state") == "NEWS_SWEEP_EARLY_REVERSAL_CONFIRMED"
    next_zone = (
        _next_same_zone(
            list(sd_evaluation.get("active_zones") or []),
            failed_zone=zone,
        )
        if failed
        else {}
    )

    if gate_risk_state == "NEWS_SOURCE_UNAVAILABLE":
        decision_state = "WAIT_NEWS_DATA"
        preferred = "WAIT_FOR_NEWS_SOURCE_RECOVERY"
        alternative = "DO_NOT_TREAT_MISSING_CALENDAR_AS_CLEAR"
    elif gate_risk_state in {"PRE_EVENT", "EVENT_WINDOW"}:
        decision_state = "WAIT_EVENT_VOLATILITY"
        preferred = "WAIT_FOR_RELEASE_THEN_REASSESS_ZONE"
        alternative = "NO_DIRECTIONAL_NEWS_BET"
    elif failed:
        decision_state = "ZONE_FAILED_SEARCH_NEXT_HTF"
        preferred = "CONTINUATION_TO_NEXT_SAME_TYPE_HTF_ZONE"
        alternative = "ONLY_REVERSE_IF_FAILED_ZONE_IS_RECLAIMED_WITH_NEW_MSS"
    elif confirmed:
        decision_state = "POST_NEWS_REVERSAL_CONFIRMED"
        preferred = "REVERSAL_FROM_HTF_ZONE_TOWARD_OPPOSING_ZONE"
        alternative = "INVALIDATE_IF_RECLAIM_FAILS_OR_STRONG_DISTAL_CLOSE_RETURNS"
    elif early_confirmed:
        decision_state = "POST_NEWS_EARLY_REVERSAL_CONFIRMED"
        preferred = "BOUNDED_DEMO_PROBE_FROM_RECLAIM_WITH_STRUCTURAL_INVALIDATION"
        alternative = "WAIT_FULL_LOCAL_MSS_FOR_STRONGER_CONFIRMATION"
    elif gate_risk_state == "POST_EVENT_DISCOVERY":
        decision_state = "WAIT_POST_NEWS_CONFIRMATION"
        preferred = "WAIT_SWEEP_RECLAIM_MSS_DISPLACEMENT"
        alternative = "ZONE_FAILURE_THEN_SEARCH_NEXT_HTF_ZONE"
    else:
        decision_state = "NORMAL_ZONE_PROCESS"
        preferred = "FOLLOW_V342_ZONE_AND_MICRO_CONFIRMATION"
        alternative = "IF_ZONE_FAILS_SEARCH_NEXT_HTF_ZONE"

    effective_entry_state = str(
        dict(sd_evaluation.get("entry_guide") or {}).get("state") or "WAIT_CONFIRMATION"
    )
    if gate_risk_state == "NEWS_SOURCE_UNAVAILABLE":
        effective_entry_state = "WAIT_NEWS_DATA"
    elif gate_risk_state in {"PRE_EVENT", "EVENT_WINDOW"}:
        effective_entry_state = "WAIT_FOR_NEWS"
    elif failed:
        effective_entry_state = "BLOCK_FAILED_ZONE"
    elif gate_risk_state == "POST_EVENT_DISCOVERY" and not (confirmed or early_confirmed):
        effective_entry_state = "WAIT_POST_NEWS_M5_M15_CONFIRMATION"

    upcoming = [
        event.as_dict()
        for event in event_list
        if current - timedelta(minutes=120) <= event.scheduled_at <= current + timedelta(hours=36)
    ][:10]

    return {
        "contract": CONTRACT,
        "state": decision_state,
        "risk_state": risk_state,
        "execution_risk_state": gate_risk_state,
        "event_execution_blocking": event_execution_blocking,
        "observed_at": current.isoformat(),
        "focal_event": None if focal is None else focal.as_dict(),
        "minutes_to_focal": delta,
        "next_events": upcoming,
        "source_status": source_status,
        "news_source_available": news_source_available,
        "zone_coupled": zone_coupled,
        "zone_distance_atr": zone_distance_atr,
        "overshoot_risk": overshoot,
        "zone_interaction": interaction,
        "failed_zone": zone if failed else {},
        "next_same_type_htf_zone": next_zone,
        "preferred_path": preferred,
        "alternative_path": alternative,
        "effective_entry_state": effective_entry_state,
        "policy": {
            "news_direction_prediction": False,
            "verified_event_hard_gate": "SOURCE_TIER_NOT_DISCOVERY_UNVERIFIED",
            "discovery_unverified": "CONTEXT_ONLY_NO_HARD_EXECUTION_BLACKOUT",
            "pre_event": "WAIT_EVENT_VOLATILITY",
            "post_event": "SWEEP_RECLAIM_MSS_DISPLACEMENT_OR_ZONE_FAILURE",
            "failure": "STRONG_CLOSE_OR_TWO_M5_CLOSES_BEYOND_DISTAL",
            "geopolitical_shock": "INTERFACE_READY_REQUIRES_VERIFIED_HEADLINE_FEED",
        },
        "execution_authority": EXECUTION_AUTHORITY,
        "execution_influence": EXECUTION_INFLUENCE,
        "live_execution_enabled": LIVE_EXECUTION_ENABLED,
    }

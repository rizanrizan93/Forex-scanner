from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from math import isfinite
from typing import Any, Iterable, Mapping
from urllib.parse import urlencode

CONTRACT = "XAU_US10Y_INTRADAY_REVERSAL_V367"


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo else None
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo else None


def parse_yahoo_tnx_chart(body: bytes) -> tuple[dict[str, Any], ...]:
    payload = json.loads(body.decode("utf-8"))
    chart = dict(payload.get("chart") or {})
    if chart.get("error"):
        raise ValueError(f"TNX chart error: {chart.get('error')}")
    results = list(chart.get("result") or [])
    if not results:
        raise ValueError("TNX chart contained no result")
    result = dict(results[0] or {})
    timestamps = list(result.get("timestamp") or [])
    indicators = dict(result.get("indicators") or {})
    quotes = list(indicators.get("quote") or [])
    closes = list(dict(quotes[0] or {}).get("close") or []) if quotes else []
    rows: list[dict[str, Any]] = []
    for raw_ts, raw_close in zip(timestamps, closes):
        value = _number(raw_close)
        if value is None or value <= 0.0 or value >= 30.0:
            continue
        try:
            observed_at = datetime.fromtimestamp(int(raw_ts), tz=UTC)
        except (TypeError, ValueError, OSError):
            continue
        rows.append({"observed_at": observed_at, "yield_pct": value})
    if not rows:
        raise ValueError("TNX chart contained no usable closes")
    rows.sort(key=lambda row: row["observed_at"])
    return tuple(rows)


def fetch_intraday_us10y(
    transport: Any,
    *,
    base_url: str,
    allowed_host: str,
    interval: str = "1m",
    range_name: str = "1d",
) -> tuple[dict[str, Any], ...]:
    query = urlencode(
        {
            "interval": interval,
            "range": range_name,
            "includePrePost": "true",
            "events": "div,splits",
        }
    )
    response = transport.get(
        f"{base_url}?{query}",
        allowed_host=allowed_host,
        headers={"Accept": "application/json,*/*;q=0.1"},
    )
    return parse_yahoo_tnx_chart(response.body)


def select_latest_post_release_event(
    event_context: Mapping[str, Any] | None,
    *,
    now: datetime,
    max_age_hours: float = 8.0,
) -> dict[str, Any] | None:
    current = now.astimezone(UTC)
    context = dict(event_context or {})
    candidates = [
        dict(item or {})
        for item in list(context.get("upcoming_events") or [])
        if isinstance(item, Mapping)
    ]
    focal = dict(context.get("focal_event") or {})
    if focal:
        candidates.append(focal)

    priority = {
        "EMPLOYMENT": 4,
        "UNEMPLOYMENT_RATE": 3,
        "WAGES": 2,
        "CPI": 2,
        "PCE": 2,
        "PPI": 1,
    }
    usable: list[tuple[float, int, dict[str, Any]]] = []
    seen: set[tuple[str, str]] = set()
    for event in candidates:
        scheduled = _dt(event.get("scheduled_at_wib") or event.get("scheduled_at"))
        if scheduled is None or scheduled > current:
            continue
        age = (current - scheduled).total_seconds()
        if age < 0 or age > max_age_hours * 3600.0:
            continue
        if event.get("actual") is None:
            continue
        if str(event.get("gold_bias_confidence") or "").upper() != "POST_RELEASE":
            continue
        key = (str(event.get("category") or ""), scheduled.isoformat())
        if key in seen:
            continue
        seen.add(key)
        usable.append(
            (
                scheduled.timestamp(),
                priority.get(str(event.get("category") or "").upper(), 0),
                event,
            )
        )
    if not usable:
        return None
    usable.sort(key=lambda row: (row[0], row[1]), reverse=True)
    return usable[0][2]


def evaluate_post_event_yield_reversal(
    points: Iterable[Mapping[str, Any]],
    *,
    event: Mapping[str, Any] | None,
    now: datetime,
    max_age_seconds: float = 1200.0,
    minimum_initial_drop_bps: float = 1.5,
    reversal_threshold_bps: float = 3.0,
    strong_reversal_threshold_bps: float = 5.0,
) -> dict[str, Any]:
    current = now.astimezone(UTC)
    anchor = dict(event or {})
    event_at = _dt(anchor.get("scheduled_at_wib") or anchor.get("scheduled_at"))
    if event_at is None:
        return {
            "contract": CONTRACT,
            "available": False,
            "state": "NO_POST_RELEASE_EVENT_ANCHOR",
            "gold_implication": "UNAVAILABLE",
            "execution_authority": False,
            "execution_influence": False,
        }

    rows: list[tuple[datetime, float]] = []
    for raw in points:
        row = dict(raw or {})
        at = _dt(row.get("observed_at"))
        value = _number(row.get("yield_pct"))
        if at is None or value is None or at > current:
            continue
        rows.append((at, value))
    rows.sort(key=lambda row: row[0])
    if not rows:
        return {
            "contract": CONTRACT,
            "available": False,
            "state": "INTRADAY_YIELD_MISSING",
            "gold_implication": "UNAVAILABLE",
            "event": anchor.get("title"),
            "event_at": event_at.isoformat(),
            "execution_authority": False,
            "execution_influence": False,
        }

    latest_at, latest_value = rows[-1]
    age_seconds = max(0.0, (current - latest_at).total_seconds())
    if age_seconds > max_age_seconds:
        return {
            "contract": CONTRACT,
            "available": False,
            "state": "INTRADAY_YIELD_STALE",
            "gold_implication": "UNAVAILABLE",
            "event": anchor.get("title"),
            "event_at": event_at.isoformat(),
            "current": latest_value,
            "current_at": latest_at.isoformat(),
            "age_seconds": age_seconds,
            "execution_authority": False,
            "execution_influence": False,
        }

    nearest_at, release_value = min(
        rows,
        key=lambda row: abs((row[0] - event_at).total_seconds()),
    )
    if abs((nearest_at - event_at).total_seconds()) > 15 * 60:
        return {
            "contract": CONTRACT,
            "available": False,
            "state": "NO_YIELD_POINT_NEAR_EVENT",
            "gold_implication": "UNAVAILABLE",
            "event": anchor.get("title"),
            "event_at": event_at.isoformat(),
            "current": latest_value,
            "current_at": latest_at.isoformat(),
            "age_seconds": age_seconds,
            "execution_authority": False,
            "execution_influence": False,
        }

    post = [(at, value) for at, value in rows if at >= event_at - timedelta(minutes=2)]
    if len(post) < 3:
        return {
            "contract": CONTRACT,
            "available": False,
            "state": "INSUFFICIENT_POST_EVENT_SAMPLES",
            "gold_implication": "UNAVAILABLE",
            "event": anchor.get("title"),
            "event_at": event_at.isoformat(),
            "sample_count": len(post),
            "execution_authority": False,
            "execution_influence": False,
        }

    low_at, low_value = min(post, key=lambda row: row[1])
    high_at, high_value = max(post, key=lambda row: row[1])
    initial_drop_bps = (low_value - release_value) * 100.0
    rebound_from_low_bps = (latest_value - low_value) * 100.0
    net_from_release_bps = (latest_value - release_value) * 100.0

    if (
        initial_drop_bps <= -abs(minimum_initial_drop_bps)
        and rebound_from_low_bps >= abs(strong_reversal_threshold_bps)
    ):
        state = "YIELD_REVERSAL_UP_STRONG"
        implication = "GOLD_HEADWIND_CONFIRMED"
    elif (
        initial_drop_bps <= -abs(minimum_initial_drop_bps)
        and rebound_from_low_bps >= abs(reversal_threshold_bps)
    ):
        state = "YIELD_REVERSAL_UP"
        implication = "GOLD_HEADWIND"
    elif initial_drop_bps <= -abs(minimum_initial_drop_bps):
        state = "POST_EVENT_YIELD_DOWN"
        implication = "GOLD_SUPPORT"
    elif net_from_release_bps >= abs(reversal_threshold_bps):
        state = "YIELD_UP_POST_EVENT"
        implication = "GOLD_HEADWIND"
    elif net_from_release_bps <= -abs(reversal_threshold_bps):
        state = "YIELD_DOWN_POST_EVENT"
        implication = "GOLD_SUPPORT"
    else:
        state = "POST_EVENT_YIELD_MIXED"
        implication = "MIXED"

    return {
        "contract": CONTRACT,
        "available": True,
        "state": state,
        "gold_implication": implication,
        "event": anchor.get("title"),
        "event_category": anchor.get("category"),
        "event_gold_bias": anchor.get("gold_bias"),
        "event_at": event_at.isoformat(),
        "yield_at_release": release_value,
        "yield_at_release_observed_at": nearest_at.isoformat(),
        "post_event_low": low_value,
        "post_event_low_at": low_at.isoformat(),
        "post_event_high": high_value,
        "post_event_high_at": high_at.isoformat(),
        "current": latest_value,
        "current_at": latest_at.isoformat(),
        "age_seconds": age_seconds,
        "initial_drop_bps": initial_drop_bps,
        "rebound_from_low_bps": rebound_from_low_bps,
        "net_from_release_bps": net_from_release_bps,
        "sample_count": len(post),
        "source": "YAHOO_FINANCE_TNX_INTRADAY_PROXY",
        "source_note": (
            "^TNX is a secondary intraday 10Y Treasury-yield proxy, not an official "
            "Treasury/FRED intraday feed. It is context-only and may be delayed."
        ),
        "confidence_cap": "MEDIUM_SECONDARY_INTRADAY_SOURCE",
        "execution_authority": False,
        "execution_influence": False,
    }

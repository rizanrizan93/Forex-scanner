from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from math import isfinite
from typing import Any, Iterable, Mapping
from urllib.parse import urlencode, urlparse

from curl_cffi import requests as curl_requests

CONTRACT = "XAU_INTRADAY_MACRO_CONFIRMATION_V398"


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


def parse_yahoo_chart(body: bytes) -> tuple[dict[str, Any], ...]:
    payload = json.loads(body.decode("utf-8"))
    chart = dict(payload.get("chart") or {})
    if chart.get("error"):
        raise ValueError(f"Yahoo chart error: {chart.get('error')}")
    results = list(chart.get("result") or [])
    if not results:
        raise ValueError("Yahoo chart contained no result")
    result = dict(results[0] or {})
    timestamps = list(result.get("timestamp") or [])
    indicators = dict(result.get("indicators") or {})
    quotes = list(indicators.get("quote") or [])
    closes = list(dict(quotes[0] or {}).get("close") or []) if quotes else []
    rows: list[dict[str, Any]] = []
    for raw_ts, raw_close in zip(timestamps, closes):
        value = _number(raw_close)
        if value is None or value <= 0.0:
            continue
        try:
            observed_at = datetime.fromtimestamp(int(raw_ts), tz=UTC)
        except (TypeError, ValueError, OSError):
            continue
        rows.append({"observed_at": observed_at, "value": value})
    if not rows:
        raise ValueError("Yahoo chart contained no usable closes")
    rows.sort(key=lambda row: row["observed_at"])
    return tuple(rows)


def fetch_yahoo_chart(
    *,
    base_url: str,
    allowed_host: str,
    interval: str = "5m",
    range_name: str = "1d",
    timeout_seconds: float = 10.0,
) -> tuple[dict[str, Any], ...]:
    query = urlencode(
        {
            "interval": interval,
            "range": range_name,
            "includePrePost": "true",
            "events": "div,splits",
        }
    )
    parsed = urlparse(base_url)
    if parsed.scheme != "https" or parsed.hostname != allowed_host:
        raise ValueError("intraday macro source HTTPS host contract is invalid")
    response = curl_requests.get(
        f"{base_url}?{query}",
        headers={"Accept": "application/json,*/*;q=0.1"},
        timeout=float(timeout_seconds),
        impersonate="chrome",
    )
    response.raise_for_status()
    final = urlparse(str(response.url))
    if final.scheme != "https" or final.hostname != allowed_host:
        raise ValueError("intraday macro source redirected outside allowed host")
    return parse_yahoo_chart(bytes(response.content))


def _window_rows(
    points: Iterable[Mapping[str, Any]],
    *,
    now: datetime,
    window_minutes: float,
) -> list[tuple[datetime, float]]:
    current = now.astimezone(UTC)
    rows: list[tuple[datetime, float]] = []
    for raw in points:
        row = dict(raw or {})
        at = _dt(row.get("observed_at"))
        value = _number(row.get("value"))
        if at is None or value is None or at > current:
            continue
        rows.append((at, value))
    rows.sort(key=lambda row: row[0])
    if not rows:
        return []
    cutoff = current - timedelta(minutes=max(5.0, float(window_minutes)))
    window = [(at, value) for at, value in rows if at >= cutoff]
    return window or rows[-1:]


def evaluate_dxy_pressure(
    points: Iterable[Mapping[str, Any]],
    *,
    now: datetime,
    max_age_seconds: float = 1800.0,
    window_minutes: float = 120.0,
    flat_threshold_pct: float = 0.05,
) -> dict[str, Any]:
    current = now.astimezone(UTC)
    rows = _window_rows(points, now=current, window_minutes=window_minutes)
    if not rows:
        return {
            "available": False,
            "freshness": "MISSING",
            "state": "DXY_INTRADAY_MISSING",
            "gold_implication": "UNAVAILABLE",
            "source": "YAHOO_FINANCE_ICE_DXY_PROXY",
            "execution_authority": False,
            "execution_influence": False,
        }

    reference_at, reference = rows[0]
    latest_at, latest = rows[-1]
    age_seconds = max(0.0, (current - latest_at).total_seconds())
    net_pct = 0.0 if reference == 0 else (latest / reference - 1.0) * 100.0
    stale = age_seconds > float(max_age_seconds)
    threshold = abs(float(flat_threshold_pct))

    if stale:
        state = "DXY_INTRADAY_STALE"
        implication = "UNAVAILABLE"
        available = False
        freshness = "STALE"
    elif net_pct >= threshold:
        state = "DXY_UP"
        implication = "GOLD_HEADWIND"
        available = True
        freshness = "FRESH"
    elif net_pct <= -threshold:
        state = "DXY_DOWN"
        implication = "GOLD_SUPPORT"
        available = True
        freshness = "FRESH"
    else:
        state = "DXY_FLAT"
        implication = "MIXED"
        available = True
        freshness = "FRESH"

    return {
        "available": available,
        "freshness": freshness,
        "state": state,
        "gold_implication": implication,
        "current": latest,
        "current_at": latest_at.isoformat(),
        "reference": reference,
        "reference_at": reference_at.isoformat(),
        "net_pct": net_pct,
        "window_minutes": float(window_minutes),
        "age_seconds": age_seconds,
        "freshness_limit_seconds": float(max_age_seconds),
        "source": "YAHOO_FINANCE_ICE_DXY_PROXY",
        "source_note": (
            "DX-Y.NYB tracks the ICE U.S. Dollar Index on Yahoo Finance. "
            "It is a secondary/delayed market-data feed, not a direct licensed ICE feed."
        ),
        "execution_authority": False,
        "execution_influence": False,
    }


def evaluate_fed_funds_futures_pressure(
    points: Iterable[Mapping[str, Any]],
    *,
    now: datetime,
    max_age_seconds: float = 1800.0,
    window_minutes: float = 120.0,
    flat_threshold_bps: float = 1.0,
) -> dict[str, Any]:
    current = now.astimezone(UTC)
    rows = _window_rows(points, now=current, window_minutes=window_minutes)
    if not rows:
        return {
            "available": False,
            "freshness": "MISSING",
            "state": "FED_FUNDS_FUTURES_MISSING",
            "gold_implication": "UNAVAILABLE",
            "source": "YAHOO_FINANCE_ZQ_FRONT_PROXY",
            "execution_authority": False,
            "execution_influence": False,
        }

    reference_at, reference_price = rows[0]
    latest_at, latest_price = rows[-1]
    age_seconds = max(0.0, (current - latest_at).total_seconds())
    reference_implied_rate = 100.0 - reference_price
    latest_implied_rate = 100.0 - latest_price
    implied_rate_change_bps = (latest_implied_rate - reference_implied_rate) * 100.0
    stale = age_seconds > float(max_age_seconds)
    threshold = abs(float(flat_threshold_bps))

    if stale:
        state = "FED_REPRICING_STALE"
        implication = "UNAVAILABLE"
        available = False
        freshness = "STALE"
    elif implied_rate_change_bps >= threshold:
        state = "HAWKISH_REPRICING"
        implication = "GOLD_HEADWIND"
        available = True
        freshness = "FRESH"
    elif implied_rate_change_bps <= -threshold:
        state = "DOVISH_REPRICING"
        implication = "GOLD_SUPPORT"
        available = True
        freshness = "FRESH"
    else:
        state = "FED_REPRICING_FLAT"
        implication = "MIXED"
        available = True
        freshness = "FRESH"

    return {
        "available": available,
        "freshness": freshness,
        "state": state,
        "gold_implication": implication,
        "current": latest_price,
        "current_at": latest_at.isoformat(),
        "reference": reference_price,
        "reference_at": reference_at.isoformat(),
        "implied_rate_pct": latest_implied_rate,
        "reference_implied_rate_pct": reference_implied_rate,
        "implied_rate_change_bps": implied_rate_change_bps,
        "window_minutes": float(window_minutes),
        "age_seconds": age_seconds,
        "freshness_limit_seconds": float(max_age_seconds),
        "source": "YAHOO_FINANCE_ZQ_FRONT_PROXY",
        "source_note": (
            "ZQ=F is the front 30-Day Federal Funds futures contract on Yahoo Finance. "
            "Price is translated as 100 minus implied average effective federal funds rate. "
            "This is a repricing proxy, not CME FedWatch meeting-probability output."
        ),
        "execution_authority": False,
        "execution_influence": False,
    }


def build_intraday_macro_confirmation(
    *,
    dxy: Mapping[str, Any] | None = None,
    fed_funds: Mapping[str, Any] | None = None,
    us10y: Mapping[str, Any] | None = None,
    broader_macro_bias: str | None = None,
) -> dict[str, Any]:
    contexts = {
        "DXY": dict(dxy or {}),
        "FED_FUNDS_FUTURES": dict(fed_funds or {}),
        "US10Y_INTRADAY": dict(us10y or {}),
    }
    usable = {
        name: row
        for name, row in contexts.items()
        if bool(row.get("available"))
        and str(row.get("gold_implication") or "").upper()
        in {"GOLD_HEADWIND", "GOLD_HEADWIND_CONFIRMED", "GOLD_SUPPORT", "GOLD_SUPPORT_CONFIRMED"}
    }
    headwind = [
        name
        for name, row in usable.items()
        if str(row.get("gold_implication") or "").upper()
        in {"GOLD_HEADWIND", "GOLD_HEADWIND_CONFIRMED"}
    ]
    support = [
        name
        for name, row in usable.items()
        if str(row.get("gold_implication") or "").upper()
        in {"GOLD_SUPPORT", "GOLD_SUPPORT_CONFIRMED"}
    ]

    if len(headwind) >= 2 and not support:
        intraday_bias = "BEARISH_XAU"
        state = "INTRADAY_MACRO_BEARISH_CONFIRMED"
    elif len(support) >= 2 and not headwind:
        intraday_bias = "BULLISH_XAU"
        state = "INTRADAY_MACRO_BULLISH_CONFIRMED"
    elif headwind and support:
        intraday_bias = "NEUTRAL_MIXED"
        state = "INTRADAY_MACRO_DIVERGENT"
    elif headwind:
        intraday_bias = "BEARISH_XAU"
        state = "INTRADAY_MACRO_BEARISH_PARTIAL"
    elif support:
        intraday_bias = "BULLISH_XAU"
        state = "INTRADAY_MACRO_BULLISH_PARTIAL"
    else:
        intraday_bias = "UNAVAILABLE"
        state = "INTRADAY_MACRO_UNAVAILABLE"

    stale_or_missing = [
        name
        for name, row in contexts.items()
        if not bool(row.get("available"))
    ]
    confirmation_eligible = len(usable) >= 2 and state in {
        "INTRADAY_MACRO_BEARISH_CONFIRMED",
        "INTRADAY_MACRO_BULLISH_CONFIRMED",
    }

    broader = str(broader_macro_bias or "UNAVAILABLE").upper()
    if intraday_bias in {"BULLISH_XAU", "BEARISH_XAU"} and broader in {
        "BULLISH_XAU",
        "BEARISH_XAU",
    }:
        if intraday_bias == broader:
            relationship = "ALIGNED_WITH_BROADER_MACRO"
        else:
            relationship = "DIVERGENT_FROM_BROADER_MACRO"
    else:
        relationship = "NO_CLEAR_BROADER_COMPARISON"

    return {
        "contract": CONTRACT,
        "state": state,
        "intraday_macro_bias": intraday_bias,
        "relationship_to_broader_macro": relationship,
        "confirmation_eligible": confirmation_eligible,
        "fresh_components": sorted(usable),
        "stale_or_missing_components": sorted(stale_or_missing),
        "headwind_components": sorted(headwind),
        "support_components": sorted(support),
        "components": contexts,
        "execution_authority": False,
        "execution_influence": False,
        "policy": (
            "Intraday macro may confirm or veto confidence, but never creates an XAU entry. "
            "Stale/missing components cannot count as confirmation."
        ),
    }

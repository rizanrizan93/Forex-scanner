"""Read-only US10Y source-recovery helpers for the Streamlit macro panel.

CNBC cash yield and Yahoo market proxies are distinct instruments. Neither a
cache refresh nor a recently fetched stale vendor quote can become a live yield.
No broker, trade, or cBot dependencies.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from math import isfinite
from typing import Any
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

CASH_MAX_AGE_SECONDS = 120
PROXY_MAX_AGE_SECONDS = 1200  # Yahoo market quotes can be exchange delayed.
YAHOO_HOST = "query1.finance.yahoo.com"
PROXY_SYMBOLS = ("^TNX", "ZN=F")
MAX_BODY = 128 * 1024


def _dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo is not None else None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.astimezone(UTC) if parsed.tzinfo is not None else None
    except (ValueError, TypeError):
        return None


def _number(value: Any) -> float | None:
    try:
        parsed = float(value)
        return parsed if isfinite(parsed) else None
    except (ValueError, TypeError):
        return None


def cash_quote_status(data: dict[str, Any] | None, *, now: datetime) -> dict[str, Any]:
    """Reassess vendor time on EACH fragment rerun, not at cache-fetch time."""
    if now.tzinfo is None:
        raise ValueError("now must be timezone aware")
    row = dict(data or {})
    observed = _dt(row.get("current_at"))
    value = _number(row.get("current"))
    if observed is None or value is None or not 0.0 < value < 30.0:
        return {"fresh": False, "age_seconds": None, "reason": "invalid quote/timestamp"}
    age = (now.astimezone(UTC) - observed).total_seconds()
    realtime = str(row.get("realtime")).lower() == "true"
    if age < 0:
        reason = "future vendor timestamp"
    elif not realtime:
        reason = "vendor did not confirm realtime"
    elif age > CASH_MAX_AGE_SECONDS:
        reason = "source quote is stale"
    else:
        reason = "ok"
    return {"fresh": reason == "ok", "age_seconds": max(0.0, age),
            "reason": reason}


def parse_yahoo_proxy(payload: Any, *, symbol: str, now: datetime) -> dict[str, Any] | None:
    """Use chart candle times, not HTTP request/regularMarketTime as freshness."""
    if symbol not in PROXY_SYMBOLS or now.tzinfo is None:
        raise ValueError("invalid proxy symbol or clock")
    chart = (payload or {}).get("chart") or {}
    if chart.get("error"):
        return None
    results = chart.get("result") or []
    if not results:
        return None
    result = results[0] or {}
    timestamps = result.get("timestamp") or []
    quotes = (result.get("indicators") or {}).get("quote") or []
    closes = (quotes[0] or {}).get("close") or [] if quotes else []
    now_utc = now.astimezone(UTC)
    rows = []
    for ts, close in zip(timestamps, closes):
        try:
            at = datetime.fromtimestamp(int(ts), UTC)
        except (TypeError, ValueError, OverflowError, OSError):
            continue
        value = _number(close)
        if value is None or not (0.0 < value < 30.0 if symbol == "^TNX" else 70.0 < value < 200.0):
            continue
        if at <= now_utc:
            rows.append((at, value))
    if not rows:
        return None
    rows.sort()
    latest, value = rows[-1]
    age = (now_utc - latest).total_seconds()
    eligible = 0 <= age <= PROXY_MAX_AGE_SECONDS
    prior = next((v for t, v in reversed(rows[:-1]) if t < latest), None)
    delta = value - prior if prior is not None else None
    if delta is None:
        direction = "BELUM ADA DUA BAR"
    elif abs(delta) < 1e-8:
        direction = "NETRAL"
    elif symbol == "ZN=F":
        direction = "YIELD CENDERUNG TURUN" if delta > 0 else "YIELD CENDERUNG NAIK"
    else:
        direction = "YIELD NAIK" if delta > 0 else "YIELD TURUN"
    return {
        "symbol": symbol, "value": value, "observed_at": latest.isoformat(),
        "age_seconds": age, "eligible": eligible,
        "direction": direction if eligible else "TIDAK TERSEDIA (STALE)",
        "delta": delta if eligible else None, "is_cash_yield": False,
        "source": "Yahoo Finance · CBOE ^TNX (secondary, may be delayed)"
                  if symbol == "^TNX" else
                  "Yahoo Finance · CBOT ZN futures (inverted yield proxy, delayed)",
        "unit": "%" if symbol == "^TNX" else "poin futures",
    }


def fetch_yahoo_proxy(symbol: str, *, now: datetime | None = None) -> dict[str, Any] | None:
    if symbol not in PROXY_SYMBOLS:
        raise ValueError("proxy symbol not allowed")
    timestamp = now or datetime.now(UTC)
    endpoint = "https://" + YAHOO_HOST + "/v8/finance/chart/" + quote(symbol, safe="")
    url = endpoint + "?interval=5m&range=1d"
    request = Request(url, headers={"Accept": "application/json",
                                    "User-Agent": "Mozilla/5.0 (compatible; RIZAN-Macro/1.0)"})
    with urlopen(request, timeout=7) as response:
        final = urlparse(str(response.geturl()))
        if final.scheme != "https" or final.hostname != YAHOO_HOST:
            raise ValueError("proxy redirected outside allowlist")
        body = response.read(MAX_BODY + 1)
    if len(body) > MAX_BODY:
        raise ValueError("proxy response too large")
    return parse_yahoo_proxy(json.loads(body.decode("utf-8")), symbol=symbol, now=timestamp)

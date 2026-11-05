"""Read-only, timestamped public market data: CNBC plus optional gold spot fallback.

CNBC is an unofficial, potentially delayed public quote cache; provider flags
AND source timestamps are verified. Contract futures are never disguised as spot
or considered live when the publisher reports delayed exchange prices.
No trading, credentials, broker, or execution dependencies.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from math import isfinite
from typing import Any
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

CNBC_URL = "https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol"
GOLD_API = "https://api.gold-api.com"
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")
MAX_BODY = 256 * 1024
MAX_QUOTE_AGE_S = 300
CNBC_SYMBOLS = {
    ".DXY": "DX-Y.NYB",
    ".VIX": "^VIX",
    "JPY=": "JPY=X",           # USDJPY (USD/JPY)
    "CHF=": "CHF=X",           # USDCHF (USD/CHF)
    "XAU=": "XAU_SPOT",        # OTC indicative XAU/USD, NOT GC futures
    "XAG=": "XAG_SPOT",        # OTC indicative XAG/USD, NOT SI futures
    "@GC.1": "GC=F",          # exchange delayed continuous futures
    "@SI.1": "SI=F",
    "@CL.1": "CL=F",
    "@BZ.1": "BZ=F",
}
SPOT_GOLD_SYMBOLS = {"XAU": "XAU_SPOT", "XAG": "XAG_SPOT"}


def _float(value: Any) -> float | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        text = str(value).strip().replace(",", "").replace("%", "")
        if text.upper() in {"", "N/A", "NA", "--", "-"}:
            return None
        if text.upper() in {"UNCH", "UNCH."}:
            text = "0"
        result = float(text)
        return result if isfinite(result) else None
    except (ValueError, TypeError):
        return None


def _timestamp(value: Any) -> datetime | None:
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return (dt.replace(tzinfo=UTC) if dt.tzinfo is None
                else dt.astimezone(UTC))
    except (ValueError, TypeError):
        return None


def _age_seconds(at: datetime | None, now: datetime) -> float | None:
    return (now - at).total_seconds() if at is not None else None


def parse_cnbc_quotes(payload: Any, *, now: datetime) -> dict[str, dict[str, Any]]:
    """Parse known symbols; freshness is based on VENDOR time, not retrieval."""
    if now.tzinfo is None:
        raise ValueError("now must be timezone aware")
    now = now.astimezone(UTC)
    rows = ((payload or {}).get("FormattedQuoteResult") or {}).get("FormattedQuote") or []
    if isinstance(rows, dict):
        rows = [rows]
    if not isinstance(rows, list):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for item in rows:
        if not isinstance(item, dict):
            continue
        original = str(item.get("symbol") or "")
        if original not in CNBC_SYMBOLS:
            continue
        value, pct = _float(item.get("last")), _float(item.get("change_pct"))
        stamp = _timestamp(item.get("last_time"))
        age = _age_seconds(stamp, now)
        if value is None or value <= 0 or pct is None or age is None or age < 0:
            continue
        realtime = str(item.get("realTime") or "").strip().lower() == "true"
        # Exchange futures may be ~10m delayed even if updated by CNBC now.
        fresh = realtime and age <= MAX_QUOTE_AGE_S
        key = CNBC_SYMBOLS[original]
        out[key] = {
            "value": value, "pct": pct, "observed": stamp.isoformat(),
            "fresh": fresh,
            "source": ("CNBC Quote Cache · spot/FX indicative" if key.endswith("_SPOT")
                       else "CNBC Quote Cache · futures exchange-delayed"
                       if key in {"GC=F", "SI=F", "CL=F", "BZ=F"}
                       else "CNBC Quote Cache · market quote"),
            "basis": "penutupan sebelumnya",
            "provider_realtime": realtime,
            "provider_symbol": original,
            "instrument_type": "SPOT" if key.endswith("_SPOT") else (
                "FUTURES" if key in {"GC=F", "SI=F", "CL=F", "BZ=F"} else "INDEX_OR_FX"),
            "age_seconds_at_fetch": round(age, 1),
        }
    return out


def parse_goldapi_spot(
    payload: Any, *, symbol: str, now: datetime
) -> dict[str, Any] | None:
    """Gold-API's price is indicative spot with NO prior close percentage."""
    if symbol not in SPOT_GOLD_SYMBOLS or not isinstance(payload, dict):
        return None
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    now = now.astimezone(UTC)
    price, stamp = _float(payload.get("price")), _timestamp(payload.get("updatedAt"))
    age = _age_seconds(stamp, now)
    if price is None or price <= 0 or age is None or age < 0:
        return None
    return {
        "value": price, "pct": None, "observed": stamp.isoformat(),
        "fresh": age <= MAX_QUOTE_AGE_S,
        "source": "Gold-API · spot indikatif", "basis": "persentase tidak tersedia",
        "provider_realtime": age <= MAX_QUOTE_AGE_S,
        "instrument_type": "SPOT",
        "age_seconds_at_fetch": round(age, 1),
    }


def _get_json(url: str, expected_host: str) -> Any:
    req = Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urlopen(req, timeout=7) as response:
        location = urlparse(str(response.geturl()))
        if location.scheme != "https" or location.hostname != expected_host:
            raise ValueError("market quote redirected to unexpected host")
        raw = response.read(MAX_BODY + 1)
        if len(raw) > MAX_BODY:
            raise ValueError("market quote payload too large")
    return json.loads(raw.decode("utf-8"))


def fetch_cnbc_market_quotes() -> dict[str, dict[str, Any]]:
    params = urlencode({
        "symbols": "|".join(CNBC_SYMBOLS.keys()),
        "requestMethod": "itv", "noform": "1", "partnerId": "2",
        "fund": "1", "exthrs": "1", "output": "json", "events": "1",
    })
    payload = _get_json(CNBC_URL + "?" + params, "quote.cnbc.com")
    quotes = parse_cnbc_quotes(payload, now=datetime.now(UTC))
    if not quotes:
        raise ValueError("CNBC returned no valid time-stamped market quotes")
    return quotes


def fetch_goldapi_spot(symbol: str) -> dict[str, Any]:
    if symbol not in SPOT_GOLD_SYMBOLS:
        raise ValueError("gold-api symbol is not on allowlist")
    payload = _get_json(f"{GOLD_API}/price/{symbol}", "api.gold-api.com")
    quote = parse_goldapi_spot(payload, symbol=symbol, now=datetime.now(UTC))
    if quote is None:
        raise ValueError("Gold-API spot quote unavailable or missing source timestamp")
    return quote

"""Public, read-only spot oil references and multi-publisher news fallback.

A DIA commodity reference is indicative, not FP Markets' executable bid/ask.
Source timestamps—not HTTP fetch times—decide scoring eligibility. RSS articles
are *reports*, not independent proof that an event occurred.
"""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from math import isfinite
from urllib.parse import urlparse
from urllib.request import Request, urlopen

DIA_HOST = "api.diadata.org"
DIA_SYMBOLS = {"WTI": "WTI-USD", "Brent": "XBR-USD"}
RSS_FEEDS = (
    ("feeds.bbci.co.uk", "https://feeds.bbci.co.uk/news/world/rss.xml"),
    ("www.cnbc.com", "https://www.cnbc.com/id/100727362/device/rss/rss.html"),
    ("www.aljazeera.com", "https://www.aljazeera.com/xml/rss/all.xml"),
)
MAX_BYTES = 256 * 1024
MAX_AGE_SECONDS = 300


def _number(value):
    try:
        if value is None or isinstance(value, bool):
            return None
        n = float(value)
        return n if isfinite(n) else None
    except (TypeError, ValueError):
        return None


def _date(value):
    if not value:
        return None
    try:
        if isinstance(value, (int, float)):
            d = datetime.fromtimestamp(float(value), UTC)
        else:
            d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return d.replace(tzinfo=UTC) if d.tzinfo is None else d.astimezone(UTC)
    except (TypeError, ValueError, OverflowError):
        return None


def parse_dia_spot(payload, *, symbol, now):
    """Return a safe quote; absent previous close means no directional vote."""
    if symbol not in DIA_SYMBOLS or not isinstance(payload, dict) or now.tzinfo is None:
        return None
    price = _number(payload.get("Price", payload.get("price")))
    previous = _number(payload.get("PriceYesterday", payload.get("prev_close")))
    observed = _date(payload.get("Time", payload.get("timestamp")))
    if price is None or not 0 < price < 10000 or observed is None:
        return None
    if previous is not None and not 0 < previous < 10000:
        previous = None
    age = (now.astimezone(UTC) - observed).total_seconds()
    if age < -30:
        return None
    fresh = (0 <= age <= MAX_AGE_SECONDS
             and payload.get("MarketOpen") is not False
             and payload.get("MarketHoliday") is not True)
    return {
        "value": price,
        "pct": (100 * (price / previous - 1)) if previous is not None else None,
        "observed": observed.isoformat(),
        "fresh": fresh,
        "source": "DIA RWA · spot minyak indikatif",
        "basis": "penutupan sebelumnya" if previous is not None
                 else "persentase tidak tersedia",
        "instrument_type": "SPOT",
        "provider_realtime": fresh,
        "provider_symbol": DIA_SYMBOLS[symbol],
    }


def _fetch(url, expected_host):
    req = Request(url, headers={
        "User-Agent": "RIZAN-Macro-ReadOnly/2.0",
        "Accept": "application/json,application/rss+xml,application/xml",
    })
    with urlopen(req, timeout=7) as response:
        final = urlparse(str(response.geturl()))
        if final.scheme != "https" or final.hostname != expected_host:
            raise ValueError("Unexpected macro source redirect")
        body = response.read(MAX_BYTES + 1)
        if len(body) > MAX_BYTES:
            raise ValueError("External macro response too large")
    return body


def fetch_dia_spot(symbol):
    if symbol not in DIA_SYMBOLS:
        raise ValueError("Unapproved DIA oil symbol")
    code = DIA_SYMBOLS[symbol]
    payload = json.loads(_fetch(
        f"https://{DIA_HOST}/v1/rwa/Commodities/{code}", DIA_HOST
    ).decode("utf-8"))
    quote = parse_dia_spot(payload, symbol=symbol, now=datetime.now(UTC))
    if quote is None:
        raise ValueError("DIA spot quote lacks valid price or source timestamp")
    return quote


def _parse_rss(body, now):
    root = ET.fromstring(body)
    articles = []
    for item in root.findall(".//item")[:40]:
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        published = (item.findtext("pubDate") or "").strip()
        try:
            stamp = parsedate_to_datetime(published).astimezone(UTC)
        except (ValueError, TypeError, IndexError):
            continue
        if not title or not link or not 0 <= (now - stamp).total_seconds() <= 24 * 3600:
            continue
        articles.append({
            "title": title[:400], "url": link[:1800],
            "observed": stamp.isoformat(),
        })
    return articles


def fetch_geopolitical_rss():
    """Two or more publishers can contribute; partial RSS failure is tolerated."""
    now = datetime.now(UTC)
    articles = []
    successes = 0
    for host, url in RSS_FEEDS:
        try:
            body = _fetch(url, host)
            articles.extend(_parse_rss(body, now))
            successes += 1
        except (OSError, ValueError, ET.ParseError):
            continue
    if not successes:
        raise ValueError("Every trusted geopolitical RSS feed failed")
    seen = set()
    unique = []
    for article in articles:
        url = article["url"]
        if url not in seen:
            seen.add(url)
            unique.append(article)
    return unique[:75]

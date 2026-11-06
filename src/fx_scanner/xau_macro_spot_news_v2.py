"""Public, read-only spot oil references and multi-publisher news fallback.

A DIA commodity reference is indicative, not FP Markets' executable bid/ask.
Source timestamps—not HTTP fetch times—decide scoring eligibility. RSS articles
are *reports*, not independent proof that an event occurred.
"""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Lock
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
    observed = _date(payload.get("Timestamp") or payload.get("Time") or payload.get("timestamp"))
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


class SpotMomentumTracker:
    """In-process, source-timestamped WTI/Brent spot change (not previous close).

    If DIA omits PriceYesterday, compare with a verified 10-20-minute-old DIA
    sample. No interpolation, synthetic baseline, or previous-session guessing.
    A process restart simply resets warm-up and disables the momentum vote.
    """

    def __init__(self):
        self._lock = Lock()
        self._samples = {}

    def observe(self, symbol, quote, *, now):
        if symbol not in DIA_SYMBOLS or not quote or not quote.get("fresh"):
            return quote
        observed = _date(quote.get("observed"))
        price = _number(quote.get("value"))
        if observed is None or price is None or price <= 0:
            return quote
        if not 0 <= (now.astimezone(UTC) - observed).total_seconds() <= MAX_AGE_SECONDS:
            return quote

        with self._lock:
            history = self._samples.setdefault(symbol, [])
            history[:] = [(at, val) for at, val in history
                          if at <= observed and observed - at <= timedelta(minutes=30)]
            if all(at != observed for at, _ in history):
                history.append((observed, price))
            history.sort(key=lambda item: item[0])
            if quote.get("pct") is not None:
                return quote  # real same-provider previous close wins
            candidates = [
                (at, val) for at, val in history
                if 600 <= (observed - at).total_seconds() <= 1200 and val > 0
            ]
            if not candidates:
                return quote
            baseline_at, baseline = min(
                candidates,
                key=lambda item: abs((observed - item[0]).total_seconds() - 900),
            )
            elapsed = (observed - baseline_at).total_seconds() / 60
            enriched = dict(quote)
            enriched["pct"] = 100 * (price / baseline - 1)
            enriched["basis"] = "perubahan spot 10–20 menit"
            enriched["momentum_window_minutes"] = round(elapsed, 1)
            enriched["baseline_observed"] = baseline_at.isoformat()
            return enriched


_SPOT_MOMENTUM = SpotMomentumTracker()


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
    return _SPOT_MOMENTUM.observe(symbol, quote, now=datetime.now(UTC))


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
    def one(source):
        host, url = source
        try:
            return _parse_rss(_fetch(url, host), now)
        except (OSError, ValueError, ET.ParseError):
            return None

    with ThreadPoolExecutor(max_workers=3) as pool:
        for found in pool.map(one, RSS_FEEDS):
            if found is not None:
                articles.extend(found)
                successes += 1
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

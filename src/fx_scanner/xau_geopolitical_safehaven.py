"""Geopolitical reporting and market safe-haven confirmation for XAU.

Data-driven, conservative HEURISTIC, not a verification of real-world events.
Never infer geopolitical events merely from Oil or from unsourced narratives.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from math import isfinite
from urllib.parse import urlparse
from typing import Any

REPUTABLE_HOSTS = {
    "reuters.com", "apnews.com", "bbc.com", "ft.com",
    "bloomberg.com", "aljazeera.com", "cnbc.com",
}
REGIONS = {
    "Middle East": ("iran", "israel", "middle east", "gaza", "lebanon", "hezbollah", "hormuz"),
    "Ukraine/Russia": ("ukraine", "russia", "kyiv", "moscow"),
    "Taiwan Strait": ("taiwan", "taipei", "taiwan strait"),
    "Red Sea/Yemen": ("yemen", "red sea", "houthi"),
    "Korean Peninsula": ("north korea", "south korea", "korean peninsula"),
}
ESCALATION_TERMS = (
    "missile strike", "missile attack", "airstrike", "air strike",
    "bombardment", "rocket attack", "drone attack", "military strike",
    "armed attack", "military escalation", "cross-border strike",
)
UNCERTAIN_TERMS = (
    "could", "might", "may attack", "warns of", "fears of",
    "threatens", "unconfirmed", "rumor", "rumour",
)


def _num(x: Any) -> float | None:
    try:
        y = float(x)
        return y if isfinite(y) else None
    except (ValueError, TypeError):
        return None


def _dt(x: Any) -> datetime | None:
    try:
        dt = datetime.fromisoformat(str(x).replace("Z", "+00:00"))
        return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
    except (ValueError, TypeError):
        return None


def _trusted_host(url: str) -> str | None:
    try:
        parts = urlparse(url)
        host = str(parts.hostname or "").lower()
        if parts.scheme != "https" or parts.username or parts.password:
            return None
        for root in REPUTABLE_HOSTS:
            if host == root or host.endswith("." + root):
                return root
    except ValueError:
        return None
    return None


def _valid_market(row: dict[str, Any] | None, now: datetime) -> float | None:
    row = row or {}
    value, price, at = _num(row.get("pct")), _num(row.get("value")), _dt(row.get("observed"))
    if row.get("fresh") is not True or value is None or price is None or price <= 0 or at is None:
        return None
    # Prices from Yahoo: compare to prior session close, not to the same 90-minute period.
    if not str(row.get("source") or "").startswith("Yahoo Finance"):
        return None
    if str(row.get("basis") or "") != "penutupan sebelumnya":
        return None
    if not 0 <= (now - at).total_seconds() <= 90 * 60:
        return None
    return value


def assess_geopolitical_safehaven(
    *, articles: list[dict[str, Any]] | None,
    markets: dict[str, dict[str, Any] | None] | None,
    now: datetime,
    news_error: str | None = None,
) -> dict[str, Any]:
    """Risk cluster max 10%, subchannels 5% each, no assumptions if feed missing.

    A report cluster needs >=2 distinct reputable publications about the same
    region, <=12h; it alone does not prove an event happened. Geopolitical vote
    also requires at least one fresh corroborating market move.
    Risk-off vote needs VIX up >=4% AND one haven FX move (USDJPY / USDCHF down
    >=0.2%). Risk-on vote needs VIX down >=4% and BOTH yen/CHF weakening.
    """
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    now = now.astimezone(UTC)
    clusters: dict[str, dict[str, dict[str, str]]] = defaultdict(dict)
    for article in (articles or [])[:75]:
        if not isinstance(article, dict):
            continue
        title = str(article.get("title") or "").strip()
        at = _dt(article.get("observed"))
        href = str(article.get("url") or "")
        host = _trusted_host(href)
        lower = title.casefold()
        if not host or at is None or not 0 <= (now - at).total_seconds() <= 12 * 3600:
            continue
        if not any(term in lower for term in ESCALATION_TERMS):
            continue
        if any(term in lower for term in UNCERTAIN_TERMS):
            continue
        for region, words in REGIONS.items():
            if any(term in lower for term in words):
                if host not in clusters[region]:
                    clusters[region][host] = {
                        "source": host, "title": title[:180],
                        "url": href, "observed": at.isoformat(),
                    }
    confirmed = [(region, list(reporters.values())) for region, reporters in clusters.items()
                 if len(reporters) >= 2]
    confirmed.sort(key=lambda x: (-len(x[1]), x[0]))
    observed_region = confirmed[0][0] if confirmed else None
    evidence = confirmed[0][1][:3] if confirmed else []

    markets = markets or {}
    vix = _valid_market(markets.get("^VIX"), now)
    jpy = _valid_market(markets.get("JPY=X"), now)
    chf = _valid_market(markets.get("CHF=X"), now)
    # USDJPY and USDCHF falling = JPY and CHF strengthening vs USD.
    risk_off = (vix is not None and vix >= 4.0 and
                any(p is not None and p <= -0.20 for p in (jpy, chf)))
    risk_on = (vix is not None and vix <= -4.0 and
               jpy is not None and chf is not None and
               jpy >= 0.20 and chf >= 0.20)
    haven_vote = 1 if risk_off else -1 if risk_on else None
    market_confirm = (vix is not None and vix >= 4.0) or any(
        p is not None and p <= -0.20 for p in (jpy, chf)
    )
    geo_vote = 1 if observed_region and market_confirm else None

    geo_weight = 0.05 if geo_vote is not None else 0.0
    haven_weight = 0.05 if haven_vote is not None else 0.0
    status = (
        "GEOPOLITIK + SAFE HAVEN TERKONFIRMASI PASAR" if geo_weight and haven_weight and haven_vote == 1
        else "GEOPOLITIK DILAPORKAN + KONFIRMASI PASAR TERBATAS" if geo_weight
        else "SAFE HAVEN RISK-OFF TERAMATI" if haven_vote == 1
        else "RISK-ON / SAFE HAVEN UNWIND TERAMATI" if haven_vote == -1
        else "BELUM TERKONFIRMASI"
    )
    return {
        "status": status,
        "reported_region": observed_region,
        "news_evidence": evidence,
        "news_error": news_error,
        "geopolitical_vote": geo_vote,
        "safehaven_vote": haven_vote,
        "geo_weight": geo_weight,
        "haven_weight": haven_weight,
        "total_weight": geo_weight + haven_weight,
        "market_pct": {"VIX": vix, "USDJPY": jpy, "USDCHF": chf},
        "news_status": ("LAPORAN MULTI-SUMBER" if observed_region
                        else "FEED ERROR" if news_error
                        else "BELUM ADA KOROBORASI LINTAS MEDIA"),
        "summary": (
            "Skor berita geopolitik hanya aktif bila sedikitnya dua domain berita "
            "bereputasi melaporkan eskalasi di wilayah yang sama dalam 12 jam "
            "dan pasar memberikan indikasi risk-off. Ini bukti peliputan, "
            "BUKAN verifikasi independen atas terjadinya serangan. "
            "Safe haven menggunakan VIX + JPY/CHF; tidak menghitung harga emas "
            "sebagai prediktor emas. Kedua kanal bersama dibatasi 10%."
        ),
    }

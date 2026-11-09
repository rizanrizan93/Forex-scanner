"""Read-only four-pillar macro monitor for the XAU manual dashboard.

Data labels carry the original observation time. Never use missing/stale market
data to infer a live macro direction or to authorize an order.
"""
from __future__ import annotations

import csv
import io
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo
from math import isfinite
from urllib.parse import quote, urlencode, urlparse
from urllib.request import Request, urlopen

import streamlit as st

from .xau_macro_gold_consensus import analyze_gold_macro, explain_oil_component
from .xau_m15_macro_forecast import render_macro_m15_forecast
from .xau_market_quote_health import quote_freshness, QUOTE_MAX_AGE_SECONDS
from .xau_cnbc_macro_quotes import fetch_cnbc_market_quotes, fetch_goldapi_spot
from .xau_macro_spot_news_v2 import fetch_dia_spot, fetch_geopolitical_rss
from .xau_macro_daily_regime import (
    assess_daily_regime, fred_daily_yield_row, FRED_YIELD_SERIES,
)


FRED_SERIES = {
    "CPIAUCSL", "PCEPILFE", "PCEPI", "DFEDTARU", "DGS2",
    "DCOILWTICO", "DCOILBRENTEU", "DGS10", "DFII10",
}
YAHOO_SYMBOLS = {"DX-Y.NYB", "^VIX", "JPY=X", "CHF=X"}  # no delayed futures
MAX_BODY = 256 * 1024


def _date(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _number(value):
    try:
        n = float(value)
        return n if isfinite(n) else None
    except (ValueError, TypeError):
        return None


def _recent(value, days):
    d = _date(value)
    if d is None:
        return False
    if d.tzinfo is None:
        d = d.replace(tzinfo=UTC)
    age = (datetime.now(UTC) - d.astimezone(UTC)).total_seconds()
    return 0 <= age <= days * 86400


def _fetch(url, host):
    request = Request(url, headers={
        "Accept": "application/json,text/csv,*/*",
        "User-Agent": "RIZAN-ReadOnly-Macro-Monitor/1.0",
    })
    with urlopen(request, timeout=8) as response:
        parsed = urlparse(str(response.geturl()))
        if parsed.scheme != "https" or parsed.hostname != host:
            raise ValueError("External data host mismatch")
        raw = response.read(MAX_BODY + 1)
    if len(raw) > MAX_BODY:
        raise ValueError("External market data too large")
    return raw


@st.cache_data(ttl=1800, show_spinner=False)
def fred_history(series):
    if series not in FRED_SERIES:
        raise ValueError("Unapproved FRED series")
    start = (datetime.now(UTC) - timedelta(days=490)).date().isoformat()
    url = "https://fred.stlouisfed.org/graph/fredgraph.csv?" + urlencode(
        {"id": series, "cosd": start}
    )
    data = _fetch(url, "fred.stlouisfed.org")
    records = {}
    for line in csv.DictReader(io.StringIO(data.decode("utf-8-sig"))):
        date = line.get("observation_date") or line.get("DATE") or line.get("date")
        value = _number(line.get(series))
        if date and value is not None and _date(date) is not None:
            if _date(date).date() <= datetime.now(UTC).date():
                records[date] = value
    if not records:
        raise ValueError("FRED series without numeric observations")
    return sorted(records.items())


@st.cache_data(ttl=60, show_spinner=False)
def market_quote(symbol):
    if symbol not in YAHOO_SYMBOLS:
        raise ValueError("Unapproved market symbol")
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/"
           + quote(symbol, safe="") + "?interval=1h&range=5d")
    payload = json.loads(_fetch(url, "query1.finance.yahoo.com").decode("utf-8"))
    rows = (payload.get("chart") or {}).get("result") or []
    if not rows:
        raise ValueError("Market quote absent")
    meta = rows[0].get("meta") or {}
    current = _number(meta.get("regularMarketPrice"))
    prior = _number(meta.get("previousClose"))
    basis = "penutupan sebelumnya"
    if prior is None:
        prior = _number(meta.get("chartPreviousClose"))
        basis = "awal rentang grafik"
    at = meta.get("regularMarketTime")
    observed = (datetime.fromtimestamp(float(at), UTC).isoformat()
                if at is not None else None)
    if current is None or current <= 0 or prior is None or prior <= 0 or not observed:
        raise ValueError("Market quote invalid")
    return {
        "value": current, "pct": (current / prior - 1) * 100,
        "observed": observed, "fresh": _recent(observed, QUOTE_MAX_AGE_SECONDS / 86400),
        "source": "Yahoo Finance · kemungkinan tertunda", "basis": basis,
    }


@st.cache_data(ttl=600, show_spinner=False)
def geopolitical_headlines():
    """Merge GDELT reports with independent publisher RSS; never assume events."""
    q = ('("missile strike" OR "missile attack" OR "airstrike" OR '
         '"drone attack" OR "military strike" OR "military escalation") '
         '(Iran OR Israel OR Ukraine OR Russia OR Taiwan OR Yemen OR "Red Sea" OR Korea) '
         'sourcelang:english')
    url = "https://api.gdeltproject.org/api/v2/doc/doc?" + urlencode({
        "query": q, "mode": "ArtList", "format": "json",
        "sort": "DateDesc", "timespan": "24h", "maxrecords": "50",
    })
    articles = []
    gdelt_ok = False
    try:
        raw = json.loads(_fetch(url, "api.gdeltproject.org").decode("utf-8"))
        rows = raw.get("articles") if isinstance(raw, dict) else None
        if not isinstance(rows, list):
            raise ValueError("GDELT response lacks article list")
        gdelt_ok = True
        for item in rows[:50]:
            if not isinstance(item, dict):
                continue
            try:
                stamp = datetime.strptime(
                    str(item.get("seendate") or ""), "%Y%m%dT%H%M%SZ"
                ).replace(tzinfo=UTC).isoformat()
            except ValueError:
                continue
            articles.append({
                "title": str(item.get("title") or "")[:400],
                "url": str(item.get("url") or "")[:1800],
                "observed": stamp,
            })
    except (ValueError, OSError, json.JSONDecodeError):
        pass
    rss, rss_error = _safe(fetch_geopolitical_rss)
    if rss:
        articles.extend(rss)
    if not gdelt_ok and rss_error:
        raise ValueError("GDELT and trusted publisher RSS are unavailable")
    seen, merged = set(), []
    for item in articles:
        href = item.get("url")
        if href and href not in seen:
            seen.add(href)
            merged.append(item)
    return merged[:100]


@st.cache_data(ttl=15, show_spinner=False)
def us2y_live():
    endpoint = "https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol"
    q = urlencode({
        "symbols": "US2Y", "requestMethod": "itv", "noform": "1",
        "partnerId": "2", "fund": "1", "exthrs": "1",
        "output": "json", "events": "1",
    })
    raw = json.loads(_fetch(endpoint + "?" + q, "quote.cnbc.com"))
    rows = (raw.get("FormattedQuoteResult") or {}).get("FormattedQuote") or []
    if not rows or str(rows[0].get("symbol") or "").upper() != "US2Y":
        raise ValueError("Cash US2Y CNBC tidak tersedia")
    r = rows[0]
    value = _number(str(r.get("last") or "").replace("%", "").replace(",", ""))
    observed = r.get("last_time")
    if value is None or not 0 < value < 30 or not _recent(observed, 120 / 86400):
        raise ValueError("Cash US2Y CNBC tidak segar")
    return {"value": value, "observed": observed, "source": "CNBC / Tradeweb"}


def _safe(call, *args):
    try:
        return call(*args), None
    except Exception as e:
        return None, type(e).__name__


@st.cache_data(ttl=30, show_spinner=False)
def cnbc_macro_quotes_cached():
    """One bounded CNBC request for DXY, haven FX, spot metals, and futures."""
    return fetch_cnbc_market_quotes()


@st.cache_data(ttl=30, show_spinner=False)
def goldapi_spot_cached(symbol):
    """Only needed if CNBC spot quote is missing/delayed."""
    return fetch_goldapi_spot(symbol)


@st.cache_data(ttl=60, show_spinner=False)
def load_external_macro_inputs():
    """CNBC primary with time-verified fallback for missing and stale DXY.

    A provider returning a symbol does NOT mean its market observation is live.
    Only a genuinely fresh, source-timestamped Yahoo DXY may replace stale
    CNBC DXY; the fallback never refreshes timestamps artificially.
    Futures remain display-only and may be exchange-delayed.
    """
    fred_codes = sorted(FRED_SERIES)
    tasks = [("fred", code) for code in fred_codes] + [
        ("cnbc", "ALL"), ("us2y", "US2Y"), ("geo", "GDELT"),
        ("oil", "WTI"), ("oil", "Brent"),
    ]
    def read(kind, code):
        fn = (fred_history if kind == "fred" else
              cnbc_macro_quotes_cached if kind == "cnbc" else
              us2y_live if kind == "us2y" else
              fetch_dia_spot if kind == "oil" else geopolitical_headlines)
        return _safe(fn, code) if kind in {"fred", "oil"} else _safe(fn)
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {key: pool.submit(read, *key) for key in tasks}
        outcomes = {key: future.result() for key, future in futures.items()}
    fast, fast_err = outcomes[("cnbc", "ALL")]
    fast = dict(fast or {})
    market = {code: fast[code] for code in YAHOO_SYMBOLS if code in fast}
    missing = [code for code in sorted(YAHOO_SYMBOLS) if code not in market]
    # The original presence-only condition left a stale CNBC DXY in place,
    # producing exactly 41% coverage (Treasury valid, DXY ineligible).
    # Recheck the source timestamp rather than marking CNBC as unavailable.
    stale_dxy = (
        ["DX-Y.NYB"]
        if "DX-Y.NYB" in market and
        not quote_freshness(market["DX-Y.NYB"])["eligible"]
        else []
    )
    fallback_candidates = sorted(set(missing + stale_dxy))
    fallback_errors: dict[str, str] = {}
    recovered: list[str] = []
    if fallback_candidates:
        with ThreadPoolExecutor(max_workers=3) as pool:
            attempts = list(pool.map(
                lambda code: _safe(market_quote, code), fallback_candidates
            ))
        for code, (q, err) in zip(fallback_candidates, attempts):
            # Yahoo's quote must be independently eligible; never substitute
            # an old vendor price just because HTTP returned successfully.
            if q is not None and quote_freshness(q)["eligible"]:
                market[code] = q
                recovered.append(code)
            elif code not in market and q is not None:
                # Keep a stale reference visible as historical only.
                market[code] = q
            if err:
                fallback_errors[code] = err
    spot: dict[str, dict | None] = {
        name: fast.get(name) for name in ("XAU_SPOT", "XAG_SPOT")
    }
    for name, provider_key in (("XAU_SPOT", "XAU"), ("XAG_SPOT", "XAG")):
        if not quote_freshness(spot.get(name))["eligible"]:
            quote, _ = _safe(goldapi_spot_cached, provider_key)
            if quote is not None and quote_freshness(quote)["eligible"]:
                spot[name] = quote
            elif spot.get(name) is None:
                spot[name] = quote
    return {
        "fred": {code: outcomes[("fred", code)][0] for code in fred_codes},
        "market": market,
        "spot": spot,
        "oil_spot": {key: outcomes[("oil", key)][0] for key in ("WTI", "Brent")},
        "us2y": outcomes[("us2y", "US2Y")],
        "geo_news": outcomes[("geo", "GDELT")],
        "source_health": {
            "cnbc_count": len(fast),
            "cnbc_error": fast_err,
            "yahoo_missing": missing,
            "yahoo_stale_dxy_recovery_attempted": bool(stale_dxy),
            "yahoo_recovered": recovered,
            "dxy_cnbc_fresh": quote_freshness(fast.get("DX-Y.NYB"))["eligible"],
            "dxy_market_fresh": quote_freshness(market.get("DX-Y.NYB"))["eligible"],
            "yahoo_errors": fallback_errors,
            "dia_wti_error": outcomes[("oil", "WTI")][1],
            "dia_brent_error": outcomes[("oil", "Brent")][1],
        },
    }


def _last(series, feeds):
    rows = feeds["fred"].get(series)
    return (rows[-1] if rows else None), None


def _yoy(series, feeds):
    rows = feeds["fred"].get(series)
    err = None if rows else "UNAVAILABLE"
    if not rows:
        return None, None, err
    date, current = rows[-1]
    d = _date(date).date()
    prev = {day: val for day, val in rows}.get(d.replace(year=d.year - 1).isoformat())
    if prev is None or prev <= 0 or not _recent(date, 120):
        return None, date, "STALE_OR_MISSING_BASE"
    return (current / prev - 1) * 100, date, None


def _fmt(n, unit="", digits=2):
    return "—" if n is None else f"{n:,.{digits}f}{unit}"


def _delta(n, suffix=""):
    return None if n is None else f"{n:+.2f}{suffix}"


def _yield_row(macro_eval, h15, symbol, fred=None):
    """Use fresh worker/H15 observations; FRED official daily if unavailable."""
    row = dict(((macro_eval or {}).get("components") or {}).get(symbol) or {})
    if (row.get("freshness") == "FRESH"
            and _recent(row.get("observed_at"), 5)
            and _number(row.get("current")) is not None
            and _number(row.get("delta")) is not None):
        return row
    fallback = dict((h15 or {}).get(symbol) or {})
    if (fallback.get("freshness") == "FRESH"
            and _recent(fallback.get("observed_at"), 5)
            and _number(fallback.get("delta")) is not None):
        return fallback
    series = FRED_YIELD_SERIES.get(symbol)
    observation = fred_daily_yield_row(symbol, (fred or {}).get(series),
                                       now=datetime.now(UTC))
    return observation or {}


def _daily_dxy_last(feeds):
    """Last published DXY session (NOT live) for regime-only view."""
    row = (feeds.get("market") or {}).get("DX-Y.NYB") or {}
    return dict(row)


def _market_or_fred(symbol, fred_series, feeds):
    data = feeds["market"].get(symbol)
    # Keep the same source in the Energy panel and the Macro conclusion.
    # CNBC futures exchange-delay is usable ONLY as a low-weight context for
    # <=15 min (never relabel as live). Daily FRED can substitute only when
    # its observation is <=48h old, not a 3+ day historical reference.
    if data and quote_freshness(data)["eligible"]:
        return data
    if data and symbol in {"CL=F", "BZ=F"}:
        stamp = _date(data.get("observed"))
        age = ((datetime.now(UTC) - stamp.astimezone(UTC)).total_seconds()
               if stamp is not None and stamp.tzinfo is not None else -1)
        if (0 <= age <= 15 * 60
                and str(data.get("source") or "").startswith(
                    "CNBC Quote Cache · futures exchange-delayed")
                and data.get("instrument_type") == "FUTURES"
                and data.get("provider_realtime") is False
                and data.get("basis") == "penutupan sebelumnya"
                and _number(data.get("value")) is not None
                and _number(data.get("pct")) is not None
                and _number(data.get("value")) > 0):
            return data
    rows = feeds["fred"].get(fred_series)
    if rows and len(rows) >= 2 and _recent(rows[-1][0], 2):
        (prev_date, previous), (date, current) = rows[-2:]
        if previous <= 0 or current <= 0:
            return data
        return {"value": current, "pct": 100 * (current / previous - 1),
                "observed": date, "fresh": True, "source": "FRED (spot harian)",
                "basis": "observasi sebelumnya"}
    return data if data else None


def _spot_oil_or_fred(name, symbol, fred_series, feeds):
    """Prefer timestamped DIA spot, then true daily physical spot; no futures."""
    direct = (feeds.get("oil_spot") or {}).get(name)
    if (direct and quote_freshness(direct)["eligible"]
            and _number(direct.get("pct")) is not None):
        return direct
    daily = _market_or_fred(symbol, fred_series, feeds)
    return daily or direct


def _market_metric(slot, title, data, *, unit=""):
    quality = quote_freshness(data)
    if not data or quality["status"] == "UNAVAILABLE":
        slot.metric(title, "BELUM TERSEDIA")
        slot.caption("Feed tidak memberikan timestamp sumber yang dapat diverifikasi.")
        return
    eligible = quality["eligible"]
    daily = quality["status"].startswith("HARIAN")
    slot.metric(title if eligible else title + (" · HARIAN" if daily else " · DELAYED"),
                _fmt(data.get("value"), unit),
                delta=_delta(data.get("pct"), "%") if eligible else None)
    age = ("—" if quality["age_minutes"] is None else
           f"{quality['age_minutes']:.1f} menit")
    slot.caption(
        f"Status {quality['status']} · timestamp sumber "
        f"{quality['observed_wib']} WIB · usia {age} · "
        f"{data.get('source') or '—'} · basis: {data.get('basis') or '—'}"
    )
    if not eligible:
        slot.caption("Hanya harga referensi; tidak berlaku sebagai konfirmasi intraday.")


def _selected_dxy(macro_eval, feeds):
    """Prefer source-timestamped CNBC DXY, then independently fresh worker proxy."""
    dxy = feeds["market"].get("DX-Y.NYB")
    if dxy and quote_freshness(dxy)["eligible"]:
        return dxy
    row = (macro_eval or {}).get("dxy_intraday") or {}
    if (row.get("freshness") == "FRESH"
            and _number(row.get("current")) is not None
            and _number(row.get("net_pct")) is not None
            and _recent(row.get("current_at"), QUOTE_MAX_AGE_SECONDS / 86400)):
        return {
            "value": float(row["current"]),
            "pct": float(row["net_pct"]),
            "observed": row["current_at"],
            "fresh": True,
            "source": row.get("source") or "Macro worker DXY",
            "basis": "referensi intraday worker",
        }
    return dxy


@st.cache_data(ttl=15, show_spinner=False)
def load_macro_m15_snapshot_readonly():
    """Always read a validated LIVE 7903 M15. Never silently use stale reversal."""
    from .xau_m15_market_feed import fetch_fast_m15
    return fetch_fast_m15()


def render_gold_macro_conclusion(macro_eval, h15_loader, *, event_risk=None):
    """Render a single aggregate XAU macro verdict at the TOP of the Macro tab."""
    feeds = load_external_macro_inputs()
    h15, _ = _safe(h15_loader)
    yield_rows = {
        key: _yield_row(macro_eval, h15, key, feeds.get("fred"))
        for key in ("US2Y", "US10Y", "REAL_YIELD_10Y")
    }
    daily_regime = assess_daily_regime(
        yields=yield_rows, dxy_last=_daily_dxy_last(feeds),
        now=datetime.now(UTC),
    )
    pce, _, _ = _yoy("PCEPI", feeds)
    cpi, _, _ = _yoy("CPIAUCSL", feeds)
    wti = _spot_oil_or_fred("WTI", "CL=F", "DCOILWTICO", feeds)
    brent = _spot_oil_or_fred("Brent", "BZ=F", "DCOILBRENTEU", feeds)
    gold = (feeds.get("spot") or {}).get("XAU_SPOT")
    silver = (feeds.get("spot") or {}).get("XAG_SPOT")
    selected_dxy = _selected_dxy(macro_eval, feeds)
    result = analyze_gold_macro(
        yields=yield_rows,
        dxy=selected_dxy,
        pce_yoy=pce, cpi_yoy=cpi,
        oil={"WTI": wti, "Brent": brent},
        metals={"Gold": gold, "Silver": silver},
        fed_repricing=(macro_eval or {}).get("fed_repricing_proxy"),
        geopolitical_articles=(feeds.get("geo_news") or (None, "NO_FEED"))[0],
        geopolitical_news_error=(feeds.get("geo_news") or (None, "NO_FEED"))[1],
        haven_markets={
            "^VIX": feeds["market"].get("^VIX"),
            "JPY=X": feeds["market"].get("JPY=X"),
            "CHF=X": feeds["market"].get("CHF=X"),
        },
    )

    # M15 directional context is shown before the long macro breakdown.
    # It remains read-only; stale/missing source yields WAIT_DATA, never a call.
    render_macro_m15_forecast(
        result, snapshot_loader=load_macro_m15_snapshot_readonly,
        event_risk=event_risk,
    )

    st.subheader("KESIMPULAN GABUNGAN MAKRO GOLD")
    st.caption("RIZAN Macro Spot V4 · WTI/Brent DIA spot indikatif (atau FRED harian), "
               "XAU/XAG spot OTC indikatif, DXY/VIX/FX CNBC. "
               "Setiap bobot menggunakan timestamp asli; tidak menggunakan futures.")
    provider_status = feeds.get("source_health") or {}
    if provider_status.get("cnbc_count"):
        st.caption(f"CNBC public batch: {provider_status['cnbc_count']} simbol tersedia · "
                   "cache 30–60 detik · label live hanya jika timestamp ≤5 menit.")
    else:
        st.warning("CNBC fast feed tidak tersedia. Yahoo fallback digunakan bila tersedia; "
                   "jangan anggap harga lama sebagai live.")
    a, b, c = st.columns(3)
    a.metric("Bias XAUUSD", result["bias"])
    b.metric("Indeks arah makro", "—" if result["score"] is None
             else f"{result['score']:+d} / 100")
    c.metric("Cakupan feed", f"{result['coverage_pct']}%")
    dxy_status = quote_freshness(selected_dxy)
    if result["state"] == "WAIT_DATA":
        st.error(
            "Kesimpulan gabungan belum valid: " +
            (", ".join(result["missing"]) if result["missing"] else "feed inti tidak lengkap") +
            ". Ini adalah kegagalan kualitas data, bukan indikasi bearish/bullish."
        )
        st.caption(
            "Status DXY: " + dxy_status["status"] +
            " · sumber " + str((selected_dxy or {}).get("source") or "tidak ada") +
            " · waktu observasi WIB " + str(dxy_status.get("observed_wib") or "—") +
            " · usia " + str(dxy_status.get("age_minutes") if dxy_status.get("age_minutes") is not None else "—") +
            " menit. CNBC " + str(provider_status.get("cnbc_count") or 0) +
            " simbol terunduh bukan berarti semua quote segar."
        )
        if provider_status.get("yahoo_stale_dxy_recovery_attempted"):
            st.caption(
                "Fallback Yahoo DXY dicoba karena CNBC DXY tidak segar; " +
                ("berhasil dengan timestamp valid."
                 if "DX-Y.NYB" in provider_status.get("yahoo_recovered", [])
                 else "belum menghasilkan quote yang lolos batas 5 menit.")
            )
    # Explicit oil verdict belongs to the combined XAU macro conclusion,
    # not only the lower-level oil diagnostics.
    oil_component = explain_oil_component(result)
    st.write("**WTI + Brent dalam kesimpulan makro XAU:** " + oil_component["headline"])
    st.caption(oil_component["detail"])
    with st.container(border=True):
        st.markdown("**CADANGAN: REGIME MAKRO HARIAN (bukan sinyal live)**")
        st.caption("Menggunakan perubahan yield resmi harian terakhir (worker/H.15/FRED) "
                   "dan perubahan DXY terhadap penutupan sebelumnya. "
                   "Saat DXY intraday berhenti bergerak, skor regime tetap "
                   "tersedia selama data terakhir masih memenuhi batas usia.")
        daily_a, daily_b = st.columns(2)
        daily_a.metric("Bias regime", daily_regime["bias"])
        daily_b.metric("Skor regime", "—" if daily_regime["score"] is None
                       else f"{daily_regime['score']:+d} / 100")
        st.caption(
            f"Cakupan regime harian: {daily_regime['coverage_pct']}% · "
            f"DXY: {daily_regime['dxy_source'] or 'tidak ada'} · "
            f"last published: {daily_regime['dxy_timestamp'] or '—'} UTC. "
            "Regime bukan validasi entry M5/M15, tidak menggantikan skor intraday."
        )
        if daily_regime["score"] is None:
            st.warning("Fallback regime belum lengkap: " +
                       ", ".join(daily_regime["missing"]))
        elif result["state"] == "WAIT_DATA":
            st.info("Skor intraday tetap WAIT_DATA; latar belakang regime "
                    "ditampilkan sebagai informasi dengan keyakinan lebih rendah.")
    with st.expander("Diagnostik sumber makro & penyebab WAIT DATA"):
        for comp in daily_regime["components"]:
            st.caption(
                f"{comp['name']}: " +
                ("VALID" if comp["valid"] else "MISSING/STALE") +
                f" · {comp['provider'] or '—'} · "
                f"Δ {comp['delta_bps'] if comp['delta_bps'] is not None else '—'} bps "
                f"· timestamp {comp['timestamp'] or '—'}"
            )
        st.caption("Kekurangan intraday: " +
                   (", ".join(result["missing"]) if result["missing"] else "Tidak ada"))
        source_errors = (feeds.get("source_health") or {})
        st.caption(
            "Status CNBC: " +
            (str(source_errors.get("cnbc_count") or 0) + " simbol") +
            " · Error: " + str(source_errors.get("cnbc_error") or "tidak ada")
        )
    oil_view = result["oil_assessment"]
    wti_top, brent_top = (oil_view["quotes"].get(name) or {}
                          for name in ("WTI", "Brent"))
    st.caption(
        "Sumber skor Oil: WTI " +
        (_fmt(wti_top.get("value"), " USD/barel") + " · " +
         str(wti_top.get("status") or "UNAVAILABLE")) +
        " | Brent " +
        (_fmt(brent_top.get("value"), " USD/barel") + " · " +
         str(brent_top.get("status") or "UNAVAILABLE")) +
        " · instrumen dan timestamp tercantum di bawah. "
        "Bobot heuristik, bukan akurasi yang telah divalidasi.")
    st.caption("Kekuatan: " + result["strength"] +
               " · Horizon: " + result["horizon"] +
               " · skor heuristik, BUKAN probabilitas atau akurasi historis.")

    if result["state"] == "WAIT_DATA":
        st.warning("SKOR INTRADAY: WAIT DATA · " + result["rationale"] +
                   " Kurang: " + ", ".join(result["missing"]) +
                   ". Lihat REGIME HARIAN sebagai konteks cadangan, bukan sinyal entry.")
    elif result["state"] in {"CONFLICT", "OIL_CONFLICT", "RISK_CONFLICT"}:
        st.warning(result["bias"] + " · " + result["rationale"])
    elif result["bias"] == "BULLISH XAU":
        st.success("TAILWIND EMAS · " + result["rationale"])
    elif result["bias"] == "BEARISH XAU":
        st.warning("HEADWIND EMAS · " + result["rationale"])
    else:
        st.info("NETRAL / MIXED · " + result["rationale"])

    def names(rows):
        return ", ".join(item["name"] for item in rows) or "Tidak ada"
    st.write("**Mendukung BUY:** " + names(result["bullish"]) +
             "  |  **Mendukung SELL:** " + names(result["bearish"]))
    if result["neutral"]:
        st.caption("Belum directional: " + names(result["neutral"]))

    st.markdown("**OIL → INFLASI → THE FED → REAL YIELD | RISIKO GEOPOLITIK**")
    for symbol in ("WTI", "Brent"):
        q = oil_view["quotes"][symbol]
        if q["value"] is None:
            st.write(f"**{symbol}:** BELUM TERSEDIA")
        else:
            change = "—" if q["pct"] is None else f"{q['pct']:+.2f}%"
            st.write(f"**{symbol}:** USD {q['value']:.2f}/barel ({change}) · "
                     f"**{q['status']}**")
        if q["observed"] is not None:
            observed_wib = datetime.fromisoformat(q["observed"]).astimezone(
                ZoneInfo("Asia/Jakarta")).strftime("%d/%m %H:%M:%S")
            age = ("—" if q["age_minutes"] is None else
                   f"{q['age_minutes']:.1f} menit")
            st.caption(f"Timestamp {symbol}: {observed_wib} WIB · usia {age} · "
                       f"{q['source']} · basis {q['basis'] or '—'}")
    if any(str(oil_view["quotes"][name]["status"]) == "SPOT_NO_BASELINE"
           for name in ("WTI", "Brent")):
        st.warning("Harga spot tersedia, tetapi histori perubahan 10–20 menit "
                   "belum lengkap; bobot dari spot = 0% sampai data cukup.")
    elif any(str(oil_view["quotes"][name]["status"]).startswith(("DELAYED", "STALE"))
             for name in ("WTI", "Brent")):
        st.warning("QUOTE OIL DELAYED. Data tidak memenuhi kontrak waktu/kualitas "
                   "untuk skor Oil; harga tetap referensi.")
    st.caption("Cache market quote ±60 detik; harga pasar Yahoo Finance dapat "
               "tertunda oleh penyedia. Timestamp sumber, bukan waktu refresh "
               "aplikasi, menentukan kelayakan skor.")
    st.write("**Kesimpulan Oil:** " + oil_view["summary"])
    st.write("**Implikasi XAU melalui inflasi:** " + oil_view["xau_inflation_bias"])
    st.caption("Jalur inflasi/Fed: " + oil_view["inflation_path"])
    st.caption("Jalur geopolitik/safe haven: " + oil_view["safe_haven_path"])
    if result["score"] is None:
        st.write("**Kontribusi Oil ke skor:** BELUM DINILAI · skor utama WAIT_DATA; "
                 "WTI/Brent tetap ditampilkan sebagai konteks.")
    else:
        st.write(
            "**Kontribusi Oil ke skor:** " +
            (f"AKTIF · bobot {result['oil_weight_pct']}% · "
             f"kontribusi {result['score_breakdown']['Oil']:+.1f} poin"
             if result["oil_score_counted"] else "TIDAK AKTIF · bobot 0%")
        )
    st.caption(oil_view["score_reason"])
    if result["core_score"] is not None:
        st.caption(
            f"Skor Treasury–DXY tanpa Oil: {result['core_score']:+d} · "
            f"skor gabungan setelah Oil: {result['score']:+d} / 100 · "
            f"cakupan core: {result['coverage_core_pct']}% · "
            f"cakupan gabungan: {result['coverage_pct']}%"
        )
    st.caption(
        "Oil satu cluster WTI+Brent: spot dengan prior close valid ≤5 menit 15%; "
        "momentum spot DIA 10–20 menit 5%; FRED spot harian ≤48 jam 8%; "
        "futures tidak dihitung. "
        "Geopolitik dan safe haven masing-masing maksimal 5% dan baru dinilai "
        "berdasarkan peliputan multi-sumber serta konfirmasi pasar. "
        "Skor belum terkalibrasi; tidak mengotorisasi order cBot."
    )

    geo = result["geo_haven_assessment"]
    st.markdown("**GEOPOLITICAL RISK & SAFE HAVEN — SKOR TERVERIFIKASI**")
    st.write("**Status risiko:** " + geo["status"])
    st.write(
        f"**Kontribusi skor:** Geopolitik "
        f"{result['score_breakdown']['Geopolitical'] if result['score_breakdown']['Geopolitical'] is not None else '—'} poin "
        f"(bobot {result['geo_weight_pct']}%) · Safe Haven "
        f"{result['score_breakdown']['Safe Haven'] if result['score_breakdown']['Safe Haven'] is not None else '—'} poin "
        f"(bobot {result['haven_weight_pct']}%)"
    )
    market_risk = geo["market_pct"]
    st.caption(
        "VIX: " + ("—" if market_risk["VIX"] is None else f"{market_risk['VIX']:+.2f}%") +
        " · USDJPY: " + ("—" if market_risk["USDJPY"] is None else f"{market_risk['USDJPY']:+.2f}%") +
        " · USDCHF: " + ("—" if market_risk["USDCHF"] is None else f"{market_risk['USDCHF']:+.2f}%") +
        " (vs previous close; hanya quote segar <=5 menit)."
    )
    articles, article_error = feeds.get("geo_news") or (None, "NO_FEED")
    st.caption("Berita geopolitik: " + geo["news_status"] +
               f" · artikel indeks/RSS: {len(articles or [])}" +
               (" · " + geo["reported_region"] if geo["reported_region"] else "") +
               (" · feed error: " + geo["news_error"] if geo["news_error"] else ""))
    for item in geo["news_evidence"]:
        st.caption(f"Media: {item['source']} · {item['observed']} UTC · {item['title']}")
    st.caption(geo["summary"])
    if result["core_score"] is not None:
        st.caption("Alokasi final: Treasury "
                   f"{(1-(result['oil_weight_pct'] + result['geo_weight_pct'] + result['haven_weight_pct'])/100)*55:.2f}%"
                   " · DXY "
                   f"{(1-(result['oil_weight_pct'] + result['geo_weight_pct'] + result['haven_weight_pct'])/100)*45:.2f}%"
                   f" · Oil {result['oil_weight_pct']}% "
                   f" · Geo {result['geo_weight_pct']}% "
                   f" · Safe Haven {result['haven_weight_pct']}%. "
                   "Total alokasi = 100% jika data core valid; belum dikalibrasi.")

    risk = event_risk or {}
    state = str(risk.get("state") or "UNAVAILABLE")
    if state not in {"CLEAR", "UNAVAILABLE"}:
        st.warning("EVENT RISK: " + state + " · " +
                   str(risk.get("action") or "Perhatikan jadwal rilis; hindari chase menjelang berita."))
    else:
        st.caption("Event risk: " + state +
                   " · pastikan waktu rilis dan konferensi FOMC sebelum memasang order manual.")

    with st.expander("Rincian faktor, tanggal data, dan alasan perhitungan", expanded=False):
        st.dataframe([
            {
                "Indikator": factor["name"],
                "Efek XAU": ("BULLISH" if factor["direction"] == 1 else
                            "BEARISH" if factor["direction"] == -1 else
                            "FLAT" if factor["direction"] == 0 else "UNAVAILABLE"),
                "Keterangan": factor["reason"],
                "Sumber": factor.get("source") or "—",
                "Waktu observasi (UTC)": str(factor.get("observed_at") or "—"),
                "Dalam skor": bool(factor.get("counted")),
            }
            for factor in result["factors"]
        ], hide_index=True, use_container_width=True)
        st.markdown("**Makro pendukung (tidak dihitung ganda):**")
        for line in result["context"]:
            st.caption("• " + line)
        st.caption("Perhitungan: Treasury (real yield 50%, US2Y 30%, US10Y 20% "
                   "di dalam kelompok) + DXY, mempertahankan rasio 55:45 dari sisa bobot. "
                   "Oil: 15% spot dengan prior-close; 5% momentum DIA 10–20 menit; "
                   "8% FRED spot harian ≤48 jam. "
                   "Geopolitical risk dan safe haven: masing-masing 5% bila koroborasi "
                   "berita serta pasar valid. Futures tidak digunakan. "
                   "Data core hilang/stale = WAIT_DATA. Bobot belum diuji out-of-sample.")

    st.info("KESIMPULAN EKSEKUSI: " +
            ("WAIT — data makro utama belum lengkap. " if result["score"] is None else
             "Makro hanya filter arah, bukan sinyal trading. ") +
            "Tetap gunakan H1 untuk bias/zona, M15 untuk validasi reversal/MSS, "
            "dan M5 untuk timing serta SL/TP struktural. "
            "Tidak mengubah strategi, bridge, atau order cBot.")
    return result



def _oil_direction_caption(wti, brent, *, now=None) -> str:
    """Display-only oil momentum. Missing or non-comparable changes = no vote."""
    quotes = (wti, brent)
    if not all(isinstance(row, dict) for row in quotes):
        return "Momentum WTI/Brent belum lengkap; tidak ada konfirmasi inflasi energi."
    # Daily FRED and delayed quote timestamps must never appear intraday LIVE.
    if not all(quote_freshness(row, now=now)["eligible"] for row in quotes):
        return "Momentum minyak intraday belum segar; harga terakhir hanya referensi."
    values = [_number(row.get("pct")) for row in quotes]
    if any(value is None for value in values):
        return "Harga minyak tersedia, tetapi baseline perubahan WTI/Brent belum lengkap; arah tidak dinilai."
    # Different reference bases are not independently comparable momentum.
    bases = [str(row.get("basis") or "").strip() for row in quotes]
    if not all(bases) or bases[0] != bases[1]:
        return "Perubahan WTI/Brent memakai basis berbeda/belum diketahui; arah gabungan tidak dinilai."
    if values[0] > 0 and values[1] > 0:
        return "Energi naik terhadap basis sebanding; tekanan inflasi bisa meningkat."
    if values[0] < 0 and values[1] < 0:
        return "Energi turun terhadap basis sebanding; tekanan inflasi bisa mereda."
    return "WTI dan Brent mixed/flat; belum ada konfirmasi arah inflasi energi."



def render_macro_risk_monitor(macro_eval, h15_loader):
    """Additional display-only panel; no interaction with strategy or broker."""
    macro_eval = macro_eval or {}
    st.divider()
    st.header("MONITOR MAKRO XAU — 4 PILAR")
    st.caption("Data independen, hanya untuk analisis manual. Refresh dashboard 60 detik; "
               "tiap sumber punya frekuensi dan timestamp sendiri. Tidak mengubah sinyal cBot.")

    feeds = load_external_macro_inputs()
    h15, h15_err = _safe(h15_loader)
    st.subheader("1 · Treasury AS: US2Y + US10Y")
    us2 = _yield_row(macro_eval, h15, "US2Y")
    us10 = _yield_row(macro_eval, h15, "US10Y")
    c1, c2 = st.columns(2)
    for col, symbol, row in ((c1, "US2Y (DGS2)", us2), (c2, "US10Y (DGS10)", us10)):
        col.metric(symbol, _fmt(_number(row.get("current")), "%", 3),
                   delta=_delta(_number(row.get("delta")), " bps"))
        col.caption(f"{row.get('provider') or 'BELUM TERSEDIA'} · "
                    f"observasi {str(row.get('observed_at') or '—')[:10]}")
    if us2 and us10 and str(us2.get("observed_at"))[:10] == str(us10.get("observed_at"))[:10]:
        spread = (_number(us10["current"]) - _number(us2["current"])) * 100
        st.metric("Spread 10Y − 2Y", _fmt(spread, " bps", 1))
    else:
        st.caption("Spread 10Y−2Y tidak dihitung bila tanggal observasi berbeda/kurang data.")
    recent_two_year = feeds["fred"].get("DGS2")
    if recent_two_year and len(recent_two_year) >= 5 and _recent(recent_two_year[-1][0], 7):
        last_five = recent_two_year[-5:]
        last_value = last_five[-1][1]
        peak = max(val for _, val in last_five)
        st.caption("US2Y (5 observasi): " +
                   ("TERTINGGI 5 SESI" if last_value >= peak else
                    f"di bawah high 5 sesi {_fmt(peak, '%', 3)}") +
                   f" · observasi {last_five[-1][0]} · FRED DGS2")
    else:
        st.caption("Status tertinggi 5 sesi US2Y belum dapat diverifikasi.")
    if us2 and us10:
        d2, d10 = _number(us2.get("delta")), _number(us10.get("delta"))
        if d2 is not None and d10 is not None:
            if d2 >= 1 and d10 >= 1:
                st.caption("Treasury: kedua yield naik harian → tekanan potensial terhadap XAU.")
            elif d2 <= -1 and d10 <= -1:
                st.caption("Treasury: kedua yield turun harian → dukungan potensial terhadap XAU.")
            else:
                st.caption("Treasury: yield mixed/flat; tidak ada konfirmasi tekanan searah.")
    live, live_error = feeds["us2y"]
    if live:
        st.success("Cash US2Y intraday: " + _fmt(live["value"], "%", 3)
                   + " · " + str(live["observed"]) + " · CNBC/Tradeweb")
    else:
        st.caption("Cash US2Y intraday: BELUM TERSEDIA / tidak segar "
                   f"({live_error or 'sumber kosong'}). US2Y daily tetap ditampilkan.")
    if not (us2 and us10):
        st.warning("Data yield daily tidak lengkap; H.15/FRED: " + (h15_err or "observasi tidak segar"))
    st.caption("US2Y sensitif pada ekspektasi kebijakan Fed; US10Y juga memuat premi tenor. "
               "Kenaikan yield dapat menekan XAU, tetapi bukan sinyal SELL otomatis.")

    st.subheader("2 · Ekspektasi Fed dan inflasi")
    policy, _ = _last("DFEDTARU", feeds)
    cpi, cpi_date, cpi_error = _yoy("CPIAUCSL", feeds)
    pce, pce_date, pce_error = _yoy("PCEPILFE", feeds)
    headline, headline_date, headline_error = _yoy("PCEPI", feeds)
    p1, p2 = st.columns(2)
    valid_policy = policy is not None and _recent(policy[0], 7)
    p1.metric("Fed target upper", _fmt(policy[1], "%") if valid_policy else "—")
    p1.caption("FRED DFEDTARU · " + (policy[0] if policy else "belum tersedia"))
    p2.metric("CPI YoY", _fmt(cpi, "%"))
    p2.caption("FRED CPIAUCSL · " + str(cpi_date or cpi_error or "belum tersedia"))
    p3, p4 = st.columns(2)
    p3.metric("PCE headline YoY", _fmt(headline, "%"))
    p3.caption("FRED PCEPI · " + str(headline_date or headline_error or "belum tersedia"))
    p4.metric("Core PCE YoY", _fmt(pce, "%"))
    p4.caption("FRED PCEPILFE · " + str(pce_date or pce_error or "belum tersedia"))
    if headline is not None:
        st.caption("Inflasi PCE vs target Fed 2%: " +
                   ("DI ATAS TARGET" if headline > 2 else
                    "DI BAWAH TARGET" if headline < 2 else "PADA TARGET") +
                   ". Ini tidak berarti Fed pasti menaikkan/menahan suku bunga.")
    st.markdown("[Probabilitas FOMC terbaru: CME FedWatch](https://www.cmegroup.com/markets/interest-rates/cme-fedwatch-tool.html)")
    st.caption("Probabilitas cut/hold/hike tidak disalin menjadi angka otomatis karena belum ada "
               "feed probabilitas yang terverifikasi. Angka inflasi = YoY, bukan surprise vs konsensus. "
               "PCE adalah metrik inflasi kebijakan Fed; CPI indikator pelengkap.")

    st.subheader("3 · Energi dan risiko inflasi")
    wti = (feeds.get("oil_spot") or {}).get("WTI") or _spot_oil_or_fred(
        "WTI", "CL=F", "DCOILWTICO", feeds)
    brent = (feeds.get("oil_spot") or {}).get("Brent") or _spot_oil_or_fred(
        "Brent", "BZ=F", "DCOILBRENTEU", feeds)
    oil1, oil2 = st.columns(2)
    _market_metric(oil1, "WTI spot indikatif (USD/barel)", wti)
    _market_metric(oil2, "Brent spot indikatif (USD/barel)", brent)
    # The scored Oil channel may use genuinely DAILY FRED as a separate
    # lower-weight context. Never relabel delayed futures as live spot.
    # An indicative spot quote can be fresh with pct=None when its
    # separate 10–20-minute baseline has not formed. Never infer a direction
    # from the fresh flag alone or compare a None/NaN pct to zero.
    st.caption(_oil_direction_caption(wti, brent))
    st.caption("DIA WTI/Brent adalah spot indikatif (bukan bid/ask broker). "
               "Keterangan persen: perubahan dari observasi DIA 10–20 menit sebelumnya; "
               "maksimum bobot momentum 5% hanya saat kedua quote segar ≤5 menit. "
               "Sebelum riwayat terbentuk, tidak ada suara spot. "
               "FRED physical spot harian adalah sumber skor cadangan 8%.")

    st.subheader("4 · Dolar AS dan logam mulia")
    st.caption("Yahoo Finance dapat tertunda meski cache diperbarui setiap 60 detik. "
               "Sumber quote harus berusia maksimal 5 menit untuk status FRESH; "
               "data DELAYED adalah harga terakhir, bukan harga live.")
    dxy = feeds["market"].get("DX-Y.NYB")
    if not quote_freshness(dxy)["eligible"]:
        d = macro_eval.get("dxy_intraday") or {}
        if (_number(d.get("current")) is not None
                and _number(d.get("net_pct")) is not None
                and _recent(d.get("current_at"), QUOTE_MAX_AGE_SECONDS / 86400)
                and d.get("freshness") == "FRESH"):
            dxy = {"value": float(d["current"]), "pct": float(d["net_pct"]),
                   "observed": d["current_at"], "fresh": True,
                   "source": str(d.get("source") or "Macro worker"),
                   "basis": "referensi intraday worker"}
    gold = (feeds.get("spot") or {}).get("XAU_SPOT")
    silver = (feeds.get("spot") or {}).get("XAG_SPOT")
    dx, au, ag = st.columns(3)
    _market_metric(dx, "DXY", dxy)
    _market_metric(au, "Gold spot XAU/USD", gold)
    _market_metric(ag, "Silver spot XAG/USD", silver)
    if any(not quote_freshness(item)["eligible"] for item in (dxy, gold, silver)):
        st.warning("Sebagian feed DXY/XAU spot/XAG spot tidak segar. "
                   "Harga terakhir hanya referensi, bukan konfirmasi saat ini.")
    if all(quote_freshness(item)["eligible"] and _number(item.get("pct")) is not None
           for item in (dxy, gold, silver)):
        if dxy["pct"] > 0 and gold["pct"] < 0 and silver["pct"] < 0:
            st.caption("DXY menguat bersamaan dengan pelemahan spot XAU dan XAG.")
        else:
            st.caption("Tekanan DXY terhadap spot XAU/XAG belum searah.")
    else:
        st.caption("Perubahan spot vs penutupan sebelumnya belum lengkap; "
                   "tidak dibuat sinyal lintas aset.")
    st.caption("Spot XAU/XAG adalah OTC indikatif, bukan bid/ask FP Markets cTrader. "
               "Arah emas tidak disimpulkan dari satu quote yang tidak punya baseline.")

    st.info("KESIMPULAN OPERASIONAL: konteks makro saja, BUKAN sinyal entry. "
            "Konfirmasi di H1 (bias/zona), M15 (MSS/reversal), M5 (refinement). "
            "Jika feed hilang atau stale, status BELUM TERSEDIA — tidak diasumsikan bearish.")

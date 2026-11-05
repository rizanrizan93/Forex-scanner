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

from .xau_macro_gold_consensus import analyze_gold_macro
from .xau_market_quote_health import quote_freshness, QUOTE_MAX_AGE_SECONDS


FRED_SERIES = {
    "CPIAUCSL", "PCEPILFE", "PCEPI", "DFEDTARU", "DGS2",
    "DCOILWTICO", "DCOILBRENTEU",
}
YAHOO_SYMBOLS = {"DX-Y.NYB", "GC=F", "SI=F", "CL=F", "BZ=F", "^VIX", "JPY=X", "CHF=X"}
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
    """Discover time-stamped articles, not verified events or trading triggers.

    GDELT only indexes/report-matches headlines; independent reputable domains
    and risk-off prices must both corroborate before any macro vote.
    """
    q = ('("missile strike" OR "missile attack" OR "airstrike" OR '
         '"drone attack" OR "military strike" OR "military escalation") '
         '(Iran OR Israel OR Ukraine OR Russia OR Taiwan OR Yemen OR "Red Sea" OR Korea) '
         'sourcelang:english')
    url = "https://api.gdeltproject.org/api/v2/doc/doc?" + urlencode({
        "query": q, "mode": "ArtList", "format": "json",
        "sort": "DateDesc", "timespan": "24h", "maxrecords": "50",
    })
    raw = json.loads(_fetch(url, "api.gdeltproject.org").decode("utf-8"))
    articles = raw.get("articles") if isinstance(raw, dict) else None
    if not isinstance(articles, list):
        raise ValueError("GDELT document response lacks article list")
    result = []
    for article in articles[:50]:
        if not isinstance(article, dict):
            continue
        seen = str(article.get("seendate") or "")
        try:
            observed = datetime.strptime(seen, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC).isoformat()
        except ValueError:
            continue
        result.append({
            "title": str(article.get("title") or "")[:400],
            "url": str(article.get("url") or "")[:1800],
            "observed": observed,
        })
    return result


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


@st.cache_data(ttl=60, show_spinner=False)
def load_external_macro_inputs():
    """Parallel bounded requests; cache even failed sources to keep UI responsive."""
    fred_codes = sorted(FRED_SERIES)
    market_codes = sorted(YAHOO_SYMBOLS)
    tasks = [("fred", code) for code in fred_codes] + [
        ("market", code) for code in market_codes
    ] + [("us2y", "US2Y"), ("geo", "GDELT")]
    def read(kind, code):
        fn = (fred_history if kind == "fred" else
              market_quote if kind == "market" else
              us2y_live if kind == "us2y" else geopolitical_headlines)
        return _safe(fn, code) if kind in {"fred", "market"} else _safe(fn)
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {key: pool.submit(read, *key) for key in tasks}
        outcomes = {key: future.result() for key, future in futures.items()}
    return {
        "fred": {code: outcomes[("fred", code)][0] for code in fred_codes},
        "market": {code: outcomes[("market", code)][0] for code in market_codes},
        "us2y": outcomes[("us2y", "US2Y")],
        "geo_news": outcomes[("geo", "GDELT")],
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


def _yield_row(macro_eval, h15, symbol):
    row = dict((macro_eval.get("components") or {}).get(symbol) or {})
    if (row.get("freshness") == "FRESH"
            and _recent(row.get("observed_at"), 5)
            and _number(row.get("current")) is not None
            and _number(row.get("delta")) is not None):
        return row
    fallback = dict((h15 or {}).get(symbol) or {})
    if (fallback.get("freshness") == "FRESH"
            and _recent(fallback.get("observed_at"), 5)):
        return fallback
    return {}


def _market_or_fred(symbol, fred_series, feeds):
    data = feeds["market"].get(symbol)
    if data and data["fresh"]:
        return data
    rows = feeds["fred"].get(fred_series)
    if rows and len(rows) >= 2 and _recent(rows[-1][0], 7):
        (prev_date, previous), (date, current) = rows[-2:]
        return {"value": current, "pct": 100 * (current / previous - 1),
                "observed": date, "fresh": True, "source": "FRED (spot harian)",
                "basis": "observasi sebelumnya"}
    return data if data else None


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
    """Prefer time-stamped Yahoo DXY, then independently fresh worker proxy."""
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


def render_gold_macro_conclusion(macro_eval, h15_loader, *, event_risk=None):
    """Render a single aggregate XAU macro verdict at the TOP of the Macro tab."""
    feeds = load_external_macro_inputs()
    h15, _ = _safe(h15_loader)
    yield_rows = {
        key: _yield_row(macro_eval, h15, key)
        for key in ("US2Y", "US10Y", "REAL_YIELD_10Y")
    }
    pce, _, _ = _yoy("PCEPI", feeds)
    cpi, _, _ = _yoy("CPIAUCSL", feeds)
    wti = _market_or_fred("CL=F", "DCOILWTICO", feeds)
    brent = _market_or_fred("BZ=F", "DCOILBRENTEU", feeds)
    gold = feeds["market"].get("GC=F")
    silver = feeds["market"].get("SI=F")
    result = analyze_gold_macro(
        yields=yield_rows,
        dxy=_selected_dxy(macro_eval, feeds),
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

    st.subheader("KESIMPULAN GABUNGAN MAKRO GOLD")
    st.caption("RIZAN Macro Synthesis V3 · Treasury/DXY + Oil + konfirmasi Geopolitical Risk "
               "dan Safe Haven (VIX, JPY, CHF). Tidak ada asumsi geopolitik dari Oil; "
               "bobot risiko aktif hanya bila bukti berita/pasar memenuhi syarat.")
    a, b, c = st.columns(3)
    a.metric("Bias XAUUSD", result["bias"])
    b.metric("Indeks arah makro", "—" if result["score"] is None
             else f"{result['score']:+d} / 100")
    c.metric("Cakupan feed", f"{result['coverage_pct']}%")
    st.caption("Kekuatan: " + result["strength"] +
               " · Horizon: " + result["horizon"] +
               " · skor heuristik, BUKAN probabilitas atau akurasi historis.")

    if result["state"] == "WAIT_DATA":
        st.warning("WAIT DATA · " + result["rationale"] +
                   " Kurang: " + ", ".join(result["missing"]))
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

    oil_view = result["oil_assessment"]
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
    if any(oil_view["quotes"][name]["status"] == "DELAYED"
           for name in ("WTI", "Brent")):
        st.warning("QUOTE OIL DELAYED (>5 MENIT). Harga terakhir hanya referensi; "
                   "tidak dihitung sebagai sinyal Oil intraday pada skor XAU.")
    st.caption("Cache market quote ±60 detik; harga pasar Yahoo Finance dapat "
               "tertunda oleh penyedia. Timestamp sumber, bukan waktu refresh "
               "aplikasi, menentukan kelayakan skor.")
    st.write("**Kesimpulan Oil:** " + oil_view["summary"])
    st.write("**Implikasi XAU melalui inflasi:** " + oil_view["xau_inflation_bias"])
    st.caption("Jalur inflasi/Fed: " + oil_view["inflation_path"])
    st.caption("Jalur geopolitik/safe haven: " + oil_view["safe_haven_path"])
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
        "Oil adalah satu cluster WTI+Brent: hanya quote intraday dengan usia <=5 menit "
        "yang dapat memberi bobot 15%, sedangkan FRED harian valid maksimal 8%. "
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
        " (vs previous close; hanya quote segar <=90 menit)."
    )
    st.caption("Berita geopolitik: " + geo["news_status"] +
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
                   "Oil: 15% futures intraday bila timestamp quote <=5 menit, "
                   "8% FRED spot harian bila valid ≤48 jam. "
                   "Geopolitical risk dan safe haven: masing-masing 5% bila koroborasi "
                   "berita serta pasar valid. Quote terlambat tidak masuk skor Oil intraday. "
                   "Data core hilang/stale = WAIT_DATA. Bobot belum diuji out-of-sample.")

    st.info("KESIMPULAN EKSEKUSI: " +
            ("WAIT — data makro utama belum lengkap. " if result["score"] is None else
             "Makro hanya filter arah, bukan sinyal trading. ") +
            "Tetap gunakan H1 untuk bias/zona, M15 untuk validasi reversal/MSS, "
            "dan M5 untuk timing serta SL/TP struktural. "
            "Tidak mengubah strategi, bridge, atau order cBot.")
    return result


def render_macro_risk_monitor(macro_eval, h15_loader):
    """Additional display-only panel; no interaction with strategy or broker."""
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
    wti = _market_or_fred("CL=F", "DCOILWTICO", feeds)
    brent = _market_or_fred("BZ=F", "DCOILBRENTEU", feeds)
    oil1, oil2 = st.columns(2)
    _market_metric(oil1, "WTI (USD/barel)", wti)
    _market_metric(oil2, "Brent (USD/barel)", brent)
    if wti and brent and wti.get("fresh") and brent.get("fresh"):
        if wti["pct"] > 0 and brent["pct"] > 0:
            st.caption("Harga WTI dan Brent sama-sama menguat terhadap basisnya; risiko tekanan inflasi energi dapat meningkat.")
        elif wti["pct"] < 0 and brent["pct"] < 0:
            st.caption("Harga WTI dan Brent sama-sama melemah terhadap basisnya; tekanan energi jangka pendek berkurang.")
        else:
            st.caption("WTI dan Brent belum searah; dorongan inflasi energi belum terkonfirmasi.")
    st.caption("Futures Yahoo dapat tertunda; fallback FRED adalah harga spot harian, "
               "bukan quote live. Lonjakan minyak berpotensi menambah inflasi tetapi "
               "dampak bersih terhadap emas bergantung pada real yield dan risiko geopolitik.")

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
    gold = feeds["market"].get("GC=F")
    silver = feeds["market"].get("SI=F")
    dx, au, ag = st.columns(3)
    _market_metric(dx, "DXY", dxy)
    _market_metric(au, "Gold futures GC", gold)
    _market_metric(ag, "Silver futures SI", silver)
    if any(not quote_freshness(item)["eligible"] for item in (dxy, gold, silver)):
        st.warning("Sebagian feed DXY/Gold/Silver DELAYED (>5 menit) atau hanya data harian. "
                   "Harga terakhir ditampilkan sebagai referensi, bukan konfirmasi pasar intraday.")
    if all(quote_freshness(item)["eligible"] for item in (dxy, gold, silver)):
        if dxy["pct"] > 0 and gold["pct"] < 0 and silver["pct"] < 0:
            st.caption("DXY menguat sementara futures emas dan perak melemah: tekanan lintas aset teramati pada basis masing-masing.")
        else:
            st.caption("Tekanan DXY terhadap emas dan perak belum terkonfirmasi serempak.")
    else:
        st.caption("Konfirmasi lintas aset tertunda karena ada quote DXY/logam yang belum segar.")
    st.caption("GC/SI adalah futures, bukan harga spot cTrader XAUUSD/XAGUSD. "
               "DXY dan yield menguat bersamaan sering menjadi headwind emas, "
               "namun hubungan ini tidak selalu berlaku.")

    st.info("KESIMPULAN OPERASIONAL: konteks makro saja, BUKAN sinyal entry. "
            "Konfirmasi di H1 (bias/zona), M15 (MSS/reversal), M5 (refinement). "
            "Jika feed hilang atau stale, status BELUM TERSEDIA — tidak diasumsikan bearish.")

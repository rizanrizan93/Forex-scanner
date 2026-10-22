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
from math import isfinite
from urllib.parse import quote, urlencode, urlparse
from urllib.request import Request, urlopen

import streamlit as st


FRED_SERIES = {
    "CPIAUCSL", "PCEPILFE", "PCEPI", "DFEDTARU", "DGS2",
    "DCOILWTICO", "DCOILBRENTEU",
}
YAHOO_SYMBOLS = {"DX-Y.NYB", "GC=F", "SI=F", "CL=F", "BZ=F"}
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


@st.cache_data(ttl=180, show_spinner=False)
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
    prior = _number(meta.get("chartPreviousClose") or meta.get("previousClose"))
    at = meta.get("regularMarketTime")
    observed = (datetime.fromtimestamp(float(at), UTC).isoformat()
                if at is not None else None)
    if current is None or current <= 0 or prior is None or prior <= 0 or not observed:
        raise ValueError("Market quote invalid")
    return {
        "value": current, "pct": (current / prior - 1) * 100,
        "observed": observed, "fresh": _recent(observed, 2),
        "source": "Yahoo Finance · kemungkinan tertunda",
    }


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


@st.cache_data(ttl=120, show_spinner=False)
def load_external_macro_inputs():
    """Parallel bounded requests; cache even failed sources to keep UI responsive."""
    fred_codes = sorted(FRED_SERIES)
    market_codes = sorted(YAHOO_SYMBOLS)
    tasks = [("fred", code) for code in fred_codes] + [
        ("market", code) for code in market_codes
    ] + [("us2y", "US2Y")]
    def read(kind, code):
        fn = fred_history if kind == "fred" else market_quote if kind == "market" else us2y_live
        return _safe(fn, code) if kind != "us2y" else _safe(fn)
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {key: pool.submit(read, *key) for key in tasks}
        outcomes = {key: future.result() for key, future in futures.items()}
    return {
        "fred": {code: outcomes[("fred", code)][0] for code in fred_codes},
        "market": {code: outcomes[("market", code)][0] for code in market_codes},
        "us2y": outcomes[("us2y", "US2Y")],
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
                "observed": date, "fresh": True, "source": "FRED (spot harian)"}
    return data if data else None


def _market_metric(slot, title, data, *, unit=""):
    if data and data.get("fresh"):
        slot.metric(title, _fmt(data["value"], unit),
                    delta=_delta(data["pct"], "%"))
        slot.caption(f"{data['source']} · Δ vs penutupan/observasi sebelumnya · {str(data['observed'])[:19]} UTC")
    elif data:
        slot.metric(title, "STALE")
        slot.caption(f"Quote terakhir {str(data.get('observed'))[:19]} UTC · tidak digunakan untuk bias")
    else:
        slot.metric(title, "BELUM TERSEDIA")
        slot.caption("Feed harga belum dapat diverifikasi")


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
    st.caption("Futures Yahoo dapat tertunda; fallback FRED adalah harga spot harian, "
               "bukan quote live. Lonjakan minyak berpotensi menambah inflasi tetapi "
               "dampak bersih terhadap emas bergantung pada real yield dan risiko geopolitik.")

    st.subheader("4 · Dolar AS dan logam mulia")
    dxy = feeds["market"].get("DX-Y.NYB")
    if not dxy or not dxy["fresh"]:
        d = macro_eval.get("dxy_intraday") or {}
        if (_number(d.get("current")) is not None
                and _number(d.get("net_pct")) is not None
                and _recent(d.get("current_at"), 0.02)
                and d.get("freshness") == "FRESH"):
            dxy = {"value": float(d["current"]), "pct": float(d["net_pct"]),
                   "observed": d["current_at"], "fresh": True,
                   "source": str(d.get("source") or "Macro worker")}
    gold = feeds["market"].get("GC=F")
    silver = feeds["market"].get("SI=F")
    dx, au, ag = st.columns(3)
    _market_metric(dx, "DXY", dxy)
    _market_metric(au, "Gold futures GC", gold)
    _market_metric(ag, "Silver futures SI", silver)
    st.caption("GC/SI adalah futures, bukan harga spot cTrader XAUUSD/XAGUSD. "
               "DXY dan yield menguat bersamaan sering menjadi headwind emas, "
               "namun hubungan ini tidak selalu berlaku.")

    st.info("KESIMPULAN OPERASIONAL: konteks makro saja, BUKAN sinyal entry. "
            "Konfirmasi di H1 (bias/zona), M15 (MSS/reversal), M5 (refinement). "
            "Jika feed hilang atau stale, status BELUM TERSEDIA — tidak diasumsikan bearish.")

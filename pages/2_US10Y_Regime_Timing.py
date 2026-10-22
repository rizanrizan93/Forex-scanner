from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if SRC.is_dir() and str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fx_scanner.pre_news_transport import fetch_pre_news_snapshot  # noqa: E402
from fx_scanner.dashboard_independent_feeds import macro_input  # noqa: E402
from fx_scanner.manual_reversal_dashboard import wib  # noqa: E402
from fx_scanner.xau_yield_regime_view_v372 import yield_regime_summary  # noqa: E402
from fx_scanner.xau_h15_daily_fallback import fetch_h15_daily_rows  # noqa: E402
from fx_scanner.xau_macro_risk_monitor import render_macro_risk_monitor  # noqa: E402

CNBC_US10Y_URL = "https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol"
CNBC_US10Y_HOST = "quote.cnbc.com"
LIVE_CASH_MAX_AGE_SECONDS = 120.0


def fmt(value: Any, suffix: str = "") -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    return f"{number:.3f}{suffix}"


def bias_label(value: Any) -> str:
    labels = {
        "BULLISH_XAU": "BULLISH XAU",
        "BEARISH_XAU": "BEARISH XAU",
        "NEUTRAL_MIXED": "NETRAL / MIXED",
        "UNAVAILABLE": "BELUM TERSEDIA",
    }
    return labels.get(str(value or "UNAVAILABLE"), str(value or "UNAVAILABLE"))


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


def _safe_error(exc: Exception) -> str:
    text = " ".join(str(exc).split())
    if len(text) > 180:
        text = text[:177] + "..."
    return f"{type(exc).__name__}: {text}" if text else type(exc).__name__


@st.cache_data(ttl=10, show_spinner=False)
def load_live_cash_us10y() -> dict[str, Any]:
    query = urlencode(
        {
            "symbols": "US10Y",
            "requestMethod": "itv",
            "noform": "1",
            "partnerId": "2",
            "fund": "1",
            "exthrs": "1",
            "output": "json",
            "events": "1",
        }
    )
    request = Request(
        CNBC_US10Y_URL + "?" + query,
        headers={
            "Accept": "application/json,text/plain,*/*",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "User-Agent": (
                "Mozilla/5.0 (Linux; Android 16) AppleWebKit/537.36 "
                "Chrome/140.0 Mobile Safari/537.36"
            ),
        },
    )
    with urlopen(request, timeout=8.0) as response:
        final = urlparse(str(response.geturl()))
        if final.scheme != "https" or final.hostname != CNBC_US10Y_HOST:
            raise ValueError("US10Y live quote redirected outside allowed host")
        raw = response.read(128 * 1024 + 1)
    if len(raw) > 128 * 1024:
        raise ValueError("US10Y live quote response too large")

    payload = json.loads(raw.decode("utf-8"))
    rows = list(dict(payload.get("FormattedQuoteResult") or {}).get("FormattedQuote") or [])
    if not rows:
        raise ValueError("US10Y live quote missing")
    quote = dict(rows[0] or {})
    if str(quote.get("symbol") or "").upper() != "US10Y":
        raise ValueError("US10Y live quote symbol mismatch")

    raw_last = str(quote.get("last") or "").replace("%", "").replace(",", "").strip()
    value = float(raw_last)
    if not 0.0 < value < 30.0:
        raise ValueError("US10Y live quote outside valid range")

    observed_at = _dt(quote.get("last_time"))
    if observed_at is None:
        raise ValueError("US10Y live quote timestamp missing")
    now = datetime.now(tz=UTC)
    age_seconds = max(0.0, (now - observed_at).total_seconds())
    return {
        "current": value,
        "current_at": observed_at.isoformat(),
        "age_seconds": age_seconds,
        "fresh": age_seconds <= LIVE_CASH_MAX_AGE_SECONDS,
        "realtime": quote.get("realTime"),
        "exchange": quote.get("exchange") or "Tradeweb",
        "provider": quote.get("provider") or "CNBC QUOTE CACHE",
        "source": "CNBC_US10Y_TRADEWEB_QUOTE",
    }


@st.cache_data(ttl=30, show_spinner=False)
def load_macro():
    return fetch_pre_news_snapshot()


@st.cache_data(ttl=900, show_spinner=False)
def load_h15_daily():
    return fetch_h15_daily_rows()


st.set_page_config(page_title="RIZAN US10Y", layout="wide")
st.title("RIZAN — Makro XAU: Treasury & Cross-Asset")
st.caption(
    "Daily FRED (fallback Federal Reserve H.15) untuk regime makro. Intraday US10Y untuk timing/pressure. "
    "Keduanya tidak memberi izin order sendiri; keputusan tetap harus dikonfirmasi struktur XAU."
)

if st.button("Perbarui tampilan", key="yield_refresh"):
    load_macro.clear()
    load_live_cash_us10y.clear()
    load_h15_daily.clear()

# The independently fetched CNBC cash quote must remain visible even when the
# GitHub-published macro engine heartbeat is stale or temporarily unavailable.
macro_error = None
try:
    data = macro_input(load_macro())
    macro_eval = data["evaluation"]
    st.caption("Feed makro terakhir: " + wib(data["observed_at"]) + " · independen dari heartbeat zona XAU")
except Exception as exc:
    macro_error = _safe_error(exc)
    macro_eval = {}

proxy_active = (macro_eval.get("intraday_yield_context") or {}).get("timing_basis") == "TREASURY_FUTURES_PROXY"
last_cash = macro_eval.get("last_cash_yield") or {}


@st.fragment(run_every="20s")
def render_live_cash_quote() -> None:
    live_cash = None
    live_error = None
    try:
        live_cash = load_live_cash_us10y()
    except Exception as exc:
        live_error = _safe_error(exc)

    if live_cash and live_cash.get("fresh"):
        health = "CNBC OK"
        fallback = "TIDAK"
        health_detail = (
            f"{live_cash.get('provider') or 'CNBC'} / {live_cash.get('exchange') or 'Tradeweb'}"
            + (" · realtime=true" if str(live_cash.get("realtime")).lower() == "true" else "")
        )
    elif live_cash:
        health = "CNBC STALE"
        fallback = "YA"
        health_detail = (
            f"quote berusia {float(live_cash.get('age_seconds') or 0.0) / 60:.1f} menit "
            f"(batas live {LIVE_CASH_MAX_AGE_SECONDS:.0f} detik)"
        )
    else:
        health = "CNBC ERROR"
        fallback = "YA"
        health_detail = live_error or "sumber live tidak mengembalikan quote"

    h1, h2, h3 = st.columns(3)
    h1.metric("Source Health", health)
    h2.metric("Fallback aktif", fallback)
    if live_cash and live_cash.get("current_at"):
        h3.metric("Usia data", f"{float(live_cash.get('age_seconds') or 0.0):.0f} dtk")
    else:
        h3.metric("Usia data", "—")
    st.caption("Health detail: " + health_detail)

    if live_cash and live_cash.get("fresh"):
        st.success(
            "Cash US10Y LIVE: "
            + fmt(live_cash.get("current"), "%")
            + " · "
            + wib(live_cash.get("current_at"))
            + f" · usia {float(live_cash.get('age_seconds') or 0.0):.0f} detik"
            + ". Auto-refresh 20 detik."
        )
        st.caption(
            "Sumber live display: CNBC / Tradeweb. Feed ini dipisahkan dari Daily FRED dan tidak memberi otoritas order."
        )
        return

    if live_cash:
        st.warning(
            "Cash US10Y live source belum cukup segar: "
            + fmt(live_cash.get("current"), "%")
            + " · "
            + wib(live_cash.get("current_at"))
            + f" · usia {float(live_cash.get('age_seconds') or 0.0) / 60:.1f} menit."
        )
    elif last_cash:
        st.warning(
            "Sumber live cash US10Y sedang tidak tersedia. Last valid engine: "
            + fmt(last_cash.get("current"), "%")
            + " · "
            + wib(last_cash.get("current_at"))
            + "."
        )
    else:
        st.warning("Sumber live cash US10Y sedang tidak tersedia dan belum ada last-valid quote.")

    if live_error:
        st.caption("Error sumber terakhir: " + live_error)

    if proxy_active:
        st.caption("Timing engine tetap memakai Treasury futures ZN yang lebih baru sampai cash feed valid kembali.")
    else:
        st.caption("Timing engine tetap fail-closed; quote stale tidak dianggap sebagai data intraday live.")


render_live_cash_quote()

if macro_error is not None:
    st.warning(
        "Feed engine Daily FRED / intraday belum dapat diverifikasi. "
        "Panel CNBC dan fallback H.15 dapat berjalan secara independen; "
        "bias intraday tetap tidak tersedia bila snapshot engine tidak sehat."
    )
    st.caption("Diagnosis feed engine: " + macro_error)
    st.caption("Tekan 'Perbarui tampilan' untuk memuat ulang snapshot; quote CNBC menyegarkan sendiri setiap 20 detik.")
    # The daily reference can still recover directly from H.15 when the
    # separately published macro-worker snapshot is unavailable.

summary = yield_regime_summary(macro_eval)
daily = dict(summary.get("daily") or {})
intraday = dict(summary.get("intraday") or {})
h15_display_active = False
h15_display_error = None
if daily.get("gold_bias") == "UNAVAILABLE":
    try:
        official = dict(load_h15_daily().get("US10Y") or {})
        if official.get("freshness") == "FRESH" and official.get("delta") is not None:
            display_only = dict(macro_eval)
            display_only["components"] = {
                **dict(macro_eval.get("components") or {}), "US10Y": official,
            }
            summary = yield_regime_summary(display_only)
            daily = dict(summary.get("daily") or {})
            intraday = dict(summary.get("intraday") or {})
            h15_display_active = True
    except Exception as exc:
        h15_display_error = _safe_error(exc)


c1, c2 = st.columns(2)
with c1:
    st.markdown("### US10Y Daily Regime")
    st.metric("Bias terhadap XAU", bias_label(daily.get("gold_bias")))
    if h15_display_active:
        st.info("Fallback Federal Reserve H.15 aktif karena FRED/worker belum menyediakan DGS10. Hanya konteks tampilan, tanpa otoritas order.")
    elif daily.get("gold_bias") == "UNAVAILABLE":
        st.warning("DGS10 harian belum valid; fallback H.15 juga belum menyediakan observasi segar.")
    st.metric(
        "Fed H.15 DGS10 (fallback)" if h15_display_active else "FRED DGS10",
        fmt(daily.get("current"), "%"),
        delta=(
            None
            if daily.get("delta_bps") is None
            else f"{float(daily.get('delta_bps')):+.1f} bps vs prior day"
        ),
    )
    st.caption("Tanggal observasi daily: " + str(daily.get("observed_at") or "—")[:10])
    st.caption("Sumber harian: " + str(daily.get("source") or "UNAVAILABLE"))
    st.caption(
        "Fungsi: menentukan backdrop 1–beberapa hari. Yield harian turun = tailwind XAU; "
        "yield harian naik = headwind XAU. Ini bukan trigger entry."
    )

with c2:
    st.markdown("### US10Y Intraday Pressure")
    st.metric("Bias terhadap XAU", bias_label(intraday.get("gold_bias")))
    if proxy_active:
        st.metric(
            "Treasury futures ZN · harga proksi",
            fmt(intraday.get("futures_price")),
            delta=(
                None
                if intraday.get("futures_change_points") is None
                else f"{intraday['futures_change_points']:+.5f} poin vs awal jendela"
            ),
        )
        st.caption("Waktu kuotasi ZN: " + wib(intraday.get("futures_at")))
        if intraday.get("age_seconds") is not None:
            st.caption(
                f"Usia kuotasi proksi: {intraday['age_seconds']/60:.1f} menit · pembaruan feed sekitar 4 menit."
            )
        st.caption(
            "Proksi arah yield dari harga futures, bukan yield cash dalam persen. Harga ZN naik → tekanan yield turun; "
            "ZN turun → tekanan yield naik. Sumber Yahoo dapat tertunda."
        )
    else:
        st.metric(
            "Yield intraday engine",
            fmt(intraday.get("current"), "%"),
            delta=(
                None
                if intraday.get("rebound_from_low_bps") is None
                else f"{float(intraday['rebound_from_low_bps']):+.1f} bps dari low pasca-event"
            ),
        )
        st.caption("Waktu kuotasi engine: " + wib(intraday.get("current_at")))
    st.caption(
        "Fungsi: membaca pressure menit/jam terbaru. Yield intraday naik/re-accelerate = "
        "headwind XAU; yield intraday turun = tailwind XAU. Ini dipakai untuk timing."
    )

alignment = str(summary.get("alignment") or "MIXED")
if alignment == "ALIGNED":
    st.success("DAILY + INTRADAY SEARAH • " + str(summary.get("decision_note") or ""))
elif alignment == "DIVERGENT":
    st.warning("DAILY vs INTRADAY DIVERGEN • " + str(summary.get("decision_note") or ""))
elif alignment == "INTRADAY_UNAVAILABLE":
    st.info("INTRADAY BELUM TERSEDIA • " + str(summary.get("decision_note") or ""))
else:
    st.info("YIELD MIXED • " + str(summary.get("decision_note") or ""))

render_macro_risk_monitor(macro_eval, load_h15_daily)

st.markdown("### Cara baca cepat")
st.write(
    "1. Daily FRED = arah regime. 2. Intraday yield = timing pressure. "
    "3. Bila searah, cek apakah struktur H4/H1 dan S/R XAU mendukung. "
    "4. Bila berlawanan, jangan entry dari makro saja; tunggu reclaim/MSS/displacement."
)

with st.expander("Detail sumber"):
    st.write(
        {
            "daily_state": daily.get("state"),
            "daily_freshness": daily.get("freshness"),
            "daily_source": daily.get("source"),
            "h15_display_fallback_active": h15_display_active,
            "h15_display_error": h15_display_error,
            "intraday_state": intraday.get("state"),
            "intraday_source": intraday.get("source"),
            "live_cash_display_source": "CNBC_US10Y_TRADEWEB_QUOTE",
            "live_cash_refresh_seconds": 20,
            "live_cash_cache_seconds": 10,
            "live_cash_max_age_seconds": LIVE_CASH_MAX_AGE_SECONDS,
            "fallback_policy": "LAST_VALID_CASH_THEN_ZN_DIRECTION_PROXY_FAIL_CLOSED",
            "alignment": alignment,
        }
    )

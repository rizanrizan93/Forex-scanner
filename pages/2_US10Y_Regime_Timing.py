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
from fx_scanner.xau_treasury_schedule import (  # noqa: E402
    treasury_session_status, fred_daily_release_key, next_h15_release, WIB,
)

# Long-running Streamlit sessions can retain imported modules after a Git
# deployment updates their .py files. Refresh ONLY the read-only XAU macro
# modules when file revisions change; no cBot, broker, or bridge modules loaded.
from importlib import invalidate_caches, reload  # noqa: E402
import fx_scanner.xau_cnbc_macro_quotes as _macro_quotes  # noqa: E402
import fx_scanner.xau_market_quote_health as _macro_health  # noqa: E402
import fx_scanner.xau_macro_daily_regime as _macro_daily  # noqa: E402
import fx_scanner.xau_oil_macro_context as _macro_oil  # noqa: E402
import fx_scanner.xau_geopolitical_safehaven as _macro_geo  # noqa: E402
import fx_scanner.xau_macro_gold_consensus as _macro_core  # noqa: E402
# Reload source modules BEFORE the display module: the display module imports
# their callable objects via "from ... import". Omitting them kept old M15
# forecast functions alive after a GitHub deployment on long-lived sessions.
import fx_scanner.xau_m15_macro_forecast as _m15_engine  # noqa: E402
import fx_scanner.xau_m15_market_feed as _m15_feed  # noqa: E402
import fx_scanner.xau_macro_risk_monitor as _macro_ui  # noqa: E402


def _refresh_macro_code_if_changed() -> None:
    modules = (
        _macro_quotes, _macro_health, _macro_daily, _macro_oil, _macro_geo,
        _macro_core, _m15_engine, _m15_feed, _macro_ui,
    )
    signature = tuple(
        (str(module.__file__), Path(module.__file__).stat().st_mtime_ns,
         Path(module.__file__).stat().st_size)
        for module in modules
    )
    key = "_rizan_xau_macro_code_signature"
    if st.session_state.get(key) != signature:
        invalidate_caches()
        for module in modules:
            reload(module)
        st.session_state[key] = signature


_refresh_macro_code_if_changed()
from fx_scanner.xau_macro_risk_monitor import (  # noqa: E402
    render_macro_risk_monitor, render_gold_macro_conclusion,
    fred_history, market_quote, us2y_live, load_external_macro_inputs,
    cnbc_macro_quotes_cached, goldapi_spot_cached,
)

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


@st.cache_data(ttl=7 * 86400, show_spinner=False)
def _load_h15_by_release(release_key):
    return fetch_h15_daily_rows()


def load_h15_daily():
    # Federal Reserve H.15 is official daily reference, not intraday polling.
    return _load_h15_by_release(fred_daily_release_key())


st.set_page_config(page_title="RIZAN US10Y", layout="wide")
st.title("RIZAN — Makro XAU: Treasury & Cross-Asset")
st.caption(
    "Daily FRED (fallback Federal Reserve H.15) untuk regime makro. Intraday US10Y untuk timing/pressure. "
    "Keduanya tidak memberi izin order sendiri; keputusan tetap harus dikonfirmasi struktur XAU."
)
st.caption("Versi dashboard: RIZAN Macro V3.3 TREASURY HOLIDAY + OFFICIAL DAILY RELEASE · read-only")
treasury_calendar = treasury_session_status()
calendar_state = treasury_calendar["status"]
if calendar_state == "MARKET_HOLIDAY":
    st.info(
        "MARKET HOLIDAY • " + treasury_calendar["label"] + " ("
        + treasury_calendar["ny_date"] + " waktu New York). "
        "Pasar Treasury AS dijadwalkan tutup. Yield cash lama bukan feed LIVE; "
        "Daily FRED tetap menjadi backdrop historis."
    )
elif calendar_state == "PRE_HOLIDAY":
    st.info(
        "PRE-HOLIDAY • sesi AS berikutnya libur (" + str(treasury_calendar["holiday_tomorrow"])
        + "). Sekarang di New York masih " + treasury_calendar["ny_time"]
        + "; quote intraday tetap harus lolos freshness."
    )
elif calendar_state in {"WEEKEND_CLOSED", "EARLY_CLOSE"}:
    st.info(
        calendar_state.replace("_", " ") + " • " + treasury_calendar["ny_time"]
        + ". Yield cash sebelumnya hanya referensi, bukan LIVE."
    )
st.caption(
    "FRED Treasury daily: fetch sekali per siklus rilis H.15 (16:15 ET, buffer hingga 16:45 ET), "
    "bukan setiap refresh 15–20 detik. Siklus data " + fred_daily_release_key()
    + " · rilis H.15 berikutnya "
    + next_h15_release().astimezone(WIB).strftime("%d/%m %H:%M WIB")
    + ". FRED dapat terlambat dari H.15."
)

if st.button("Perbarui tampilan", key="yield_refresh"):
    load_macro.clear()
    load_live_cash_us10y.clear()
    _load_h15_by_release.clear()
    fred_history.clear()
    market_quote.clear()
    cnbc_macro_quotes_cached.clear()
    goldapi_spot_cached.clear()
    us2y_live.clear()
    load_external_macro_inputs.clear()

# The independently fetched CNBC cash quote must remain visible even when the
# GitHub-published macro engine heartbeat is stale or temporarily unavailable.
macro_error = None
event_risk = {}
try:
    raw_snapshot = load_macro()
    data = macro_input(raw_snapshot)
    macro_eval = data["evaluation"]
    events = [
        hb for hb in (raw_snapshot.get("heartbeats") or [])
        if hb.get("worker_name") == "ctrader_demo_xau_event_risk_v192"
        and hb.get("healthy") is True
        and _dt(hb.get("observed_at")) is not None
        and 0 <= (datetime.now(UTC) - _dt(hb.get("observed_at"))).total_seconds() <= 900
    ]
    events.sort(key=lambda hb: str(hb.get("observed_at") or ""), reverse=True)
    if events:
        event_risk = dict((events[0].get("details") or {}).get("risk") or {})
    st.caption("Feed makro terakhir: " + wib(data["observed_at"]) + " · independen dari heartbeat zona XAU")
except Exception as exc:
    macro_error = _safe_error(exc)
    macro_eval = {}

proxy_active = (macro_eval.get("intraday_yield_context") or {}).get("timing_basis") == "TREASURY_FUTURES_PROXY"
last_cash = macro_eval.get("last_cash_yield") or {}


render_gold_macro_conclusion(macro_eval, load_h15_daily, event_risk=event_risk)

@st.fragment(run_every="20s")
def render_live_cash_quote() -> None:
    live_cash = None
    live_error = None
    closed_market = treasury_session_status()["status"] in {
        "MARKET_HOLIDAY", "WEEKEND_CLOSED", "EARLY_CLOSE",
    }
    # Avoid polling a cash quote during a known scheduled closure. This is a
    # UI-only calendar guard; broker / cBot execution is completely separate.
    if not closed_market:
        try:
            live_cash = load_live_cash_us10y()
        except Exception as exc:
            live_error = _safe_error(exc)
    if closed_market:
        health = treasury_session_status()["status"].replace("_", " ")
        fallback = "N/A"
        health_detail = (
            "Treasury cash tidak memiliki sesi aktif sesuai kalender pasar AS. "
            "Quote tersimpan tidak boleh dianggap intraday LIVE."
        )
    elif live_cash and live_cash.get("fresh"):
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

    if closed_market:
        st.info(
            "Treasury cash market sedang libur/tutup. Data CNBC terakhir"
            + (" " + fmt(live_cash.get("current"), "%")
               + " · " + wib(live_cash.get("current_at")) if live_cash else " tidak tersedia")
            + " hanya referensi historis, tidak digunakan untuk tekanan intraday."
        )
        if live_error:
            st.caption("Diagnosis sumber (non-trading): " + live_error)
        return

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
# Prefer a newer official H.15 date if the published macro-worker/FRED
# snapshot is a session behind. Equal-date worker data retains precedence.
try:
    official = dict(load_h15_daily().get("US10Y") or {})
    official_day = str(official.get("observed_at") or "")[:10]
    worker_day = str(daily.get("observed_at") or "")[:10]
    if (
        official.get("freshness") == "FRESH"
        and official.get("delta") is not None
        and (daily.get("gold_bias") == "UNAVAILABLE" or official_day > worker_day)
    ):
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


# Do not promote quote ages or the worker's previous-session yield to
# intraday pressure during a scheduled bond-market holiday or weekend.
if calendar_state in {"MARKET_HOLIDAY", "WEEKEND_CLOSED", "EARLY_CLOSE"}:
    intraday = {**intraday, "gold_bias": "UNAVAILABLE", "state": calendar_state,
                "current": None, "rebound_from_low_bps": None}
    summary = {
        **summary, "alignment": "INTRADAY_UNAVAILABLE",
        "decision_note": "Sesi Treasury AS ditutup sesuai kalender; bias harian tetap kontekstual, bukan trigger entry.",
    }
    proxy_active = False

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
    st.caption("Fetch official daily per rilis; pada holiday/weekend mempertahankan observasi terakhir, tanpa mencapnya LIVE.")
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
            "treasury_calendar": treasury_calendar,
            "fred_daily_release_key": fred_daily_release_key(),
            "fred_network_refresh_policy": "ONCE_PER_H15_RELEASE_CYCLE_1645_ET",
            "alignment": alignment,
        }
    )

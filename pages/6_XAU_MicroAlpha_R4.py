"""RIZAN XAU MicroAlpha R4: read-only historical liquidity and macro dashboard."""
from __future__ import annotations

import io
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import Request, urlopen

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from fx_scanner.pre_news_transport import fetch_pre_news_snapshot
from fx_scanner.xau_microalpha_r3 import macro_direction
from fx_scanner.xau_microalpha_r4 import (
    CONTRACT, R4Settings, build_liquidity_signals, backtest,
)

PUBLIC_SAMPLE_URL = (
    "https://raw.githubusercontent.com/Sai310421/xauusd-data/"
    "d27c59d23c023e0d02f5dc6fffd57850bac9d197/"
    "csv/XAUUSD/XAUUSD_M5_2026Q1Q2.csv"
)


@st.cache_data(ttl=21600, show_spinner=False)
def public_sample():
    req = Request(PUBLIC_SAMPLE_URL, headers={"User-Agent": "RIZAN-R4-Readonly"})
    with urlopen(req, timeout=15) as response:
        data = response.read(2_000_001)
    if len(data) > 2_000_000:
        raise ValueError("PUBLIC_SAMPLE_TOO_LARGE")
    return pd.read_csv(io.BytesIO(data))


@st.cache_data(ttl=60, show_spinner=False)
def macro_sample():
    return fetch_pre_news_snapshot()


st.set_page_config(page_title="MicroAlpha R4 XAU Research", page_icon="🔬", layout="wide")
st.title("RIZAN XAU — MicroAlpha R4")
st.caption("Liquidity sweep → M5 structure confirmation, trend M15/H1, macro V400 context.")
st.error(
    "RESEARCH ONLY / NO-GO LIVE: pengujian 2019–Jan 2026 belum menunjukkan expectancy "
    "positif. Tidak terhubung ke broker, bridge maupun cBot."
)

st.subheader("Konteks makro saat ini (terpisah dari replay)")
try:
    macro = macro_direction(macro_sample(), now=datetime.now(UTC))
except Exception as exc:
    macro = {"direction": "WAIT", "state": "WAIT_MACRO_DATA", "reason": type(exc).__name__}
m1, m2, m3 = st.columns(3)
m1.metric("Macro direction", macro.get("direction", "WAIT"))
m2.metric("Evidence state", macro.get("state", "WAIT"))
m3.metric("Reason", macro.get("reason", "NOT_VALIDATED"))
st.caption(
    "Hanya menampilkan arah jika V400 quality gate dan quote DXY/yield yang independen "
    "serta segar lolos. Makro historis memakai proxy USD broad + yield harian lagged, "
    "BUKAN ICE DXY atau yield intraday yang tervalidasi point-in-time."
)

st.subheader("Data historis dan parameter simulasi")
upload = st.file_uploader("Unggah CSV M5 UTC (candle closed)", type=["csv"])
try:
    raw = pd.read_csv(upload) if upload is not None else public_sample()
except Exception as exc:
    st.error(f"Data belum tersedia: {type(exc).__name__}. Upload CSV M5 diperlukan.")
    st.stop()

c1, c2, c3, c4 = st.columns(4)
with c1:
    pool = st.selectbox("Liquidity pool", ["ASIA_OPEN_06_08", "ROLL12", "ROLL24"])
with c2:
    trend = st.selectbox("Filter arah tren", ["NONE", "M15", "H1", "BOTH"])
with c3:
    risk = st.select_slider("Max risiko per trade (%)", [1, 2, 5, 10], value=5)
with c4:
    rr = st.select_slider("Target R", [1.5, 2.0, 2.5, 3.0], value=2.0)

c5, c6, c7, c8 = st.columns(4)
with c5:
    min_lot = st.number_input("Minimum lot (asumsi)", min_value=.001, max_value=1.0,
                              value=.01, step=.001, format="%.3f")
with c6:
    lot_step = st.number_input("Step lot (asumsi)", min_value=.001, max_value=1.0,
                               value=.01, step=.001, format="%.3f")
with c7:
    cost = st.number_input("Friksi round-trip USD/oz", min_value=0.0, max_value=20.0,
                           value=.8, step=.1)
with c8:
    max_margin = st.select_slider("Batas margin (% equity)", [25, 40, 50], value=50)

cfg = R4Settings(
    risk_fraction=float(risk) / 100, min_lot=float(min_lot),
    lot_step=float(lot_step), reward_r=float(rr),
    roundtrip_cost_usd_per_oz=float(cost),
    max_margin_fraction=float(max_margin) / 100,
)
try:
    frame = build_liquidity_signals(raw, pool=pool, trend=trend)
    now = datetime.now(UTC)
    frame = frame.loc[frame["closed_at"].le(pd.Timestamp(now))].reset_index(drop=True)
    if len(frame) < 2600:
        raise ValueError("NOT_ENOUGH_CLOSED_M5_HISTORY")
    report, ledger = backtest(frame, cfg, session="ASIA")
except Exception as exc:
    st.error(f"Analisis tidak tersedia: {type(exc).__name__}: {exc}")
    st.stop()

last = frame.iloc[-1]["closed_at"].to_pydatetime()
age = (now - last).total_seconds()
source = "UPLOADED_HISTORICAL" if upload is not None else "PUBLIC_HISTORICAL_SAMPLE"
st.caption(
    f"{source} • {len(frame):,} M5 • "
    f"{frame.iloc[0]['datetime']:%Y-%m-%d} sampai {last:%Y-%m-%d %H:%M UTC}"
)
if not 0 <= age <= 600:
    st.error("STATUS STALE / HISTORICAL. Tidak ada sinyal trading LIVE yang diberikan.")

st.subheader("Sinyal terakhir dalam sejarah dataset — bukan kondisi LIVE")
history = frame.loc[frame["r4_signal"].ne(0),
                    ["closed_at", "close", "r4_signal", "r4_structural_stop",
                     "r4_confirm_lag_bars"]].tail(12).copy()
if history.empty:
    st.info("Tidak ada MSS setelah sweep yang sesuai definisi.")
else:
    history["direction"] = history["r4_signal"].map({1: "BUY", -1: "SELL"})
    st.dataframe(
        history[["closed_at", "direction", "close", "r4_structural_stop",
                 "r4_confirm_lag_bars"]].iloc[::-1],
        use_container_width=True, hide_index=True,
    )

st.subheader("R4 technical-only replay — USD100 compounding / 1:200")
a, b, c, d = st.columns(4)
a.metric("Ending equity", f"USD {report['ending_usd']:,.2f}")
b.metric("Net return", f"{report['net_pct']:+.2f}%")
c.metric("Profit factor", report["profit_factor"] if report["profit_factor"] is not None else "—")
d.metric("Trades", report["count"])
e, f, g, h = st.columns(4)
e.metric("Closed DD", f"{report['closed_dd_pct']:.2f}%")
f.metric("OHLC intrabar DD*", f"{report['ohlc_floating_dd_estimate_pct']:.2f}%")
g.metric("Risk blocked", report["blocked_risk"])
h.metric("Margin blocked", report["blocked_margin"])
st.caption(
    "*Floating DD hanya perkiraan berbasis OHLC M5, bukan tick bid/ask. "
    "Spread/friksi konstan, swap, komisi FP dan margin aktual belum divalidasi. "
    "Snapshot makro sekarang tidak digunakan dalam replay historis."
)
if not ledger.empty:
    curve = ledger.copy()
    curve["entry_utc"] = pd.to_datetime(curve["entry_utc"], utc=True)
    st.line_chart(curve.set_index("entry_utc")["equity_usd"])
    st.dataframe(ledger.tail(100).iloc[::-1], hide_index=True, use_container_width=True)
    st.download_button("Unduh trade log CSV", data=ledger.to_csv(index=False),
                       file_name="rizan_microalpha_r4_research.csv", mime="text/csv")
st.caption(CONTRACT + " • execution_authority=false")

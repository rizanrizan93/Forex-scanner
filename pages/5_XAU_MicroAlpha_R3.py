"""XAU MicroAlpha R3 research dashboard, wholly separate from cBot LIVE."""
from __future__ import annotations

import io
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.request import Request, urlopen

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from fx_scanner.xau_microalpha_r3 import (  # noqa: E402
    MicroSettings, build_features, macro_direction,
    latest_research_state, replay,
)
from fx_scanner.pre_news_transport import fetch_pre_news_snapshot  # noqa: E402

PUBLIC_SOURCE = (
    "https://raw.githubusercontent.com/Sai310421/xauusd-data/"
    "d27c59d23c023e0d02f5dc6fffd57850bac9d197/"
    "csv/XAUUSD/XAUUSD_M5_2026Q1Q2.csv"
)


@st.cache_data(ttl=21600, show_spinner=False)
def public_sample() -> pd.DataFrame:
    request = Request(PUBLIC_SOURCE, headers={"User-Agent": "RIZAN-MicroAlphaR3-Readonly"})
    with urlopen(request, timeout=15) as response:
        body = response.read(2_000_001)
    if len(body) > 2_000_000:
        raise ValueError("PUBLIC_SAMPLE_TOO_LARGE")
    return pd.read_csv(io.BytesIO(body))


@st.cache_data(ttl=60, show_spinner=False)
def latest_macro() -> dict:
    return fetch_pre_news_snapshot()


st.set_page_config(page_title="MicroAlpha R3 — XAU Research", page_icon="🔬", layout="wide")
st.title("RIZAN XAU — MicroAlpha R3")
st.caption(
    "M5 EMA20 reclaim • trend M15 EMA20/50 • H1 EMA50 • macro V400 quality gate. "
    "Research/shadow only, never an order command."
)
st.warning(
    "LIVE cBot tetap terpisah. Perhitungan profit di bawah adalah replay teknikal "
    "saja; histori yield/DXY point-in-time BELUM diuji."
)

st.subheader("Arah makro ForexScanner saat ini (terpisah dari backtest historis)")
now = datetime.now(UTC)
try:
    macro = macro_direction(latest_macro(), now=now)
except Exception as exc:
    macro = {"state": "WAIT_MACRO_DATA", "direction": "WAIT", "reason": type(exc).__name__}
a, b, c = st.columns(3)
a.metric("Macro gate", macro.get("state", "WAIT"))
b.metric("Bias XAU", macro.get("direction", "WAIT"))
c.metric("Konfirmasi", macro.get("reason", "UNAVAILABLE"))
st.caption(
    "Macro hanya dinyatakan selaras jika V400 ALIGNED_CONTEXT_ONLY, publikasi "
    "terbaru valid, DXY dan US10Y/Fed futures segar, serta sumbernya berbeda. "
    "Real yield/US2Y berasal dari konteks kualitas harian; bukan kuotasi intraday "
    "yang boleh diklaim real-time. WAIT berarti belum ada konfirmasi."
)

st.subheader("Dataset M5 UTC — replay USD100 compounding")
upload = st.file_uploader("Unggah CSV XAUUSD M5 UTC (hanya candle CLOSED)", type=["csv"])
try:
    raw = pd.read_csv(upload) if upload is not None else public_sample()
except Exception as exc:
    st.error(f"Sampel tidak dapat dibaca: {type(exc).__name__}. Gunakan upload CSV.")
    st.stop()
source = "UPLOAD_CSV" if upload is not None else "PUBLIC_HISTORICAL_MID_OHLC"

col1, col2, col3, col4 = st.columns(4)
with col1:
    initial = st.number_input("Modal awal USD", min_value=1.0, max_value=10000.0, value=100.0)
with col2:
    risk = st.select_slider("Batas risiko per posisi", options=[1, 2, 5, 10], value=5)
with col3:
    stop_atr = st.select_slider("SL × ATR M5", options=[0.25, 0.5, 1.0, 1.5], value=1.0)
with col4:
    session = st.selectbox("Jam entry WIB", options=["ASIA", "ALL", "US"])
col5, col6, col7, col8 = st.columns(4)
with col5:
    minimum_lot = st.number_input("Min lot cTrader (belum diverifikasi)", min_value=0.001, max_value=1.0,
                                  value=0.01, step=0.001, format="%.3f")
with col6:
    lot_step = st.number_input("Lot step (belum diverifikasi)", min_value=0.001, max_value=1.0,
                               value=0.01, step=0.001, format="%.3f")
with col7:
    lot_size = st.number_input("Oz per 1 lot (asumsi)", min_value=1.0, max_value=1000.0, value=100.0)
with col8:
    friction = st.number_input("Friksi USD/oz roundtrip", min_value=0.0, max_value=20.0,
                               value=0.80, step=0.10)
cfg = MicroSettings(
    initial_equity=float(initial), leverage=200.0, risk_fraction=risk / 100,
    stop_atr=float(stop_atr), minimum_lot=float(minimum_lot),
    lot_step=float(lot_step), lot_size_oz=float(lot_size),
    friction_roundtrip_usd_per_oz=float(friction),
)

try:
    frame = build_features(raw)
    # Reject an uploaded still-forming last candle. The caller is responsible for only
    # sending historical/closed candles; this explicitly truncates a future/open one.
    closed = frame["closed_at"].le(pd.Timestamp(now))
    if not closed.all():
        frame = frame.loc[closed].reset_index(drop=True)
        st.info("Candle M5 yang belum CLOSE dikeluarkan dari perhitungan.")
    if len(frame) < 2600:
        raise ValueError("CLOSED_M5_INSUFFICIENT")
    report, ledger = replay(frame, cfg, session=session)
    latest = latest_research_state(frame, cfg, macro=macro, now=now)
except Exception as exc:
    st.error(f"Data atau simulasi tidak valid: {type(exc).__name__}: {exc}")
    st.stop()

last_time = frame.iloc[-1]["closed_at"]
age_minutes = (now - last_time.to_pydatetime()).total_seconds() / 60
st.caption(
    f'{source} • {len(frame):,} candle M5 • '
    f'{frame.iloc[0]["datetime"]:%Y-%m-%d} sampai {last_time:%Y-%m-%d %H:%M UTC} • '
    f'data age {age_minutes:.1f} menit'
)
if age_minutes > 10:
    st.error("HISTORICAL / STALE: tidak boleh dianggap sinyal LIVE.")
st.subheader("Sinyal terakhir DALAM DATASET")
i1, i2, i3, i4 = st.columns(4)
i1.metric("Teknikal", latest["signal"])
i2.metric("Keseluruhan", latest["state"])
i3.metric("Min-lot risk USD", f'{latest["risk_min_usd"]:.2f}')
i4.metric("Min-lot margin USD", f'{latest["margin_min_usd"]:.2f}')
st.caption(
    f'Close {latest["source_price"]:.2f} • M5 EMA20 {latest["ema20"]:.2f} • '
    f'M15 EMA20/50 {latest["m15_ema20"]:.2f}/{latest["m15_ema50"]:.2f} • '
    f'H1 EMA50 {latest["h1_ema50"]:.2f} • ATR M5 {latest["atr14"]:.2f}'
)

st.subheader("Simulasi teknikal tanpa makro historis")
p1, p2, p3, p4 = st.columns(4)
p1.metric("Ending equity", f'USD {report["ending_equity"]:.2f}')
p2.metric("Return", f'{report["return_pct"]:+.2f}%')
p3.metric("Profit factor", report["profit_factor"] if report["profit_factor"] is not None else "—")
p4.metric("Trades", report["trades"])
p5, p6, p7, p8 = st.columns(4)
p5.metric("Closed DD", f'{report["closed_dd_pct"]:.2f}%')
p6.metric("Floating DD (OHLC)*", f'{report["ohlc_intrabar_dd_estimate_pct"]:.2f}%')
p7.metric("Blocked risk", report["blocked_risk"])
p8.metric("Blocked margin", report["blocked_margin"])
st.caption(
    "*Floating DD pendekatan candle, bukan tick equity. Spread/friksi tetap, "
    "tanpa bid/ask, komisi broker aktual, swap, stop-out broker maupun partial fills. "
    "Tidak ada optimasi parameter atau validasi 2019–2026 pada halaman ini."
)
if not ledger.empty:
    st.line_chart(ledger.set_index("entry_at")["equity_usd"])
    st.dataframe(ledger.tail(100).iloc[::-1], use_container_width=True, hide_index=True)
    st.download_button("Unduh trade ledger CSV", data=ledger.to_csv(index=False),
                       file_name="rizan_microalpha_r3_research.csv", mime="text/csv")
else:
    st.info("Tidak ada transaksi yang lolos filter dan minimum lot pada simulasi ini.")
st.caption("MACRO HISTORICAL BACKTEST: NOT RUN • EXECUTION AUTHORITY: FALSE")

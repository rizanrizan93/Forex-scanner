"""RIZAN R5 read-only research dashboard; historical data never equals LIVE orders."""
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

from fx_scanner.xau_microalpha_r4 import R4Settings, backtest
from fx_scanner.xau_microalpha_r3 import macro_direction
from fx_scanner.xau_microalpha_r5 import (
    CONTRACT, CANDIDATES, features, build_signals, live_shadow_state,
)
from fx_scanner.pre_news_transport import fetch_pre_news_snapshot


SOURCE = (
    "https://raw.githubusercontent.com/Sai310421/xauusd-data/"
    "d27c59d23c023e0d02f5dc6fffd57850bac9d197/"
    "csv/XAUUSD/XAUUSD_M5_2026Q1Q2.csv"
)


@st.cache_data(ttl=86400, show_spinner=False)
def sample() -> pd.DataFrame:
    request = Request(SOURCE, headers={"User-Agent": "Rizan-XAU-R5-Readonly"})
    with urlopen(request, timeout=20) as response:
        body = response.read(2_000_001)
    if len(body) > 2_000_000:
        raise ValueError("HISTORICAL_SAMPLE_TOO_LARGE")
    return pd.read_csv(io.BytesIO(body))


@st.cache_data(ttl=60, show_spinner=False)
def macro_snapshot() -> dict:
    return fetch_pre_news_snapshot()


st.set_page_config(page_title="XAU Regime R5 — Research", page_icon="🔬", layout="wide")
st.title("RIZAN XAU — MicroAlpha R5")
st.caption("Closed M5 breakout/pullback + H1/M15 trend regime + V400 macro quality screen.")
st.error(
    "RESEARCH / SHADOW ONLY. Tidak menghasilkan perintah BUY/SELL LIVE. "
    "Pengujian historis belum membuktikan keunggulan yang aman untuk modal $100. "
    "Frozen V1 dan cBot LIVE tidak berubah."
)
now = datetime.now(UTC)
try:
    macro = macro_direction(macro_snapshot(), now=now)
except Exception as exc:
    macro = {"direction": "WAIT", "state": "WAIT_MACRO", "reason": type(exc).__name__}

st.subheader("Konteks makro sekarang — terpisah dari historical replay")
a, b, c = st.columns(3)
a.metric("Macro direction", macro.get("direction", "WAIT"))
b.metric("Quality", macro.get("state", "WAIT"))
c.metric("Reason", macro.get("reason", "NOT_AVAILABLE"))
st.caption(
    "V400 mensyaratkan kualitas data dan quote DXY serta yield/Fed futures dengan "
    "timestamp segar; kondisi WAIT berarti tidak ada konfirmasi. Data makro "
    "hari ini TIDAK digabung ke harga masa lalu. Probabilitas profit tidak diklaim."
)

st.subheader("Dataset M5 UTC untuk backtest")
upload = st.file_uploader("Unggah CSV M5 UTC (semua candle harus CLOSED)", type=["csv"])
try:
    historical = pd.read_csv(upload) if upload is not None else sample()
except Exception as exc:
    st.error(f"Tidak dapat mengambil sampel: {type(exc).__name__}. Upload M5 CSV.")
    st.stop()

x1, x2, x3, x4 = st.columns(4)
with x1:
    candidate = st.selectbox("R5 candidate", options=list(CANDIDATES))
with x2:
    cap = st.select_slider("Max risiko (%)", options=[1, 2, 5, 10], value=5)
with x3:
    min_lot = st.number_input("Min lot asumsi", min_value=.001, max_value=1.,
                              value=.01, step=.001, format="%.3f")
with x4:
    cost = st.number_input("Biaya roundtrip USD/oz", min_value=0., max_value=20.,
                           value=.8, step=.1)

y1, y2, y3, y4 = st.columns(4)
with y1:
    lot_step = st.number_input("Lot step asumsi", min_value=.001, max_value=1.,
                               value=.01, step=.001, format="%.3f")
with y2:
    lot_oz = st.number_input("Oz per lot asumsi", min_value=1., max_value=1000., value=100.)
with y3:
    rr = st.select_slider("Take profit target R", options=[1.5, 2., 2.5, 3.], value=2.)
with y4:
    max_margin = st.select_slider("Max margin (% equity)", options=[25, 40, 50], value=50)

cfg = R4Settings(
    initial_usd=100., leverage=200., min_lot=min_lot, lot_step=lot_step,
    contract_oz_per_lot=lot_oz, risk_fraction=cap / 100.,
    max_margin_fraction=max_margin / 100.,
    roundtrip_cost_usd_per_oz=cost, reward_r=rr,
)

try:
    data = features(historical)
    signals = build_signals(data, candidate=candidate)
    still_closed = signals["closed_at"].le(pd.Timestamp(now))
    signals = signals.loc[still_closed].reset_index(drop=True)
    if len(signals) < 2600:
        raise ValueError("TOO_FEW_COMPLETE_M5_BARS")
    result, ledger = backtest(signals, cfg, session="ASIA")
    shadow = live_shadow_state(
        signals, macro, now=pd.Timestamp(now), account_usd=100.0,
        risk_fraction=cap / 100., min_lot=min_lot, contract_oz=lot_oz,
        frict_usd_per_oz=cost, margin_limit=max_margin / 100.,
    )
except Exception as exc:
    st.error(f"Pengujian gagal/ditolak: {type(exc).__name__}: {exc}")
    st.stop()

last = signals.iloc[-1]["closed_at"]
age = (pd.Timestamp(now) - last).total_seconds()
source = "UPLOAD" if upload is not None else "PINNED_PUBLIC_HISTORICAL"
st.caption(
    f"{source} • {len(signals):,} M5 bars • "
    f"{signals.iloc[0]['datetime']:%Y-%m-%d} sampai {last:%Y-%m-%d %H:%M UTC}"
)
if age > 600 or age < 0:
    st.error("HISTORICAL / STALE — indikator ini bukan sinyal entry saat ini.")
st.subheader("Shadow checklist (tidak terhubung ke order)")
u, v, w = st.columns(3)
u.metric("Technical", shadow["technical"])
v.metric("Regime", shadow["regime"])
w.metric("Signal state", shadow["state"])
st.caption(
    "Meskipun seluruh filter lolos, status SHADOW_CONCORDANCE_ONLY tetap "
    "TIDAK memberi izin order. Stop/margin masih memakai asumsi, belum diverifikasi broker."
)

st.subheader("$100 compounding; leverage referensi 1:200; teknik tanpa makro historis")
a, b, c, d = st.columns(4)
a.metric("Saldo akhir", f"USD {result['ending_usd']:.2f}")
b.metric("Return simulasi", f"{result['net_pct']:+.2f}%")
c.metric("Profit factor", result["profit_factor"] if result["profit_factor"] is not None else "N/A")
d.metric("Trade count", result["count"])
a, b, c, d = st.columns(4)
a.metric("Closed DD", f"{result['closed_dd_pct']:.2f}%")
b.metric("OHLC intrabar DD*", f"{result['ohlc_floating_dd_estimate_pct']:.2f}%")
c.metric("Risk rejected", result["blocked_risk"])
d.metric("Margin rejected", result["blocked_margin"])
st.caption(
    "*Floating DD hanya estimasi rentang OHLC M5. Komisi, bid/ask tick, "
    "swap, exact dynamic margin dan slip nyata belum diuji. "
    "Harga periode publik tidak realtime."
)
if not ledger.empty:
    curve = ledger.copy()
    curve["entry_utc"] = pd.to_datetime(curve["entry_utc"], utc=True)
    st.line_chart(curve.set_index("entry_utc")["equity_usd"])
    st.dataframe(ledger.tail(100).iloc[::-1], hide_index=True, use_container_width=True)
    st.download_button("Unduh transaksi research", data=ledger.to_csv(index=False),
                       file_name="xau_r5_trades.csv", mime="text/csv")
else:
    st.info("Tidak ada transaksi yang memenuhi filter serta batas risiko/lot.")
st.caption(CONTRACT + " · execution_authority=false · execution_influence=false")

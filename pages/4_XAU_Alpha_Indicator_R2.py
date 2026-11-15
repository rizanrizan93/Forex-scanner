"""Read-only XAUUSD research page. No broker, bridge or order imports."""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from fx_scanner.xau_alpha_r2 import ResearchSettings, indicators, latest_indicator, simulate

PUBLIC_SAMPLE = ("https://raw.githubusercontent.com/getdata-finance/"
                 "xauusd-1h-ohlcv-metals-historical-data/main/XAUUSD_1h.csv")


@st.cache_data(ttl=21600)
def sample() -> pd.DataFrame:
    return pd.read_csv(PUBLIC_SAMPLE)


st.set_page_config(page_title="XAU Alpha R2 Research", page_icon="🔬", layout="wide")
st.title("RIZAN XAU — Indicator Alpha Lab R2")
st.caption("RESEARCH ONLY • Donchian 20 + EMA 200 + RSI 14 + ATR 14 • "
           "No execution authority; LIVE cBot and bridge remain untouched.")
st.warning("CSV historis bukan sinyal trading LIVE. Minimum lot dan contract size cTrader belum diverifikasi.")
file = st.file_uploader("Unggah XAU H1 CSV UTC (hanya candle CLOSED)", type=["csv"])
source = "UPLOAD" if file else "PUBLIC_SAMPLE_NOT_LIVE"
try:
    raw = pd.read_csv(file) if file else sample()
except Exception as exc:
    st.error(f"CSV tidak tersedia: {type(exc).__name__}. Silakan unggah file OHLC H1.")
    st.stop()

st.subheader("Akun simulasi")
p1, p2, p3, p4 = st.columns(4)
with p1:
    equity = st.number_input("Modal awal USD", min_value=1.0, value=100.0, step=10.0)
with p2:
    risk = st.select_slider("Risiko maksimum (%)", options=[1, 2, 5, 10, 20], value=5)
with p3:
    stop = st.select_slider("Stop loss (× ATR)", options=[0.25, 0.5, 1.0, 2.0], value=2.0)
with p4:
    session = st.selectbox("Jam entry WIB", ["ALL", "ASIA_08_13", "NY_19_24"])
p5, p6, p7, p8 = st.columns(4)
with p5:
    min_lot = st.number_input("Min lot (asumsi)", min_value=0.001, value=0.01, step=0.001, format="%.3f")
with p6:
    lot_step = st.number_input("Lot step (asumsi)", min_value=0.001, value=0.01, step=0.001, format="%.3f")
with p7:
    contract = st.number_input("Oz per lot (asumsi)", min_value=1.0, value=100.0, step=1.0)
with p8:
    friction = st.number_input("Friksi roundtrip USD/oz", min_value=0.0, value=0.8, step=0.1)
cfg = ResearchSettings(
    initial_equity=float(equity), leverage=200.0, contract_oz_per_lot=float(contract),
    min_lot=float(min_lot), lot_step=float(lot_step), risk_fraction=risk / 100,
    stop_atr=float(stop), friction_usd_per_oz_roundtrip=float(friction),
)
try:
    bars = indicators(raw)
    signal = latest_indicator(bars, cfg)
    summary, trades = simulate(bars, cfg, session=session)
except Exception as exc:
    st.error(f"Input invalid: {type(exc).__name__}: {exc}")
    st.stop()
last = bars.iloc[-1]["datetime"]
age_h = (datetime.now(timezone.utc) - last.to_pydatetime()).total_seconds() / 3600
st.caption(
    f'Dataset {source}: {len(bars):,} candle • '
    f'{bars.iloc[0]["datetime"]:%Y-%m-%d} s.d. {last:%Y-%m-%d %H:%M UTC} • '
    f'age {age_h:.1f} hours'
)
if age_h > 2 or age_h < -0.1:
    st.error("STALE / HISTORICAL — sinyal ini tidak berlaku untuk entry LIVE.")

st.subheader("Indikator terbaru DALAM DATASET")
c1, c2, c3, c4 = st.columns(4)
c1.metric("Signal", signal["direction"])
c2.metric("Risk gate", signal["state"])
c3.metric("RSI 14", signal["rsi14"])
c4.metric("ATR 14", signal["atr14"])
st.caption(
    f'Close {signal["close"]:.2f} • EMA200 {signal["ema200"]:.2f} • '
    f'Donchian {signal["channel_low20"]:.2f}–{signal["channel_high20"]:.2f} • '
    f'Minimum-lot risk USD {signal["minimum_lot_risk_usd"]:.2f} • '
    f'Minimum-lot margin USD {signal["minimum_lot_margin_usd"]:.2f}'
)
st.info("Yield/DXY macro confirmation: NOT CONNECTED. No inferred win probability.")

st.subheader("Replay $100 compounding, leverage 1:200")
a, b, c, d = st.columns(4)
a.metric("Ending equity", f'USD {summary["final_usd"]:.2f}')
b.metric("Net return", f'{summary["net_return_pct"]:+.2f}%')
c.metric("Profit factor", summary["profit_factor"] if summary["profit_factor"] is not None else "N/A")
d.metric("Trades", summary["trades"])
a, b, c, d = st.columns(4)
a.metric("Closed DD", f'{summary["closed_trade_dd_pct"]:.2f}%')
b.metric("Intrabar OHLC DD*", f'{summary["intrabar_dd_estimate_pct"]:.2f}%')
c.metric("Risk blocked", summary["blocked_by_risk"])
d.metric("Margin blocked", summary["blocked_by_margin"])
st.caption(
    "*OHLC estimate, bukan tick floating DD. SL dieksekusi lebih dulu pada candle ambigu. "
    "Spread/slippage memakai asumsi tetap; swap dan broker-specific margin tidak tervalidasi. "
    "Hasil ini belum layak untuk eksekusi."
)
if trades.empty:
    st.warning("Tidak ada trade yang lolos minimum lot, risk cap, dan margin. Jangan paksa sizing.")
else:
    st.line_chart(trades.set_index("entry_utc")["equity_usd"])
    st.dataframe(trades.tail(100).iloc[::-1], hide_index=True, use_container_width=True)
    st.download_button("Download replay CSV", data=trades.to_csv(index=False),
                       file_name="xau_alpha_r2_trades.csv", mime="text/csv")
st.caption("RIZAN_XAU_ALPHA_R2_RESEARCH_ONLY • execution_authority=false • execution_influence=false")

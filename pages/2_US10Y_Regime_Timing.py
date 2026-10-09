from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if SRC.is_dir() and str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fx_scanner.xau_turso_hot_snapshot_v407 import fetch_public_hot_snapshot  # noqa: E402
from fx_scanner.xau_yield_regime_view_v372 import yield_regime_summary  # noqa: E402


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


st.set_page_config(page_title="RIZAN US10Y", layout="wide")
st.title("RIZAN — US10Y Regime & Timing")
st.caption(
    "Daily FRED dipakai untuk regime makro. Intraday US10Y dipakai untuk timing/pressure. "
    "Keduanya tidak memberi izin order sendiri; keputusan tetap harus dikonfirmasi struktur XAU."
)

try:
    snapshot = fetch_public_hot_snapshot()
except Exception as exc:
    st.error(f"Public HOT snapshot belum tersedia: {type(exc).__name__}: {exc}")
    st.stop()

macro_hb = {}
for raw in list(snapshot.get("heartbeats") or []):
    row = dict(raw or {})
    if row.get("worker_name") == "ctrader_demo_xau_macro_attribution_v357":
        macro_hb = row
        break

macro_eval = dict(dict(macro_hb.get("details") or {}).get("evaluation") or {})
if not macro_eval:
    st.warning("Snapshot macro V357 belum tersedia.")
    st.stop()

summary = yield_regime_summary(macro_eval)
daily = dict(summary.get("daily") or {})
intraday = dict(summary.get("intraday") or {})

c1, c2 = st.columns(2)
with c1:
    st.markdown("### US10Y Daily Regime")
    st.metric("Bias terhadap XAU", bias_label(daily.get("gold_bias")))
    st.metric(
        "FRED DGS10",
        fmt(daily.get("current"), "%"),
        delta=(
            None
            if daily.get("delta_bps") is None
            else f"{float(daily.get('delta_bps')):+.1f} bps vs prior day"
        ),
    )
    st.caption(
        "Fungsi: menentukan backdrop 1–beberapa hari. Yield harian turun = tailwind XAU; "
        "yield harian naik = headwind XAU. Ini bukan trigger entry."
    )

with c2:
    st.markdown("### US10Y Intraday Pressure")
    st.metric("Bias terhadap XAU", bias_label(intraday.get("gold_bias")))
    st.metric(
        "Yield intraday sekarang",
        fmt(intraday.get("current"), "%"),
        delta=(
            None
            if intraday.get("rebound_from_low_bps") is None
            else f"{float(intraday.get('rebound_from_low_bps')):+.1f} bps dari low pasca-event"
        ),
    )
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
            "intraday_state": intraday.get("state"),
            "intraday_source": intraday.get("source"),
            "alignment": alignment,
        }
    )

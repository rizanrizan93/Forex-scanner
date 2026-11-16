"""Mobile-first separate Frozen V1 directional-audit tab.

Only independently published read-only market/status snapshots are consumed.
No order path, cBot, frozen configuration, lease or bridge is modified.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import streamlit as st

from .cbot_v1_dashboard import (
    MARKET_URL, SOURCE_URL, evaluate_snapshot, fetch_json, fetch_snapshot, wib,
)
from .frozen_v1_directional_score import SYMBOLS, evaluate_bias
from .ui_terminal import render_condition


def _fmt_score(value):
    return "—" if value is None else f"{value:.0f}/100"


def _session_note(symbol: str, phase: str) -> str:
    if phase == "SEED":
        return ("SEED: hanya EURUSD BUY, Senin–Jumat, sebelum 03.00 WIB "
                "hari berikutnya. Eksekusi tetap tunduk pada guard native.")
    if phase != "GROWTH":
        return "Fase belum diverifikasi."
    if symbol == "XAUUSD":
        return ("XAU GROWTH: displacement mulai 12.00 WIB; compression "
                "19.00–00.00 WIB. Keduanya tetap tunduk pada jadwal native.")
    if symbol == "EURUSD":
        return ("EUR GROWTH: incumbent M15 14.00–19.00 WIB; AsiaBuy "
                "hingga 00.00 WIB. Skor saat ini hanya menilai incumbent.")
    return "BTC GROWTH: weekend guard dan feed Bitstamp native 7D tetap wajib."


@st.cache_data(ttl=10, show_spinner=False)
def _cached(kind: str, slot: int):
    if kind == "status":
        return fetch_snapshot(slot)
    return fetch_json(MARKET_URL, slot)


def _read(kind: str):
    try:
        return _cached(kind, int(datetime.now(timezone.utc).timestamp() // 10))
    except (OSError, ValueError, TypeError, KeyError, TimeoutError):
        return None


def _panel():
    now = datetime.now(timezone.utc)
    st.subheader("Frozen V1 · Bias BUY vs SELL")
    st.caption(
        "LIVE ••••7903 · profil RIZAN_BOOTSTRAP125_V1_FROZEN_20261114 · "
        "skor berbasis subset aturan candle frozen, bukan skor SMC/ICT dan "
        "bukan probabilitas menang."
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        future_status = pool.submit(_read, "status")
        future_market = pool.submit(_read, "market")
        raw, market = future_status.result(), future_market.result()

    model = None
    try:
        if raw is not None:
            model = evaluate_snapshot(raw, now=now)
    except (ValueError, TypeError, KeyError):
        pass
    phase = model["phase"] if model else "UNKNOWN"
    report = evaluate_bias(market, phase=phase, now=now)
    phase_col, market_col = st.columns(2)
    phase_col.metric("Fase native V1", phase)
    market_col.metric("Market snapshot", "VALID" if any(
        x["market_valid"] for x in report["symbols"].values()) else "WAIT DATA")
    st.caption(
        "Data diperiksa " + wib(now.isoformat())
        + " · candle broker " + wib(market.get("observed_at") if isinstance(market, dict) else None)
        + " · state V1 " + wib(raw.get("observed_at") if isinstance(raw, dict) else None)
    )
    if not model or not model["bridge_ready"]:
        st.warning("Koneksi/lease V1 belum terverifikasi segar. "
                   "Skor candle tidak membuktikan bahwa cBot siap mengirim order.")
    st.caption(
        "BUY dan SELL berdiri sendiri, bukan total 100. Score 80/100 berarti "
        "80 poin aturan candle teramati pada satu keluarga strategi; "
        "bukan peluang profit 80%, bukan konfirmasi entry native."
    )
    tabs = st.tabs(list(SYMBOLS))
    for tab, symbol in zip(tabs, SYMBOLS):
        with tab:
            item = report["symbols"][symbol]
            st.markdown("#### " + symbol)
            st.write("**Bias:** " + item["bias"])
            bcol, scol = st.columns(2)
            for col, side in ((bcol, "BUY"), (scol, "SELL")):
                d = item[side]
                col.metric(side + " · skor V1", _fmt_score(d["score"]))
                col.caption("Cakupan keluarga terbaik: " + str(d["coverage"]) + "/100"
                            + (" · " + d["family"] if d["family"] else ""))
                if d["score"] is not None:
                    col.progress(d["score"] / 100)
            st.caption(_session_note(symbol, phase))
            if item["reason"]:
                st.info(item["reason"])
            for side in ("BUY", "SELL"):
                for family in item[side]["families"]:
                    with st.expander(
                        side + " · " + family["family"] + " · skor "
                        + _fmt_score(family["score"])
                        + " · cakupan " + str(family["coverage"]) + "%",
                        expanded=False,
                    ):
                        for check in family["checks"]:
                            render_condition(
                                st, title=check["name"], state=check["state"],
                                detail=check["detail"], meta=str(check["weight"]) + " poin"
                            )
            if symbol == "BTCUSD":
                st.caption("Tidak memakai candle CFD XAU/EUR/BTC sebagai pengganti "
                           "native BITSTAMP_BTCUSD_M1 7D. Skor akan tetap — "
                           "sampai data native terverifikasi dipublikasikan.")
            if model is not None:
                st.caption("Status instance: "
                           + str(model["statuses"].get(symbol, "UNKNOWN")))
    st.divider()
    st.caption(
        "Audit ini READ ONLY. Aturan posisi, fase, risiko, cooldown, "
        "filter berita/yield, broker dan weekend guard tidak disederhanakan. "
        "Tidak ada klaim missed order tanpa native intent + Journal + broker history."
    )
    st.markdown("[Baca kontrak Frozen V1](" + SOURCE_URL + ")")


def render_frozen_v1_bias_dashboard():
    st.fragment(run_every="15s")(_panel)()

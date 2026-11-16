"""Mobile-first separate Frozen V1 directional-audit tab.

Only independently published read-only market/status snapshots are consumed.
No order path, cBot, frozen configuration, lease or bridge is modified.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Lock
from time import monotonic

import streamlit as st

from .cbot_v1_dashboard import (
    MARKET_URL, SOURCE_URL, evaluate_snapshot, fetch_json, fetch_snapshot, wib,
)
from .frozen_v1_directional_score import SYMBOLS, evaluate_bias
from .xau_stable_h1_context import from_v1_market, explain_vs_fast
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


@st.cache_data(ttl=86400, show_spinner=False)
def _btc_seed():
    from .btc_native_readonly import load_seed
    return load_seed()


@st.cache_data(ttl=86400, show_spinner=False)
def _btc_chunk(start, end):
    from .btc_native_readonly import load_minutes
    return load_minutes(start, end)


@st.cache_data(ttl=3600, show_spinner=False)
def _btc_packet(through):
    from .btc_native_readonly import build_packet
    return build_packet(through, _btc_seed(), _btc_chunk)


@st.cache_resource
def _btc_jobs():
    return ThreadPoolExecutor(max_workers=1), {}, Lock()


def _btc_observation(through):
    # Cold reconstruction runs in the background; FX tabs and refresh stay responsive.
    worker, jobs, lock = _btc_jobs()
    with lock:
        future, started = jobs.get(through, (None, 0))
        if future is not None and future.done() and future.exception() is not None and monotonic()-started >= 60:
            future = None
        if future is None:
            future = worker.submit(_btc_packet, through)
            jobs[through] = future, monotonic()
        for key in list(jobs):
            if key != through and jobs[key][0].done():
                del jobs[key]
    return future.result() if future.done() else None


def _panel():
    now = datetime.now(timezone.utc)
    st.subheader("Frozen V1 · Pola BUY vs SELL")
    st.caption(
        "LIVE ••••7903 · profil RIZAN_BOOTSTRAP125_V1_FROZEN_20261114 · "
        "skor kecocokan sebagian pola frozen, bukan skor kesiapan eksekusi, dan "
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
    native = None
    native_error = None
    if phase == "GROWTH":
        try:
            native = _btc_observation(int(datetime.now(timezone.utc).timestamp()) // 3600 * 3600)
        except (OSError, ValueError, TypeError, KeyError, TimeoutError) as exc:
            native_error = type(exc).__name__
    now = datetime.now(timezone.utc)
    report = evaluate_bias(market, phase=phase, now=now, btc_native=native)
    stable_h1 = from_v1_market(market, now)
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
            if symbol == "XAUUSD":
                st.metric("Konteks H1 stabil (2 candle tertutup)", stable_h1["direction"])
                raw_side = ("BUY" if item["bias"] == "BUY LEBIH KUAT"
                            else "SELL" if item["bias"] == "SELL LEBIH KUAT" else None)
                st.caption(explain_vs_fast(stable_h1, raw_side))
                st.caption("Konteks H1 independen, bukan aturan Frozen V1. "
                           "Mengikuti EMA5/EMA8 dan 2 close H1; tidak mengubah trigger atau order.")
            st.write("**Trigger pola cepat V1 (dapat berubah per candle):** " + item["bias"])
            st.caption("Kesiapan native: BELUM DIVERIFIKASI. Skor terbaik hanya salah satu "
                       "keluarga entry, tidak berarti semua guard V1 terpenuhi.")
            bcol, scol = st.columns(2)
            for col, side in ((bcol, "BUY"), (scol, "SELL")):
                d = item[side]
                col.metric(side + " · skor pola parsial", _fmt_score(d["score"]))
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
                meta = item.get("native_source")
                if meta:
                    st.caption("Sumber independen: " + meta["source"] + " · H1 selesai: " + wib(meta["through"])
                               + " · H4 selesai: " + wib(meta["h4_close"]) + " · seed SHA256 cocok V1 · "
                               + str(meta["hourly_count"]) + " H1. Bukan bukti feed diterima terminal.")
                    st.caption("Incumbent BUY: waktu close H4 UTC <08; Break40: close H4; SELL: close H1. "
                               "Weekend, konflik sinyal dan seluruh guard terminal tetap wajib; skor hanya pola candle.")
                elif phase == "GROWTH" and native_error is None:
                    st.info("Sedang melengkapi dan memvalidasi history Bitstamp sejak seed. Tab memperbarui otomatis; pembacaan pertama membutuhkan waktu lebih lama.")
                elif native_error:
                    st.warning("Sumber native BTC belum berhasil dibaca (" + native_error + "). Skor ditahan sampai validasi berhasil; tidak memakai CFD sebagai pengganti.")
            if model is not None:
                st.caption("Status instance: "
                           + str(model["statuses"].get(symbol, "UNKNOWN")))
    st.divider()
    st.caption(
        "Audit ini READ ONLY. Aturan posisi, fase, risiko, cooldown, "
        "filter berita/yield, broker dan weekend guard tidak disederhanakan. "
        "Tidak ada klaim missed order tanpa native intent + Journal + broker history."
    )
    st.markdown("[Buka Panel Konsensus V1](https://forexrizan.streamlit.app/Konsensus_V1)")
    st.markdown("[Baca kontrak Frozen V1](" + SOURCE_URL + ")")


def render_frozen_v1_bias_dashboard():
    st.fragment(run_every="15s")(_panel)()

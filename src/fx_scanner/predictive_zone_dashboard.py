"""Streamlit view for the read-only predictive A->B research map."""
from __future__ import annotations

from datetime import UTC, datetime
import json

from .predictive_zone_to_zone import build_zone_paths
from .zone_v05_dashboard import fetch
from .manual_reversal_dashboard import wib


def _fmt(value):
    return f"{value:,.2f}" if isinstance(value, (int, float)) else "—"


def _label(reason):
    return str(reason or "DATA_BELUM_LENGKAP").replace("_", " ").capitalize()


def render_snapshot(snapshot, *, now=None):
    import streamlit as st

    p = build_zone_paths(snapshot, now=now)
    st.subheader("RIZAN · Predictive Zone-to-Zone A → B")
    st.caption("Versi dashboard: A→B 1.0 · 22 Oktober 2026 · tampilan riset manual")
    st.caption("Peta manual H4/H1 → validasi M15/M5. Zona A dipilih sebelum disentuh; B harus zona lawan yang sudah terbentuk dan belum tersentuh, bukan target yang diciptakan dari prediksi.")
    st.info("Mode riset read-only. Tidak mengirim limit order, tidak memengaruhi cBot, dan belum memiliki win rate/probabilitas yang terkalibrasi. RR LIMIT adalah **kotor**, belum memasukkan spread, komisi, slippage atau swap.")
    if p["price"] is None:
        st.warning("WAIT · " + _label(p["reason"]) + ". Harga, SL dan TP disembunyikan sampai feed segar.")
        st.caption("Close sumber: " + wib(p.get("closed_at")) + " · diterbitkan: " + wib(p.get("as_of")))
        return

    st.caption("Harga referensi: " + _fmt(p["price"]) +
               " · close M5: " + wib(p.get("closed_at")) +
               " · bias EMA H1: " + str(p["bias"].get("H1", "—")) +
               " · H4: " + str(p["bias"].get("H4", "—")))
    mode = st.radio("Jenis analisis", ["LIMIT · sebelum sentuhan", "CONFIRMED · M15 → M5"],
                    horizontal=True, key="rizan_zone_path_mode")
    if mode.startswith("LIMIT"):
        st.markdown("#### LIMIT · pemetaan zona sebelum harga tiba")
        st.caption("Area berasal dari zona WATCH V05 atau supply-demand H1/H4 yang sudah dipublikasikan. Hanya riwayat M1 yang terbukti lengkap dapat dinyatakan belum first touch. Pending invalidation, zona berusia >24 jam, konflik H1/H4, atau target lawan yang tidak tersedia tetap WAIT.")
        if not p["limit"]:
            st.warning("WAIT · belum ada zona sumber yang layak dipetakan.")
        for side in ("BUY", "SELL"):
            options = [z for z in p["limit"] if z["side"] == side]
            st.markdown("##### " + side + " · " + ("Demand" if side == "BUY" else "Supply"))
            if not options:
                st.caption("Tidak ada zona " + side + " valid dalam snapshot terbaru.")
                continue
            for row in options[:2]:
                with st.container(border=True):
                    a, b = row["source"], row["target"]
                    st.markdown("**" + row["state"] + " · " + _label(row["reason"]) + "**")
                    st.caption(row["family"] + " · " + row["origin"] + " · " + a["timeframe"] +
                               " · terbentuk " + wib(a["formed_at"]))
                    st.metric("Zona A (" + side + ")", _fmt(a["low"]) + " – " + _fmt(a["high"]))
                    c1, c2, c3 = st.columns(3)
                    c1.metric("Limit acuan", _fmt(row["entry_reference"]))
                    c2.metric("SL model", _fmt(row["sl_reference"]))
                    c3.metric("TP sebelum B", _fmt(row["tp_reference"]))
                    if b:
                        st.write("**Zona B (" + b["side"] + ")** " + _fmt(b["low"]) + " – " + _fmt(b["high"]) +
                                 " · " + str(b["timeframe"]))
                    else:
                        st.warning("Belum ada zona B lawan yang lolos validasi first touch. Tidak ada TP atau entry yang disahkan.")
                    if row.get("gross_rr") is not None:
                        st.caption("RR geometris (belum biaya): " + f"{row['gross_rr']:.2f}R")
                    st.caption("First touch tervalidasi belum terjadi: " +
                               ("Ya" if row["first_touch_verified"] else "Tidak / riwayat tidak cukup") +
                               " · status tidak memberikan izin order.")
    else:
        st.markdown("#### CONFIRMED · acuan terpisah dari V05")
        st.caption("Reclaim M15 dan break struktur M5 wajib selesai sebelum entry referensi open M1. Tidak mengubah eksekusi atau mengubah WATCH menjadi ENTRY.")
        if not p["confirmed"]:
            st.warning("WAIT · belum ada rencana V05 yang memenuhi atau menunggu konfirmasi.")
        for row in p["confirmed"]:
            with st.container(border=True):
                a = row["source"]
                st.markdown("**" + row["side"] + " · " + row["state"] + "**")
                st.caption(_label(row["reason"]))
                st.metric("Zona A · " + a["timeframe"], _fmt(a["low"]) + " – " + _fmt(a["high"]))
                st.write("First touch: " + wib(row.get("first_touch_at")))
                st.write("Reclaim M15: " + wib(row.get("reclaim_m15_at")) +
                         " · BOS M5: " + wib(row.get("confirmation_m5_at")))
                if row["state"] == "ENTRY_REFERENSI":
                    c1, c2, c3 = st.columns(3)
                    c1.metric("Entry open M1", _fmt(row["entry_reference"]))
                    c2.metric("SL skenario", _fmt(row["sl_reference"]))
                    c3.metric("TP sebelum B", _fmt(row["tp_reference"]))
                    if row["target"]:
                        b = row["target"]
                        st.caption("Zona B " + b["timeframe"] + ": " +
                                   _fmt(b["low"]) + " – " + _fmt(b["high"]) +
                                   " · RR net proxy: " + _fmt(row.get("net_rr")))
                else:
                    st.caption("Harga eksekusi tidak dipromosikan sebagai entry. Menunggu syarat V05.")
    with st.expander("Kontrak dan keterbatasan penelitian", expanded=False):
        st.caption("Input adalah snapshot zona V05 yang sudah ada, bukan feed order book institusi. Tidak ada kalibrasi probabilitas perjalanan A→B, historical forward test khusus strategi LIMIT, atau fill bid/ask broker untuk metode ini.")
        st.caption("Target B hanya dipilih dari zona lawan dengan M1 first-touch yang terbukti lengkap. Jika tidak tersedia, TP tidak boleh diisi otomatis. Tidak ada reverse order B→C tanpa sinyal baru.")
        st.caption("Compounding, layering equity, ukuran lot dan margin tidak dihitung oleh panel ini. cBot dan bridge tidak dimodifikasi.")
        st.download_button("Unduh audit peta A→B", json.dumps(p, indent=2, default=str),
                           file_name="RIZAN_XAU_ZONE_PATH_READONLY.json",
                           mime="application/json", key="rizan_zone_path_export")


def _render():
    import streamlit as st
    load = st.cache_data(ttl=15, show_spinner=False)(fetch)
    try:
        render_snapshot(load())
    except (ValueError, TypeError, KeyError, OSError):
        st.subheader("RIZAN · Predictive Zone-to-Zone A → B")
        st.warning("WAIT · data peta tidak dapat divalidasi. Tidak ada entry yang diterbitkan.")


def render_predictive_zone_dashboard():
    import streamlit as st
    st.fragment(run_every="30s")(_render)()

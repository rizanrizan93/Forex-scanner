"""Streamlit read-only R28.1 direction -> SMC zone -> M5 entry board."""
from __future__ import annotations
from datetime import UTC, datetime

import pandas as pd

from .manual_r3_feed import fetch_market
from .r281_shadow_feed import fetch as fetch_r281, reason_text
from .r281_smc_entry_engine import evaluate_entry


REASONS = {
    "R28_D1_H4_MISSING_OR_EXPIRED": "R28.1 D1/H4 tidak aktif atau telah kedaluwarsa.",
    "R28_D1_H4_CONFLICT": "R28.1 D1 dan H4 berlawanan; zona entry ditahan.",
    "R28_H1_OPPOSING": "R28.1 H1 berlawanan dengan arah D1/H4.",
    "R28_H1_NOT_CONFIRMED": "H1 belum mengonfirmasi arah D1/H4; entry ditahan.",
    "R28_H4_ABSTAIN_WATCH_ONLY": "D1 dan H1 searah; H4 abstain. Pantau zona tanpa entry.",
    "R28_H4_ABSTAIN_ENTRY_BLOCKED": "H4 WAIT MODEL (ambang skor); zona tetap terlihat, harga entry diblokir.",
    "R28_H4_ABSTAIN_NO_VALID_ZONE": "D1 dan H1 searah, tetapi H4 abstain dan belum ada zona H1/H4 valid.",
    "BROKER_M1_UNAVAILABLE": "Feed candle M1 cTrader tidak tersedia.",
    "BROKER_M1_STALE": "Data M1 cTrader terlambat; tunggu pembaruan.",
    "M1_HISTORY_INSUFFICIENT": "Riwayat M1 tidak cukup untuk membangun zona.",
    "M1_DUPLICATED_TIME": "Ada timestamp M1 duplikat; zona tidak dapat digunakan.",
    "LAST_M1_NOT_FRESH": "Candle M1 terakhir kedaluwarsa.",
    "CLOSED_M5_M15_UNAVAILABLE": "Candle lengkap M5/M15 belum tersedia.",
    "NO_VALID_CLOSED_H1_H4_BOS_ZONE": "Belum ada zona H1/H4 base-displacement + BOS yang lolos.",
    "ENTRY_CANDLE_CONTRACT_FAILED": "Struktur data candle tidak lolos validasi.",
    "MENUNGGU_HARGA_SENTUH_ZONA": "Pantau harga menuju zona; belum ada first touch.",
    "ZONE_ORIGIN_OUTSIDE_M1_HISTORY": "Riwayat M1 tidak mencakup awal zona; first touch tidak bisa dibuktikan.",
    "UNVERIFIED_FIRST_TOUCH_M1_GAP": "Ada candle M1 hilang sebelum sentuhan zona.",
    "FIRST_TOUCH_TOO_OLD_FOR_ENTRY": "First touch sudah melewati jendela 90 menit.",
    "WAIT_M15_REJECTION_RECLAIM": "Zona tersentuh, menunggu rejection/reclaim M15.",
    "WAIT_M5_BOS_AFTER_M15": "M15 terkonfirmasi, menunggu BOS 3 candle M5.",
    "M5_BOS_ALREADY_PASSED": "BOS M5 terjadi lebih dari 10 menit lalu; tidak mengejar harga.",
    "QUOTE_SPREAD_NOT_FRESH": "Quote bid/ask atau spread belum segar.",
    "PRICE_ALREADY_MOVED_FROM_BOS": "Harga sudah terlalu jauh dari BOS M5.",
    "STOP_DISTANCE_OR_COST_INVALID": "Jarak SL tidak memenuhi risk/spread gate.",
    "R28_M15_M5_RESEARCH_ALIGNMENT": "Semua syarat observasi terpenuhi, tetapi belum lulus replay entry gabungan.",
    "FEED_UNAVAILABLE": "Feed R28.1 atau broker tidak dapat diakses.",
}


def _wib(value):
    return pd.Timestamp(value).tz_convert("Asia/Jakarta").strftime("%d/%m %H:%M:%S WIB") if value else "—"


def render_r281_smc_entry():
    import streamlit as st

    st.subheader("XAUUSD · Titik Entry R28.1 × SMC")
    st.caption(
        "R28.1 D1/H4/H1 = filter arah; zona base-displacement H1/H4 dari broker M1; "
        "M15 rejection/reclaim → BOS 3 candle M5 → harga bid/ask segar. "
        "Engine masih tahap riset, bukan hasil replay entry gabungan atau instruksi order."
    )

    @st.cache_data(ttl=20, show_spinner=False)
    def load(slot):
        try:
            shadow=fetch_r281()
        except (OSError, ValueError, TypeError, KeyError, TimeoutError, OverflowError):
            shadow={}
        try:
            market=fetch_market()
        except (OSError, ValueError, TypeError, KeyError, TimeoutError, OverflowError):
            market=None
        return shadow,market

    @st.fragment(run_every="30s")
    def panel():
        now=datetime.now(UTC)
        shadow,market=load(int(now.timestamp()//20))
        report=evaluate_entry(shadow,market,now=now)
        context=report["context"]

        st.markdown("### Kesiapan setup manual")
        c1,c2,c3=st.columns(3)
        c1.metric("Arah pantauan",report["side"])
        c2.metric("Status entry riset",report["status"])
        c3.metric("Konfirmasi H1","SEARAH" if context.get("h1_confirmed") else "WAIT")
        if report.get("watch_only"):
            st.warning("H4 = WAIT MODEL (BELOW_THRESHOLD). D1/H1 searah sehingga hanya zona WATCH ditampilkan. "
                       "Tidak ada harga entry ataupun izin trade sampai H4 memberi sinyal valid.")
        if context.get("weekly_countertrend"):
            st.warning("W1 berlawanan dengan arah pantauan D1/H1/H4. "
                       "Ini konteks kontra arah mingguan, bukan rekomendasi entry.")
        if context:
            st.dataframe([
                {"Timeframe":tf,"Arah model aktif":context.get(tf,"WAIT")}
                for tf in ("H1","H4","D1","W1")
            ],hide_index=True,width="stretch")
        st.caption("Pemeriksaan: "+_wib(report["checked_at"])+" · arah menggunakan R28.1 SHADOW (bukan benchmark kandidat R1–R28).")
        st.write("**Alasan/status:** "+REASONS.get(report["reason"],report["reason"]))
        zone=report.get("zone")
        if zone:
            st.markdown("### Zona harga hasil rekonstruksi candle cTrader")
            z1,z2,z3=st.columns(3)
            z1.metric("Zona "+zone["timeframe"],f'{zone["low"]:,.2f} – {zone["high"]:,.2f}')
            z2.metric("SL struktural indikatif",f'{zone["invalidation_reference"]:,.2f}')
            z3.metric("Harga candle referensi",f'{zone["last_price"]:,.2f}')
            st.caption(
                "Zona: "+zone["side"]+" · dibentuk "+_wib(zone["formed_at"])
                +" · first touch "+_wib(zone["touch_at"])
                +" · reclaim M15 "+_wib(zone["reclaim_at"])
                +" · BOS M5 "+_wib(zone["bos_at"])
            )
            st.caption("Zona dihitung dari metode base-displacement pada candle broker tertutup. "
                       "Bukan keluaran strategi EMA V05 yang sudah direplay; jangan menyamakan keduanya.")
        if report["status"]=="M5_BOS_CONFIRMED":
            st.warning("KONFIRMASI RISET SAJA · keputusan trading manual tetap membutuhkan audit independen. Tidak ada auto-order.")
            d1,d2,d3,d4=st.columns(4)
            d1.metric("Entry bid/ask referensi",f'{report["entry_reference"]:,.2f}')
            d2.metric("SL referensi",f'{report["sl_reference"]:,.2f}')
            d3.metric("TP simulasi 1,5R",f'{report["tp_1_5r_reference"]:,.2f}')
            d4.metric("TP simulasi 2R",f'{report["tp_2r_reference"]:,.2f}')
            st.caption(
                "Spread bid/ask "+f'{report["spread"]:.2f}'
                +" USD/oz · risiko struktural "+f'{report["risk_per_oz"]:.2f}'
                +" USD/oz · konfirmasi "+_wib(report["confirmation_at"])
                +" · level TP adalah proyeksi R, belum target likuiditas/backtest.")
        else:
            st.info("WAIT ENTRY · belum ada harga entry yang memenuhi semua filter. "
                    "Tampilkan zona pantauan tanpa memasang order otomatis.")
        if report.get("candidates"):
            st.markdown("### Zona kandidat & checkpoint")
            st.dataframe([
                {"TF":z["timeframe"],"Side":z["side"],"Zona":f'{z["low"]:.2f}–{z["high"]:.2f}',
                 "Tahap":z["status"],"Alasan":REASONS.get(z["reason"],z["reason"]),
                 "Dibentuk WIB":_wib(z["formed_at"])}
                for z in report["candidates"]
            ],hide_index=True,width="stretch")
        st.caption("Klausul: output non-eksekusi, tanpa modifikasi Frozen V1, "
                   "tanpa klaim akurasi/expectancy/TP dari replay gabungan. "
                   "Bila snapshot gagal atau candle belum valid, engine tetap WAIT.")
    panel()

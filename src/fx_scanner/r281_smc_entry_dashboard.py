"""Streamlit read-only BEST CANDIDATES direction -> SMC watch/zone board."""
from __future__ import annotations
from datetime import UTC, datetime

import pandas as pd

from .manual_r3_feed import fetch_market
from .r281_shadow_feed import fetch as fetch_r281
from .rbest_side_feed import fetch as fetch_rbest
from .r294_frozen_h4_buy_feed import fetch as fetch_r294
from .best_candidate_direction import select as select_best_candidate_direction
from .best_candidate_smc import evaluate_best_entry


REASONS = {
    "BEST_H4_MISSING_OR_EXPIRED": "Arah H4 kandidat terbaik belum valid atau sudah berakhir; zona entry ditahan.",
    "BEST_H1_OPPOSING": "H1 kandidat terbaik berlawanan dengan H4; zona entry ditahan.",
    "BEST_D1_OPPOSING": "D1 kandidat terbaik berlawanan dengan H4; zona entry ditahan.",
    "BEST_DIRECTION_INCOMPLETE_WATCH_ONLY":
        "H4 valid, tetapi H1/D1 belum lengkap; zona WATCH saja, bukan entry.",
    "BEST_DIRECTION_INCOMPLETE_ENTRY_BLOCKED":
        "Zona terpantau, namun belum ada konfirmasi H1 dan D1 independen lengkap. Seluruh harga entry/SL/TP diblokir.",
    "BEST_DIRECTION_INCOMPLETE_NO_VALID_ZONE":
        "Arah H4 valid untuk pantauan; belum ada zona struktur broker valid.",
    "BEST_DIRECTION_ALIGNED": "H1, H4 dan D1 independen lengkap searah (research-only).",
    "R28_D1_H4_MISSING_OR_EXPIRED": "R28.1 D1/H4 tidak aktif atau telah kedaluwarsa.",
    "R28_D1_H4_CONFLICT": "R28.1 D1 dan H4 berlawanan; zona entry ditahan.",
    "R28_H1_OPPOSING": "R28.1 H1 berlawanan dengan arah D1/H4.",
    "R28_H1_NOT_CONFIRMED": "H1 belum mengonfirmasi arah D1/H4; entry ditahan.",
    "R28_H4_ABSTAIN_WATCH_ONLY": "D1 dan H1 searah; H4 abstain. Pantau zona tanpa entry.",
    "R28_H4_ABSTAIN_ENTRY_BLOCKED": "H4 WAIT MODEL (ambang skor); zona tetap terlihat, harga entry diblokir.",
    "R28_H4_ABSTAIN_NO_VALID_ZONE": "D1 dan H1 searah, tetapi H4 abstain dan belum ada zona H1/H4 valid.",
    "LIVE_PRICE_BEYOND_ZONE_INVALIDATION_WAIT_SOURCE_CLOSE": "Harga melewati batas invalidasi zona saat candle sumber belum ditutup; bukan zona entry.",
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
    "FEED_UNAVAILABLE": "Feed kandidat terbaik atau broker tidak dapat diakses.",
}


def _wib(value):
    return pd.Timestamp(value).tz_convert("Asia/Jakarta").strftime("%d/%m %H:%M:%S WIB") if value else "—"


def render_r281_smc_entry():
    import streamlit as st

    st.subheader("XAUUSD · Titik Entry Kandidat Terbaik × SMC")
    st.caption(
        "Direction berasal dari R25/R11 H1, R29.2/R11 H4, R28.1/R18 D1, "
        "R27/R24 W1 secara terpisah. D1 SELL R18 dan W1 masih belum terinferensi: "
        "zona hanya WATCH selama konfirmasi D1/H1 belum lengkap. "
        "Tidak ada auto-order dan bukan replay entry gabungan."
    )

    @st.cache_data(ttl=20, show_spinner=False)
    def load(slot):
        # All sources have independently validated provenance/expiry contracts.
        # No R28.1 H1/H4/W1 fallback when best-side feeds are absent.
        try:
            best=fetch_rbest()
        except (OSError, ValueError, TypeError, KeyError, TimeoutError, OverflowError):
            best={}
        try:
            h4buy=fetch_r294()
        except (OSError, ValueError, TypeError, KeyError, TimeoutError, OverflowError):
            h4buy={}
        try:
            r281=fetch_r281()
        except (OSError, ValueError, TypeError, KeyError, TimeoutError, OverflowError):
            r281={}
        try:
            market=fetch_market()
        except (OSError, ValueError, TypeError, KeyError, TimeoutError, OverflowError):
            market=None
        return best,h4buy,r281,market

    @st.fragment(run_every="30s")
    def panel():
        now=datetime.now(UTC)
        best,h4buy,r281,market=load(int(now.timestamp()//20))
        primary=select_best_candidate_direction(best,h4buy,r281,now=now)
        report=evaluate_best_entry(primary,market,now=now)
        context=report["context"]

        st.markdown("### Kesiapan setup manual")
        c1,c2,c3=st.columns(3)
        c1.metric("Arah pantauan",report["side"])
        c2.metric("Status entry riset",report["status"])
        c3.metric("Konfirmasi H1","SEARAH" if context.get("h1_confirmed") else "WAIT")
        if report.get("watch_only"):
            st.warning("MODE WATCH ONLY · H4 kandidat terbaik valid, tetapi H1 atau D1 "
                       "belum lengkap. Zona boleh dipantau, seluruh level entry/SL/TP ditahan.")
        if context.get("weekly_countertrend"):
            st.warning("W1 berlawanan dengan arah pantauan D1/H1/H4. "
                       "Ini konteks kontra arah mingguan, bukan rekomendasi entry.")
        if context:
            st.dataframe([
                {"Timeframe":tf,"Arah model aktif":context.get(tf,"WAIT")}
                for tf in ("H1","H4","D1","W1")
            ],hide_index=True,width="stretch")
        st.caption("Pemeriksaan: "+_wib(report["checked_at"])+" · sumber arah: kandidat terbaik terverifikasi per sisi, tanpa fallback R28.1 H1/H4/W1.")
        st.dataframe([{"TF":tf, "BUY":primary[tf]["sources"]["BUY"],
                       "SELL":primary[tf]["sources"]["SELL"],
                       "Direction":primary[tf]["direction"],
                       "Status":primary[tf]["status"],
                       "Alasan":primary[tf]["reason"]}
                      for tf in ("H1","H4","D1","W1")],
                     hide_index=True,width="stretch")
        st.write("**Alasan/status:** "+REASONS.get(report["reason"],report["reason"]))
        zone=report.get("zone")
        if zone:
            if report["status"]=="PENDING_INVALIDATION":
                st.error("ZONA PENDING INVALIDATION · harga melewati batas zona. "
                         "Tunggu candle H1/H4 selesai sebelum menyatakan batal atau pulih. "
                         "Dilarang digunakan sebagai referensi entry.")
            st.markdown("### Zona harga hasil rekonstruksi candle cTrader")
            z1,z2,z3=st.columns(3)
            z1.metric("Zona "+zone["timeframe"],f'{zone["low"]:,.2f} – {zone["high"]:,.2f}')
            z2.metric("Batas invalidasi zona",f'{zone["zone_invalidation"]:,.2f}')
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
            st.markdown("### Zona kandidat & checkpoint (bukan izin order)")
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

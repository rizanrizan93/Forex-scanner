"""Independent XAU H1/H4/D1/W1 entry-zone watch dashboard.

Each zone follows only the matching timeframe best-side direction. No
cross-timeframe consensus gate, no executed entry or inferred win-rate.
"""
from __future__ import annotations
from datetime import UTC, datetime
import pandas as pd

from .r281_shadow_feed import fetch as fetch_r281
from .rbest_side_feed import fetch as fetch_rbest
from .r294_frozen_h4_buy_feed import fetch as fetch_r294
from .manual_reversal_dashboard import fetch_manual_map
from .manual_r3_feed import fetch_market
from .manual_precision_shadow import render_precision
from .best_candidate_direction import select as select_best_candidate_direction
from .independent_timeframe_zones import independent_zones, fresh_m1_fallback_packet, TFS


REASONS = {
    "DIRECTION_NOT_VALIDATED_OR_EXPIRED":
        "Model kandidat timeframe ini belum memicu arah valid, parsial tidak valid, atau prediksi kedaluwarsa.",
    "BROKER_ZONE_PACKET_STALE_OR_UNAVAILABLE":
        "Peta harga cTrader belum tersedia atau snapshot sudah kedaluwarsa.",
    "SOURCE_TIMEFRAME_CANDLE_NOT_FRESH":
        "Candle tertutup timeframe ini belum diperbarui. Tidak mengambil zona timeframe lain.",
    "SOURCE_TIMEFRAME_CANDLE_INVALID":
        "Timestamp candle timeframe tidak lolos pemeriksaan freshness.",
    "NO_UNBROKEN_MATCHED_TIMEFRAME_BOS_ZONE":
        "Belum ada zona supply/demand pada timeframe dan arah yang sama dengan BOS, displacement, dan invalidasi valid.",
    "MATCHED_TIMEFRAME_CLOSED_BOS_ZONE":
        "Zona sesuai arah kandidat serta timeframe sumber terverifikasi untuk pantauan.",
}
STATE = {
    "WAIT_DIRECTION": "WAIT DIRECTION",
    "WAIT_DATA": "WAIT DATA",
    "WAIT_ZONE": "WAIT ZONA",
    "WATCH_ZONE": "ZONA PANTAU",
}


def _wib(value):
    return pd.Timestamp(value).tz_convert("Asia/Jakarta").strftime("%d/%m %H:%M WIB") if value else "—"


def render_r281_smc_entry():
    """Keep existing entrypoint so previous page routing remains compatible."""
    import streamlit as st

    st.subheader("XAUUSD · Zona Entry Independen H1/H4/D1/W1")
    st.caption(
        "Setiap timeframe menggunakan model BUY/SELL dan supply/demand miliknya "
        "sendiri: H1 SELL → cari supply SELL H1; H4 BUY → cari demand BUY H4. "
        "Tidak ada veto silang H1/H4/D1/W1. Zona memakai candle cTrader tertutup "
        "dengan base-displacement, structural BOS dan batas invalidasi. "
        "WATCH bukan konfirmasi entry atau otorisasi order."
    )

    @st.cache_data(ttl=20, show_spinner=False)
    def load(slot):
        try:
            best=fetch_rbest()
        except (OSError,ValueError,TypeError,KeyError,TimeoutError,OverflowError):
            best={}
        try:
            h4buy=fetch_r294()
        except (OSError,ValueError,TypeError,KeyError,TimeoutError,OverflowError):
            h4buy={}
        try:
            r281=fetch_r281()
        except (OSError,ValueError,TypeError,KeyError,TimeoutError,OverflowError):
            r281={}
        try:
            snapshot=fetch_manual_map()
        except (OSError,ValueError,TypeError,KeyError,TimeoutError,OverflowError):
            snapshot=None
        if not isinstance(snapshot,dict) or snapshot.get("fresh") is not True:
            # GitHub reversal snapshot may lag behind LIVE M1. Reconstruct
            # only native, fully closed H1/H4; never invent D1/W1 candles.
            try:
                snapshot=fresh_m1_fallback_packet(fetch_market(),now=datetime.now(UTC))
            except (OSError,ValueError,TypeError,KeyError,TimeoutError,OverflowError):
                snapshot=None
        return best,h4buy,r281,snapshot

    @st.cache_data(ttl=10, show_spinner=False)
    def load_precision_market(slot):
        try:
            return fetch_market()
        except (OSError,ValueError,TypeError,KeyError,TimeoutError,OverflowError):
            return None

    @st.fragment(run_every="30s")
    def panel():
        now=datetime.now(UTC)
        if st.button("Perbarui semua zona timeframe",key="independent_tf_zones_refresh"):
            load.clear()
            load_precision_market.clear()
        best,h4buy,r281,snapshot=load(int(now.timestamp()//20))
        primary=select_best_candidate_direction(best,h4buy,r281,now=now)
        zones=independent_zones(primary,snapshot,now=now)
        precision_market = (load_precision_market(int(now.timestamp()//10))
                            if any(zones[tf].get('zones') for tf in ('H1','H4')) else None)
        precision_now = datetime.now(UTC)
        if isinstance(snapshot,dict) and snapshot.get("source_detail")=="VALIDATED_FRESH_M1_REAGGREGATED_H1_H4_ONLY":
            st.info(
                "Sumber zona: cTrader M1 segar, diagregasi menjadi H1/H4 tertutup "
                "secara ketat. D1/W1 memerlukan riwayat candle broker native "
                "yang lebih panjang dan tidak akan ditebak dari M1."
            )
        elif snapshot is None or snapshot.get("fresh") is not True:
            st.warning(
                "Feed zona broker belum segar. Tidak menampilkan harga "
                "dari snapshot historis yang kedaluwarsa."
            )
        st.markdown("### Zona sesuai arah per timeframe")
        for tf in TFS:
            model=primary[tf]
            row=zones[tf]
            side=row["direction"]
            with st.container(border=True):
                st.markdown("#### "+tf+" · "+("BUY THE DIP" if side=="BUY"
                                            else "SELL ON REBOUND" if side=="SELL"
                                            else "MENUNGGU ARAH"))
                a,b=st.columns(2)
                a.metric("Direction "+tf,side)
                b.metric("Status zona",STATE.get(row["state"],row["state"]))
                st.caption("Kandidat BUY "+row["models"]["BUY"]+
                           " · SELL "+row["models"]["SELL"]+
                           " · status model: "+model["status"])
                st.write(REASONS.get(row["reason"],row["reason"]))
                if row["target"]:
                    st.caption("Prediksi berlaku hingga: "+_wib(row["target"]))
                if row["source_closed_at"]:
                    st.caption("Candle sumber "+tf+" tertutup: "+_wib(row["source_closed_at"]))
                if row["zones"]:
                    for i,zone in enumerate(row["zones"]):
                        st.markdown("**Zona "+("utama" if i==0 else "cadangan")+
                                    " · "+tf+" "+side+"**")
                        c1,c2,c3=st.columns(3)
                        c1.metric("Area harga",f'{zone["low"]:,.2f} – {zone["high"]:,.2f}')
                        c2.metric("Invalidasi zona",f'{zone["invalidation"]:,.2f}')
                        c3.metric("Jarak dari harga",f'{zone["distance"]:,.2f}')
                        st.caption(
                            "Asal zona: "+_wib(zone["formed_at"])+
                            " · jumlah retest: "+str(zone["touch_count"])+
                            " · "+("Harga di zona" if zone["status"]=="IN_ZONE_WAIT_CONFIRMATION"
                                    else "Menunggu rebound menuju supply" if side=="SELL"
                                    else "Menunggu pullback menuju demand")
                        )
                    st.info(
                        "ZONA PANTAU · tunggu reaksi/rejection M15 dan perubahan struktur "
                        "(BOS/MSS) pada M5 sebelum mempertimbangkan entry manual. "
                        "Invalidasi di atas adalah batas struktur zona, bukan SL order."
                    )
                    if model["status"]=="PARTIAL_HEAD":
                        st.warning(
                            "D1 parsial: model SELL independen belum terverifikasi. "
                            "Zona hanya referensi riset, tanpa izin entry."
                        )
                else:
                    st.info("Belum ada area harga yang lolos untuk timeframe ini. "
                            "Zona dari timeframe lain tidak menggantikannya.")
                if tf in ('H1','H4'):
                    render_precision(st,row,model,precision_market,now=precision_now)

        st.caption(
            "Evaluasi "+_wib(now)+" · zona tidak mengubah Frozen V1/cBot LIVE. "
            "Tidak ada entry/SL/TP executable atau klaim akurasi rebound terkalibrasi."
        )
    panel()

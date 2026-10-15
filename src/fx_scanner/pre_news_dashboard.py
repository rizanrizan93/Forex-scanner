"""Mobile-friendly, display-only Pre-News panel with 60-second refresh."""
from datetime import UTC, datetime

from .pre_news_expectation import evaluate_pre_news


def render_pre_news_dashboard():
    import streamlit as st
    from .xau_turso_hot_snapshot_v407 import fetch_public_hot_snapshot

    @st.cache_data(ttl=60, show_spinner=False)
    def load_snapshot():
        return fetch_public_hot_snapshot()

    @st.fragment(run_every="60s")
    def panel():
        st.subheader("Pre-News Expectation Engine · XAUUSD")
        st.caption("CPI · NFP/upah/pengangguran · PPI · JOLTS · ECI · FOMC")
        try:
            snapshot = load_snapshot()
        except Exception as exc:
            st.warning("DATA INCOMPLETE · snapshot belum tersedia (" + type(exc).__name__ + ").")
            return
        view = evaluate_pre_news(snapshot, now=datetime.now(UTC))
        cols = st.columns(2)
        cols[0].metric("Status", view["state"])
        cols[1].metric("Ekspektasi konsensus", view["expectation"])
        cols = st.columns(2)
        cols[0].metric("Bias XAU", view["xau_bias"])
        cols[1].metric("Keselarasan bukti", view["conviction"])
        st.caption("COOL/HOT-RISK = konsensus dibanding angka sebelumnya; bukan prediksi surprise. Keselarasan bukti bukan probabilitas menang.")
        event = view.get("event")
        if event:
            st.write(str(event.get("title")) + " · " + str(view["event_time_wib"]) + " WIB")
            st.caption("Sumber kalender: " + str(event.get("source") or "Belum tersedia") + " · " + str(event.get("source_tier") or "Belum terverifikasi"))
            st.metric("Menuju rilis", f'{view["minutes_to_event"]:,.1f} menit')
            st.dataframe(view["event_cluster"], hide_index=True, width="stretch")
        st.write("News gate scanner: " + view["news_gate"] + " · " + view["news_gate_action"])
        if view["reasons"]:
            st.warning(" · ".join(view["reasons"]))
        if view["components"]:
            with st.expander("Kesegaran dan sumber makro", expanded=view["state"] == "DATA INCOMPLETE"):
                st.dataframe(view["components"], hide_index=True, width="stretch")
                st.caption("Kalender: " + str(view["calendar_observed_at"]) + " · Makro: " + str(view["macro_observed_at"]))
        if view["scenarios"]:
            with st.expander("Skenario setelah rilis"):
                st.dataframe(view["scenarios"], hide_index=True, width="stretch")
                st.caption("Skenario bersifat kondisional. Revisi, core/headline, forward guidance dan respons pasar dapat mengubah implikasi awal.")
        st.caption(view.get("next_step", "H1 bias → M15 validasi struktur/reversal → M5 timing."))
        st.caption("Modul informasi · tidak memberi izin order · probabilitas historis belum dikalibrasi.")
    panel()

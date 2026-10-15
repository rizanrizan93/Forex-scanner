"""Mobile-friendly, display-only Pre-News panel with 60-second refresh."""
from datetime import UTC, datetime

from .pre_news_expectation import evaluate_pre_news, timestamp
from zoneinfo import ZoneInfo


def _wib(value):
    at = timestamp(value)
    return at.astimezone(ZoneInfo("Asia/Jakarta")).strftime("%d-%m %H:%M:%S WIB") if at else "Belum tersedia"


def _reason(value):
    labels = {
        "PUBLICATION_STALE": "Pembaruan feed terlambat; bias ditahan sampai data baru diterima",
        "DXY_PROVIDER_RATE_LIMITED": "Sumber DXY membatasi permintaan (HTTP 429); bias menunggu data segar",
        "DXY_STALE_OR_MISSING": "DXY intraday belum tersedia atau sudah kedaluwarsa",
        "CALENDAR_STALE_MISSING_OR_UNHEALTHY": "Feed kalender belum segar/sehat",
        "MACRO_STALE_MISSING_OR_UNHEALTHY": "Feed makro belum segar/sehat",
        "NO_UPCOMING_SUPPORTED_EVENT_IN_CALENDAR": "Belum ada event mendatang yang sesuai di kalender",
        "CONSENSUS_MACRO_DIVERGENCE": "Ekspektasi konsensus dan tekanan makro berlawanan",
        "FOMC_LANGUAGE_AND_RATE_PATH_UNMODELED": "FOMC: arahan kebijakan dan konferensi pers belum tercakup",
    }
    return labels.get(value, value)


def render_pre_news_dashboard():
    import streamlit as st
    from .pre_news_transport import fetch_pre_news_snapshot

    @st.cache_data(ttl=60, show_spinner=False)
    def load_snapshot():
        return fetch_pre_news_snapshot()

    @st.fragment(run_every="60s")
    def panel():
        st.subheader("Pre-News Expectation Engine · XAUUSD")
        st.caption("CPI · NFP/upah/pengangguran · PPI · JOLTS · ECI · FOMC")
        if st.button("Perbarui tampilan", key="pre_news_refresh"):
            load_snapshot.clear()
        st.caption("Panel diperiksa setiap 60 detik · sumber diperbarui sekitar 4 menit selama publisher aktif.")
        try:
            snapshot = load_snapshot()
            st.session_state["pre_news_last_snapshot"] = snapshot
        except Exception:
            previous = st.session_state.get("pre_news_last_snapshot")
            if not previous:
                st.warning("DATA INCOMPLETE · feed belum dapat dihubungi. Panel mencoba kembali setiap 60 detik.")
                return
            snapshot = {**previous, "publication_fresh": False}
            st.warning("Koneksi feed terganggu. Menampilkan data terakhir sebagai referensi; bias ditahan.")
        view = evaluate_pre_news(snapshot, now=datetime.now(UTC))
        if snapshot.get("published_at"):
            st.caption("Feed terakhir: " + _wib(snapshot["published_at"]))
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
            st.warning(" · ".join(_reason(reason) for reason in view["reasons"]))
        st.caption("Kalender: " + _wib(view["calendar_observed_at"]) + " · Makro: " + _wib(view["macro_observed_at"]))
        dxy = next((row for row in view["components"] if row["name"] == "DXY"), {})
        if dxy.get("fresh") and dxy.get("current") is not None:
            st.metric("Dollar Index · " + str(dxy.get("source")), f'{dxy["current"]:.3f}', delta=f'{dxy["delta"]:+.3f}% dari referensi')
            if str(dxy.get("source") or "").startswith("CTRADER_"):
                st.caption("Proxy dari harga broker; candle M5 tertutup. Bukan feed resmi ICE. Indeks sintetis memakai seluruh enam mata uang pada timestamp yang sama.")
        if view["components"]:
            with st.expander("Kesegaran dan sumber makro", expanded=view["state"] == "DATA INCOMPLETE"):
                st.dataframe(view["components"], hide_index=True, width="stretch")
        if view["scenarios"]:
            with st.expander("Skenario setelah rilis"):
                st.dataframe(view["scenarios"], hide_index=True, width="stretch")
                st.caption("Skenario bersifat kondisional. Revisi, core/headline, forward guidance dan respons pasar dapat mengubah implikasi awal.")
        st.caption(view.get("next_step", "H1 bias → M15 validasi struktur/reversal → M5 timing."))
        st.caption("Modul informasi · tidak memberi izin order · probabilitas historis belum dikalibrasi.")
    panel()

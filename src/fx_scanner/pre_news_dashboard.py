"""Mobile-friendly, display-only Pre-News panel with 60-second refresh."""
from datetime import UTC, datetime

from .pre_news_expectation import evaluate_pre_news, timestamp, MIN_FORECAST_SOURCES
from .pre_news_entry_guidance import evaluate_entry_guidance
from .pre_news_source_fusion import (
    SOURCE_FOREX_FACTORY, SOURCE_MYFXBOOK, SOURCE_INVESTING,
    SOURCE_SHOWMYTRADES, SOURCE_HELIOUS, SOURCE_TRADING_ECONOMICS,
)
from zoneinfo import ZoneInfo

FORECAST_SOURCES = (
    SOURCE_FOREX_FACTORY,
    SOURCE_SHOWMYTRADES,
    SOURCE_HELIOUS,
    SOURCE_INVESTING,
    SOURCE_MYFXBOOK,
    SOURCE_TRADING_ECONOMICS,
)
SOURCE_LABELS = {
    SOURCE_FOREX_FACTORY: "Forex Factory",
    SOURCE_SHOWMYTRADES: "ShowMyTrades",
    SOURCE_HELIOUS: "Helious (delay)",
    SOURCE_INVESTING: "Investing.com",
    SOURCE_MYFXBOOK: "Myfxbook",
    SOURCE_TRADING_ECONOMICS: "Trading Economics (licensed)",
}


def _wib(value):
    at = timestamp(value)
    return at.astimezone(ZoneInfo("Asia/Jakarta")).strftime("%d-%m %H:%M:%S WIB") if at else "Belum tersedia"

def _countdown(minutes):
    if minutes is None:
        return "Belum tersedia"
    whole = max(0, round(float(minutes)))
    days, remaining = divmod(whole, 1440)
    hours, mins = divmod(remaining, 60)
    return (f"{days} hari " if days else "") + f"{hours} jam {mins} menit"


def _reason(value):
    if str(value).startswith("FORECAST_QUORUM:"):
        _, title, count = str(value).split(":", 2)
        return f"{title}: forecast valid baru {count}; minimal 3 sumber independen"
    labels = {
        "PUBLICATION_STALE": "Pembaruan feed terlambat; bias ditahan sampai data baru diterima",
        "DXY_PROVIDER_RATE_LIMITED": "Sumber DXY membatasi permintaan (HTTP 429); bias menunggu data segar",
        "DXY_STALE_OR_MISSING": "DXY intraday belum tersedia atau sudah kedaluwarsa",
        "CALENDAR_STALE_MISSING_OR_UNHEALTHY": "Feed kalender belum segar/sehat",
        "MACRO_STALE_MISSING_OR_UNHEALTHY": "Feed makro belum segar/sehat",
        "NO_UPCOMING_SUPPORTED_EVENT_IN_CALENDAR": "Belum ada event mendatang yang sesuai di kalender",
        "UNIT_MISMATCH_EVENT": "Nilai indeks CPI terdeteksi pada kolom persentase; bias ditahan",
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
        st.subheader("News Entry Guidance · XAUUSD")
        st.caption("CPI · PPI · NFP · Initial/Continuing Jobless Claims · Existing Home Sales · JOLTS · FOMC")
        st.caption("Tiga tahap terpisah: bias pra-rilis, kejutan actual, lalu konfirmasi entry M1/M5.")
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
            published_at = timestamp(snapshot["published_at"])
            publication_age = ((datetime.now(UTC) - published_at).total_seconds()
                               if published_at else float("inf"))
            if not 0 <= publication_age <= 900 or snapshot.get("publication_fresh") is False:
                st.warning("SNAPSHOT PRE-NEWS TERLAMBAT (>15 menit). Semua panduan entry ditahan sampai feed pulih.")
        guidance = evaluate_entry_guidance(view, snapshot, now=datetime.now(UTC))
        st.markdown("#### 1. Sebelum rilis · bias makro, bukan prediksi actual")
        st.metric("PANDUAN ARAH ENTRY NEWS", guidance["decision"])
        st.caption("Klasifikasi hot/cool: " + guidance["hot_cool_risk"])
        stats = st.columns(2)
        stats[0].metric(
            "Skor arah XAU (-100 bearish, +100 bullish)",
            "—" if guidance["score_xau"] is None
            else f'{guidance["score_xau"]:+.1f}/100',
        )
        stats[1].metric("Keyakinan analisis", guidance["confidence"])
        st.caption(guidance["reason"])
        if guidance["release_triggers"]:
            with st.expander("Skenario actual vs forecast (HOT / COOL)", expanded=False):
                st.dataframe(guidance["release_triggers"], hide_index=True, width="stretch")
                st.caption(
                    "CPI/PPI: selisih 0,1pp hanya ambang skenario. "
                    "Jobless Claims: lebih sedikit klaim dari forecast cenderung bearish XAU; "
                    "lebih banyak klaim cenderung bullish XAU. "
                    "Existing Home Sales: lebih tinggi dari forecast cenderung bearish XAU; "
                    "lebih rendah cenderung bullish XAU. "
                    "Semua reaksi tetap kondisional, bukan kepastian spike."
                )
        # A forecast below Previous does NOT predict Actual below consensus.
        # Keep a separate, explicitly conditional pre-release macro-risk headline.
        st.markdown("#### 2. Saat rilis · hasil aktual dibanding konsensus")
        conclusion = view["news_conclusion"]
        if view["state"] == "PRE_NEWS":
            fresh_pressure = [
                row.get("hawkish_pressure")
                for row in view.get("components") or []
                if row.get("fresh") and row.get("name") in {"DXY", "US2Y", "US10Y"}
            ]
            if fresh_pressure.count(1) >= 2 and fresh_pressure.count(-1) == 0:
                conclusion = "RISIKO BEARISH XAU (MAKRO) — ACTUAL BELUM DIRILIS"
            elif fresh_pressure.count(-1) >= 2 and fresh_pressure.count(1) == 0:
                conclusion = "RISIKO BULLISH XAU (MAKRO) — ACTUAL BELUM DIRILIS"
            else:
                conclusion = "PRA-RILIS — ARAH SPIKE BELUM TERVERIFIKASI"
        if view["state"].startswith("POST_NEWS"):
            st.metric("HASIL RILIS EKONOMI", conclusion)
            st.caption(view["news_conclusion_basis"])
            st.caption("MODE PASCA-RILIS: actual vs forecast; cek status OFFICIAL/MULTI_SOURCE sebelum entry.")
        else:
            st.caption("Konteks konsensus (bukan panduan entry): " + conclusion)
            st.caption(view["news_conclusion_basis"])
            st.caption("MODE PRA-RILIS: forecast-vs-previous hanya ekspektasi perubahan "
                       "indikator ekonomi, bukan prediksi actual hot/cool.")
        st.caption(
            "VALIDATED = semua komponen sudah memenuhi 3 forecast independen. "
            "INDIKASI SEMENTARA = sebagian komponen hanya memiliki 2 sumber "
            "atau masih ada komponen yang belum tervalidasi; bukan izin entry."
        )
        st.caption("Diagnostik forecast konsensus: " + str(view["forecast_risk"]))
        st.caption(
            "HOT/COOL pada forecast hanya mengukur estimasi perubahan dari Previous. "
            "Panduan BUY/SELL/WAIT dihitung terpisah memakai kondisi makro; "
            "sesudah rilis memakai actual-vs-forecast. Quorum numerik minimal 3 sumber "
            "per komponen tetap dipantau."
        )
        cols = st.columns(2)
        cols[0].metric("Status validasi makro", view["state"])
        cols[1].metric("Ekspektasi terkonfirmasi", view["expectation"])
        cols = st.columns(2)
        cols[0].metric(
            "Bias XAU dari actual resmi" if view["state"] == "POST_NEWS"
            else "Bias XAU setelah konfirmasi makro", view["xau_bias"]
        )
        cols[1].metric("Keselarasan bukti", view["conviction"])
        # The attribution worker is a DIFFERENT scoring model from the Macro
        # tab's signed -100..+100 intraday composite. Display both honestly.
        attribution_rows = [
            row for row in (snapshot.get("heartbeats") or [])
            if row.get("worker_name") == "ctrader_demo_xau_macro_attribution_v357"
        ]
        if attribution_rows:
            worker = max(attribution_rows, key=lambda row: str(row.get("observed_at") or ""))
            evaluation = (worker.get("details") or {}).get("evaluation") or {}
            score = evaluation.get("macro_score")
            at = timestamp(worker.get("observed_at"))
            age = (datetime.now(UTC) - at).total_seconds() if at else float("inf")
            active = bool(worker.get("healthy")) and 0 <= age <= 600
            try:
                text_score = f"{float(score):.2f}/100" if score is not None else "—"
            except (ValueError, TypeError, OverflowError):
                text_score = "—"
            if text_score != "—":
                st.metric("Engine attribution Treasury/DXY · skala 0–100",
                          text_score + ("" if active else " (historis)"))
                st.caption("Berbeda dari Indeks arah makro pada tab Makro (skala −100 sampai +100). "
                           "Skor attribution bukan probabilitas hasil CPI atau kenaikan emas. "
                           + ("Feed attribution segar." if active else "Heartbeat attribution sudah terlambat."))
        excluded = view.get("unpublished_components") or []
        if excluded:
            st.info(
                "BLS: headline/core CPI YoY Oktober 2026 tidak diterbitkan "
                "karena indeks Oktober 2025 tidak tersedia. "
                "Dikeluarkan dari perhitungan hot/cool: " + ", ".join(excluded) +
                ". Yang dihitung adalah komponen CPI MoM yang memang dirilis."
            )
        st.caption("Makro DXY/US2Y/US10Y/real yield menjadi konfirmasi terpisah. Jika belum segar, bias makro ditahan; forecast 3 sumber tetap terlihat sebagai skenario pra-rilis.")
        status_map = view.get("calendar_source_status") or {}
        online = sum(
            str(status_map.get(source) or "").startswith("OK:")
            for source in FORECAST_SOURCES
        )
        st.caption(
            f"Status koneksi penyedia: {online}/{len(FORECAST_SOURCES)} aktif. "
            "Angka ini bukan jumlah forecast yang cocok untuk event terpilih."
        )
        if "BLS_CPI_RELEASE" in status_map:
            st.caption("BLS CPI aktual: " + str(status_map["BLS_CPI_RELEASE"]))
        with st.expander("Status keenam penyedia forecast"):
            st.dataframe(
                [{
                    "Sumber": SOURCE_LABELS[source],
                    "Status": status_map.get(source, "TIDAK TERSEDIA"),
                } for source in FORECAST_SOURCES],
                hide_index=True, width="stretch",
            )
        event = view.get("event")
        if event:
            st.write(str(event.get("title")) + " · " + str(view["event_time_wib"]) + " WIB")
            st.caption("Sumber kalender: " + str(event.get("source") or "Belum tersedia") + " · " + str(event.get("source_tier") or "Belum terverifikasi"))
            if view["minutes_to_event"] is not None and view["minutes_to_event"] < 0:
                st.metric("Rilis telah berlalu", f'{abs(view["minutes_to_event"]):,.1f} menit')
            else:
                st.metric("Menuju rilis", _countdown(view["minutes_to_event"]))
                st.caption(f'{view["minutes_to_event"]:,.1f} menit hingga rilis resmi (WIB)')
            cluster = view["event_cluster"]
            if cluster and view["state"] == "POST_NEWS":
                st.markdown("**Perbandingan actual dan forecast pra-rilis (periksa status verifikasi)**")
                st.dataframe(
                    [{
                        "Komponen": row.get("event_component") or row.get("title"),
                        "Actual": row.get("actual"),
                        "Forecast": row.get("forecast"),
                        "Surprise (satuan asli)": row.get("surprise"),
                        "Sumber aktual": row.get("source"),
                    } for row in cluster],
                    hide_index=True, width="stretch",
                )
                st.caption("Actual resmi menunjukkan outcome rilis, bukan "
                           "rekonstruksi prediksi sebelum news.")
            if cluster and view["state"] != "POST_NEWS":
                min_count = min(int(row.get("forecast_pair_count") or 0) for row in cluster)
                st.metric(
                    "Quorum forecast+previous per komponen",
                    f"{min_count}/{MIN_FORECAST_SOURCES}",
                )
                st.dataframe(
                    [{
                        "Komponen": row.get("event_component") or row.get("title"),
                        "Forecast konsensus": row.get("forecast"),
                        "Previous": row.get("previous"),
                        "Forecast numerik": row.get("forecast_source_count"),
                        "Pasangan valid": row.get("forecast_pair_count"),
                        "Sumber dikarantina": ", ".join(row.get("rejected_quote_sources") or []),
                        "Perbedaan sumber": row.get("source_agreement"),
                    } for row in cluster],
                    hide_index=True, width="stretch",
                )
                quarantined = [
                    f'{item.get("event_component") or item.get("title")}: ' +
                    ", ".join(item.get("rejected_quote_sources") or [])
                    for item in cluster if item.get("rejected_quote_sources")
                ]
                if quarantined:
                    st.warning(
                        "Validasi satuan: forecast indeks yang salah dipetakan " +
                        "dikarantina (tidak dihitung sebagai persentase). " +
                        " · ".join(quarantined)
                    )
                provider_rows = []
                status_map = view.get("calendar_source_status") or {}
                for item in cluster:
                    quotes = {
                        quote["source"]: quote
                        for quote in item.get("forecast_quotes") or []
                        if isinstance(quote, dict) and quote.get("source")
                    }
                    for source in FORECAST_SOURCES:
                        quote = quotes.get(source) or {}
                        provider_rows.append({
                            "Komponen": item.get("event_component") or item.get("title"),
                            "Sumber": SOURCE_LABELS[source],
                            "Forecast": quote.get("forecast"),
                            "Previous": quote.get("previous"),
                            "Status feed": status_map.get(source, "BELUM TERSEDIA"),
                            "Verifikasi": (
                                "KARANTINA UNIT" if source in (item.get("rejected_quote_sources") or []) and quote.get("forecast") is None
                                else "VALID" if quote.get("forecast") is not None and quote.get("previous") is not None
                                else "PARTIAL" if quote.get("forecast") is not None else "MISSING"
                            ),
                        })
                st.markdown("**Perbandingan forecast dari hingga 6 sumber**")
                st.dataframe(provider_rows, hide_index=True, width="stretch")
                st.caption(
                    "Sumber: Forex Factory, ShowMyTrades, Helious, Investing.com, "
                    "Myfxbook, Trading Economics (opsional/berlisensi). "
                    "Provider dengan status error/nonaktif atau forecast kosong tidak dihitung. "
                    "Konflik angka antar-provider → kesimpulan arah ditahan. "
                    "Beberapa penyedia dapat menggunakan konsensus hulu yang sama; "
                    "jumlah vendor bukan bukti survei ekonom yang independen."
                )
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
        st.markdown("#### 3. Eksekusi manual · BUY / SELL / WAIT")
        st.caption("Selalu WAIT bila feed/actual tidak tervalidasi. Konfirmasi M1/M5, DXY, yield dan spread diperlukan.")
        st.markdown("**Pemicu entry:** " + guidance["trigger"])
        st.caption("Invalidasi: " + guidance["invalidated_by"])
        if guidance["warnings"]:
            st.info(" · ".join(guidance["warnings"]))
        if guidance["evidence"]:
            with st.expander("Rincian kontribusi makro/news"):
                st.dataframe(guidance["evidence"], hide_index=True, width="stretch")
        st.caption(
            "Panduan analitis bagi keputusan manual, bukan instruksi eksekusi otomatis. "
            "Skor -100 hingga +100 adalah heuristik arah, bukan win-rate "
            "atau probabilitas. M1/M5, spread dan quote harus dikonfirmasi "
            "secara independen saat news."
        )
        st.caption(view.get("next_step", "H1 bias → M15 validasi struktur/reversal → M5 timing."))
        st.caption(
            "Panduan entry bersyarat · tidak mengirim order cBot LIVE · "
            "akurasi arah 1–2 menit belum dikalibrasi secara historis."
        )
    panel()

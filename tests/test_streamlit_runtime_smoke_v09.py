from pathlib import Path

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]


def test_streamlit_app_boots_offline_without_backend_secrets():
    app = AppTest.from_file(
        ROOT / "main.py",
        default_timeout=10,
    ).run()
    assert not app.exception
    assert app.title
    assert app.title[0].value == "RIZAN XAU Institutional Scanner"
    assert any(
        "Dashboard can be deployed now" in element.value
        for element in app.info
    )


def test_streamlit_dashboard_refresh_contract_is_15_seconds():
    text = (ROOT / "streamlit_app.py").read_text()
    assert '@st.cache_data(ttl=15, show_spinner=False)' in text
    assert '@st.fragment(run_every="15s")' in text
    assert '(now - last).total_seconds() >= 14.5' in text
    assert 'Refresh the read-only dashboard every 15 seconds.' in text
    assert 'run_every="5s"' not in text
    assert 'ttl=2' not in text


def test_xau_forecast_surfaces_cross_engine_signal_status_and_geometry():
    text = (ROOT / "streamlit_app.py").read_text()
    assert 'Cross-engine XAU technical signals' in text
    assert 'runtime_status' in text
    assert '"CURRENT"' in text
    assert '"EXPIRED"' in text
    assert '"SL": _fmt_price(row.get("sl"))' in text
    assert '"target pertama"' in text
    assert '"target terminal"' in text
    assert '"raw TP1"' in text
    assert '"raw TP2"' in text
    assert 'izin RIZAN-style tetap merupakan gerbang terpisah' in text


def test_xau_dashboard_distinguishes_prior_origin_revisit_and_target_semantics():
    text = (ROOT / "streamlit_app.py").read_text()
    assert 'PRIOR ORIGIN REVISIT' in text
    assert 'not the current primary RIZAN-style zone' in text
    assert '"target pertama"' in text
    assert '"target terminal"' in text
    assert '"raw TP1"' in text
    assert '"raw TP2"' in text


def test_xau_dashboard_does_not_label_raw_h4_direction_as_trade_forecast():
    text = (ROOT / "streamlit_app.py").read_text()
    assert 'f1.metric("H4 continuation", direction)' in text
    assert 'H4 continuation is structural context only' in text
    assert 'f1.metric("Forecast", direction)' not in text


def test_xau_dashboard_runtime_status_distinguishes_watch_and_invalidated():
    text = (ROOT / "streamlit_app.py").read_text()
    assert 'runtime_status = "INVALIDATED"' in text
    assert 'runtime_status = "WATCH"' in text
    assert 'Baris XAU non-RIZAN-style terbaru hanya WATCH' in text
    assert 'Setup XAU non-RIZAN-style terbaru INVALIDATED' in text


def test_xau_dashboard_separates_shadow_ready_from_broker_eligible():
    text = (ROOT / "streamlit_app.py").read_text()
    assert 'XAU Execution Admission' in text
    assert '"BROKER ELIGIBLE"' in text
    assert '"SHADOW READY"' in text
    assert 'authorized_geometry_codes' in text
    assert '"XAU_AFIC_PATH_EXECUTION_V1"' in text
    assert 'menunggu validasi ulang quote/risiko' in text
    assert 'dapat berstatus EXECUTION_READY di storage' in text


def test_xau_dashboard_shows_stable_zone_touch_lifecycle():
    text = (ROOT / "streamlit_app.py").read_text()
    assert '"touch lifecycle": item.get("touch_lifecycle")' in text
    assert '"zone lifecycle": item.get("zone_lifecycle")' in text
    assert '"first durable touch": item.get("first_touch_at")' in text
    assert '"current-map touch": item.get("map_first_touch_at")' in text
    assert '"live touch": item.get("live_touch_at")' in text
    assert '"invalidated": item.get("invalidated_at")' in text
    assert 'Live touch is provisional until that M15 candle closes' in text
    assert 'Only completed M15 touches are durable lifecycle evidence' in text


def test_xau_dashboard_prefers_live_v170_20k_and_separates_reference_100k():
    text = (ROOT / "streamlit_app.py").read_text()
    assert 'LIVE 20K expected-move envelope from the latest V171 cycle' in text
    assert 'LIVE anchor' in text
    assert 'LIVE as-of' in text
    assert 'REFERENCE 100K V170 snapshot' in text
    assert 'Reference anchor' in text
    assert 'showing the slower REFERENCE 100K snapshot instead' in text
    assert 'live_envelope = dict(ensemble_components.get("v170") or {})' in text


def test_xau_dashboard_shows_prepared_plan_lifecycle_and_cancel_reason():
    text = (ROOT / "streamlit_app.py").read_text()
    assert '"xau_prepared_plan_lifecycle": list(reader.latest_xau_prepared_plan_lifecycle())' in text
    assert 'Prepared Plan Lifecycle' in text
    assert 'Rencana persiapan terakhir:' in text
    assert '"alasan batal": row.get("cancel_reason") or "—"' in text
    assert 'Kandidat TP2 pasca-batal' in text
    assert 'Pembatalan disimpan sebagai evidence, bukan dihapus.' in text


def test_xau_dashboard_grade_b_matches_current_demo_authority():
    text = (ROOT / "streamlit_app.py").read_text()
    assert 'if grade in {"A", "B"}:' in text
    assert 'eligible for DEMO auto execution' in text
    assert 'elif grade == "C":' in text
    assert 'Grade C: shadow/watch only' in text


def test_xau_dashboard_splits_active_and_post_cancel_zone_reach():
    text = (ROOT / "streamlit_app.py").read_text()
    assert '"Zona tercapai saat aktif"' in text
    assert '"Zona tercapai pasca-batal"' in text
    assert '"touch saat aktif": meta.get("touch_while_active")' in text
    assert '"touch pasca-batal": meta.get("post_cancel_touch")' in text
    assert "Zona tercapai saat aktif hanya menghitung sentuhan ketika rencana masih valid." in text


def test_xau_dashboard_shows_strategic_htf_regime_and_zone_age_pools():
    text = (ROOT / "streamlit_app.py").read_text()
    assert '"ctrader_xau_htf_strategic_regime_v180"' in text
    assert 'Strategic HTF Regime' in text
    assert '"Bias Strategis (Strategic Bias)"' in text
    assert '"Gerak Taktis Pertama (Tactical First Leg)"' in text
    assert '"Zona canonical 0–24j"' in text
    assert '"Zona shadow 24–48j"' in text
    assert 'Zona shadow 24–48 jam TIDAK memiliki izin eksekusi.' in text


def test_xau_dashboard_shows_premap_prepare_only_panel_in_indonesian():
    text = (ROOT / "streamlit_app.py").read_text()
    assert '"ctrader_demo_xau_premap_candidate_v181"' in text
    assert 'Kandidat Zona Pra-H4 (Pre-map Candidate Zone)' in text
    assert 'PERSIAPAN SAJA / NO EXECUTION' in text
    assert 'V175 P(touch) OOS' in text
    assert 'V177 hold OOS' in text
    assert 'V178 hold M5 OOS' in text
    assert 'V179 reaction OOS' in text
    assert 'Izin eksekusi", "TIDAK ADA"' in text


def test_xau_dashboard_core_terms_are_localized_with_explanations():
    text = (ROOT / "streamlit_app.py").read_text()
    assert 'Prakiraan XAUUSD & Zona Reaksi (XAUUSD Forecast & Reaction Zone)' in text
    assert 'Persiapan Trading (Trade Preparation)' in text
    assert 'Kelayakan Eksekusi XAU (XAU Execution Admission)' in text
    assert 'Sinyal Teknikal XAU Lintas-Mesin (Cross-engine XAU technical signals)' in text
    assert 'Diagnostik Zona Reaksi (Reaction-zone diagnostics)' in text
    assert 'Kamus istilah pada halaman ini' in text
    assert 'Liquidity / Likuiditas' in text
    assert 'BOS (Break of Structure)' in text


def test_xau_operational_labels_are_indonesian_while_machine_states_remain_auditable():
    text = (ROOT / "streamlit_app.py").read_text()
    assert 'Bias Strategis (Strategic Bias)' in text
    assert 'Gerak Taktis Pertama (Tactical First Leg)' in text
    assert 'Menunggu", "H4 MAP BARU"' in text
    assert '"Zona tercapai saat aktif"' in text
    assert '"kelayakan": admission' in text
    assert '"izin geometry": geometry_code or "—"' in text
    assert '"target pertama"' in text
    assert '"target terminal"' in text
    assert '"BROKER ELIGIBLE"' in text
    assert '"SHADOW READY"' in text


def test_dashboard_trading_times_are_explicitly_wib():
    text = (ROOT / "streamlit_app.py").read_text()
    assert 'WIB = ZoneInfo("Asia/Jakarta")' in text
    assert '%d-%m-%Y %H:%M:%S WIB' in text
    assert 'Semua waktu trading yang ditampilkan menggunakan WIB (Asia/Jakarta, UTC+7)' in text
    assert '"kedaluwarsa (WIB)"' in text
    assert '"map H4 (WIB)"' in text
    assert '"opened_at (WIB)"' in text
    assert '"expires_at (WIB)"' in text
    assert 'runtime internal tetap UTC' in text


def test_signal_expiry_status_still_uses_absolute_utc_time():
    text = (ROOT / "streamlit_app.py").read_text()
    assert 'admission_now = datetime.now(tz=UTC)' in text
    assert 'expires_dt = expires_dt.astimezone(UTC)' in text
    assert 'expires_dt < admission_now' in text
    assert 'now_utc = datetime.now(tz=UTC)' in text
    assert 'expires_dt < now_utc' in text

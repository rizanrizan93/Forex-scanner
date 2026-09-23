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
    assert app.title[0].value == "FX Institutional Scanner"
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
    assert '"first target"' in text
    assert '"terminal target"' in text
    assert '"raw TP1"' in text
    assert '"raw TP2"' in text
    assert 'AFIC authority remains a separate gate' in text


def test_xau_dashboard_distinguishes_prior_origin_revisit_and_target_semantics():
    text = (ROOT / "streamlit_app.py").read_text()
    assert 'PRIOR ORIGIN REVISIT' in text
    assert 'not the current primary AFIC zone' in text
    assert '"first target"' in text
    assert '"terminal target"' in text
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
    assert 'Latest non-AFIC XAU row is WATCH only' in text
    assert 'Latest non-AFIC XAU setup is INVALIDATED' in text


def test_xau_dashboard_separates_shadow_ready_from_broker_eligible():
    text = (ROOT / "streamlit_app.py").read_text()
    assert 'XAU Execution Admission' in text
    assert '"BROKER ELIGIBLE"' in text
    assert '"SHADOW READY"' in text
    assert 'authorized_geometry_codes' in text
    assert '"XAU_AFIC_PATH_EXECUTION_V1"' in text
    assert 'pending live revalidation' in text
    assert 'may say EXECUTION_READY in storage but is SHADOW READY only' in text


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
    assert '"xau_prepared_plan_lifecycle": list(snapshot.xau_prepared_plan_lifecycle)' in text
    assert 'Prepared Plan Lifecycle' in text
    assert 'Last prepared plan:' in text
    assert '"cancel reason": row.get("cancel_reason") or "—"' in text
    assert 'Post-cancel TP2 candidate' in text
    assert 'Pembatalan disimpan sebagai evidence, bukan dihapus.' in text


def test_xau_dashboard_grade_b_matches_current_demo_authority():
    text = (ROOT / "streamlit_app.py").read_text()
    assert 'if grade in {"A", "B"}:' in text
    assert 'eligible for DEMO auto execution' in text
    assert 'elif grade == "C":' in text
    assert 'Grade C: shadow/watch only' in text


def test_xau_dashboard_splits_active_and_post_cancel_zone_reach():
    text = (ROOT / "streamlit_app.py").read_text()
    assert '"Active zone reach"' in text
    assert '"Post-cancel zone reach"' in text
    assert '"touch while active": meta.get("touch_while_active")' in text
    assert '"post-cancel touch": meta.get("post_cancel_touch")' in text
    assert "Active zone reach counts only touches while the prepared plan was still valid." in text


def test_xau_dashboard_shows_strategic_htf_regime_and_zone_age_pools():
    text = (ROOT / "streamlit_app.py").read_text()
    assert '"ctrader_xau_htf_strategic_regime_v180"' in text
    assert 'Strategic HTF Regime' in text
    assert '"Strategic Bias"' in text
    assert '"Tactical First Leg"' in text
    assert '"Canonical zones 0–24h"' in text
    assert '"Shadow zones 24–48h"' in text
    assert 'Shadow 24–48h zones have NO execution authority.' in text


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


def test_signal_expiry_status_still_compares_absolute_utc_time():
    text = (ROOT / "streamlit_app.py").read_text()
    assert 'admission_now = datetime.now(tz=UTC)' in text
    assert 'expires_dt = expires_dt.astimezone(UTC)' in text
    assert 'expires_dt < admission_now' in text
    assert 'now_utc = datetime.now(tz=UTC)' in text
    assert 'expires_dt < now_utc' in text

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

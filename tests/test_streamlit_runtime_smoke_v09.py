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
    assert '"TP1": _fmt_price(row.get("tp1"))' in text
    assert '"TP2": _fmt_price(row.get("tp2"))' in text
    assert 'AFIC authority remains a separate gate' in text


def test_xau_dashboard_distinguishes_prior_origin_revisit_and_target_semantics():
    text = (ROOT / "streamlit_app.py").read_text()
    assert 'PRIOR ORIGIN REVISIT' in text
    assert 'not the current primary AFIC zone' in text
    assert '"first target"' in text
    assert '"terminal target"' in text
    assert '"raw TP1"' in text
    assert '"raw TP2"' in text

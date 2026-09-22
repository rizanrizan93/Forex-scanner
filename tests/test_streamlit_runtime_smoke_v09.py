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

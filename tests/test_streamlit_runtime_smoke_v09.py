from pathlib import Path

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]


def test_streamlit_app_boots_offline_without_backend_secrets():
    app = AppTest.from_file(
        ROOT / "streamlit_app.py",
        default_timeout=10,
    ).run()
    assert not app.exception
    assert app.title
    assert app.title[0].value == "FX Institutional Scanner"
    assert any(
        "Dashboard can be deployed now" in element.value
        for element in app.info
    )

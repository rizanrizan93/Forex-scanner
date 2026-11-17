"""Retired USD Lead links render R2 when market transports are unavailable."""
from pathlib import Path
import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('failure', [
    ModuleNotFoundError("No module named 'curl_cffi'", name='curl_cffi'),
    OSError('Market source unreachable'),
    ValueError('R2_SNAPSHOT_STALE'),
])
def test_usd_lead_alias_survives_unavailable_market_source(monkeypatch, failure):
    from fx_scanner.entry_direction_r2 import dashboard

    def unavailable():
        raise failure

    monkeypatch.setattr(dashboard, 'fetch_snapshot', unavailable)
    app = AppTest.from_file(str(ROOT / 'pages/5_USD_Lead_Engine.py')).run()
    assert not app.exception
    assert any('Arah Entry R2' in x.value for x in app.subheader)
    assert any(x.label == 'Status' and x.value == 'MENUNGGU DATA' for x in app.metric)
    assert any(x.label == 'Arah entry' and x.value == 'WAIT' for x in app.metric)
    assert not app.success


def test_streamlit_cloud_requirements_covers_macro_transport():
    reqs = (ROOT / 'requirements.txt').read_text().splitlines()
    spec = (ROOT / 'pyproject.toml').read_text()
    assert 'curl-cffi==0.16.3' in reqs
    assert '"curl-cffi==0.16.3"' in spec

"""Exercise real Streamlit page switching with market/network renderers stubbed."""
from pathlib import Path
import importlib
import runpy
import streamlit as st
from streamlit.testing.v1 import AppTest
from fx_scanner import zone_v05_dashboard

ROOT=Path(__file__).resolve().parents[1]


def app(monkeypatch):
    monkeypatch.setattr(importlib, 'reload', lambda module: module)
    monkeypatch.setattr(zone_v05_dashboard, 'render_zone_v05', lambda: st.write('ZONE PANEL'))
    monkeypatch.setattr(runpy, 'run_path', lambda path, **kwargs: st.write('PAGE: '+Path(path).name))
    return AppTest.from_file(str(ROOT/'main.py'),default_timeout=15).run()


def test_switches_cancel_old_panel_and_return_to_zone(monkeypatch):
    at=app(monkeypatch)
    assert not at.exception
    for detail, marker in [('Analisis Terpadu','7_XAU_Unified_Decision.py'),('Makro','2_US10Y_Regime_Timing.py'),('Zona reversal','ZONE PANEL')]:
        at.radio(key='rizan_xau_detail').set_value(detail).run()
        assert not at.exception
        assert not any("no-op" in str(x.value) for x in at.warning)
        assert at.radio(key='rizan_xau_detail').value == detail
        text='\n'.join(str(x.value) for x in at.markdown)
        assert marker in text
        assert 'Halaman belum dapat dimuat' not in text


def test_page_failure_keeps_navigation_and_retry(monkeypatch):
    at=app(monkeypatch)
    def broken(*args, **kwargs):
        raise RuntimeError('backend unavailable')
    monkeypatch.setattr(runpy,'run_path',broken)
    at.radio(key='rizan_xau_detail').set_value('Analisis Terpadu').run()
    assert not at.exception
    assert any('Halaman belum dapat dimuat' in e.value for e in at.error)
    assert at.button(key='rizan_retry_page')
    at.radio(key='rizan_xau_detail').set_value('Zona reversal').run()
    assert not at.exception
    assert any('ZONE PANEL' in x.value for x in at.markdown)

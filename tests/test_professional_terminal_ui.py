"""Professional ForexScanner presentation regression tests (no network/orders)."""
from __future__ import annotations

import ast
import tomllib
from pathlib import Path

from fx_scanner.ui_terminal import (
    SECTION_DESCRIPTIONS, TERMINAL_CSS,
    condition_html, progress_html,
)

ROOT = Path(__file__).resolve().parents[1]


def test_theme_is_valid_toml_and_accessible_dark_palette():
    config = tomllib.loads((ROOT / ".streamlit/config.toml").read_text())
    assert config["theme"]["base"] == "dark"
    assert config["theme"]["backgroundColor"] == "#0B121C"
    assert config["theme"]["primaryColor"] == "#46CCB9"
    assert config["theme"]["textColor"] == "#E8EFF7"
    assert config["browser"]["gatherUsageStats"] is False


def test_mobile_navigation_is_scrollable_and_reuses_original_session_keys():
    assert "@media (max-width: 850px)" in TERMINAL_CSS
    assert "overflow-x: auto" in TERMINAL_CSS
    src = (ROOT / "main.py").read_text()
    assert 'key="rizan_pair"' in src
    assert 'key="rizan_xau_detail"' in src
    assert 'render_brand(st)' in src
    assert 'render_section_intro(st, pair="XAUUSD", detail=selected_detail)' in src
    assert '"USD Lead", "Teknikal", "Demand", "Pre-News", "Makro"' in src
    assert '("USD_Lead_Engine", "XAUUSD", "USD Lead")' in src
    assert '("XAU_Decision_Checklist", "XAUUSD", "Checklist")' in src
    assert 'st.navigation(routes, position="hidden").run()' in src


def test_every_xau_navigation_label_has_a_section_description():
    src = (ROOT / "main.py").read_text()
    labels = ast.literal_eval(
        next(
            x.value for x in ast.walk(ast.parse(src))
            if isinstance(x, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "labels" for t in x.targets)
        )
    )
    assert len(labels) == 12
    assert set(labels).issubset(SECTION_DESCRIPTIONS)


def test_conditions_are_distinct_and_escape_untrusted_provider_strings():
    for state, style, label in (
        ("PASS", "pass", "TERPENUHI"),
        ("FAIL", "fail", "BELUM TERPENUHI"),
        ("UNKNOWN", "unknown", "DATA BELUM VALID"),
    ):
        fragment = condition_html(
            title='<script>alert("x")</script>', state=state,
            detail='<img src=x onerror=alert(1)>', meta='&out',
        )
        assert '<script>' not in fragment
        assert '<img' not in fragment
        assert "&lt;script&gt;" in fragment
        assert "&#x27;" not in fragment or "TERPENUHI" in fragment
        assert "&lt;img" in fragment
        assert "&amp;out" in fragment
        assert "rz-condition " + style in fragment
        assert label in fragment


def test_unknown_never_receives_a_green_checkmark():
    unknown = condition_html(title="Latest yield", state="UNKNOWN", detail="missing")
    assert 'rz-condition unknown' in unknown
    assert 'class="rz-condition-icon" aria-hidden="true">–<' in unknown
    assert "DATA BELUM VALID" in unknown


def test_progress_is_bounded_and_has_accessibility_summary():
    p = progress_html(passed=2, failed=3, unknown=3, total=8)
    assert "2/8 terpenuhi" in p
    assert "3 belum · 3 data belum valid" in p
    assert "role=\"img\"" in p
    assert "width:25.0%" in p
    assert progress_html(passed=0, failed=0, unknown=0, total=0) == ""


def test_checklist_and_usd_lead_use_same_presentational_helper_without_logic_edits():
    xau = (ROOT / "pages/4_XAU_Decision_Checklist.py").read_text()
    usd = (ROOT / "pages/5_USD_Lead_Engine.py").read_text()
    for file in (xau, usd):
        ast.parse(file)
        assert "render_condition(" in file
        assert "render_progress(" in file
        assert "evaluate_" in file
    assert "yield_nowcast=yield_projection" in usd
    assert "structure_fresh=market_fresh" in xau
    assert "broker_spec=broker_spec" in xau
    assert "Frozen V1" in usd



def test_streamlit_components_render_without_any_backend_or_quotes():
    from streamlit.testing.v1 import AppTest
    source = """
import sys
sys.path.insert(0, "src")
import streamlit as st
from fx_scanner.ui_terminal import (
    TERMINAL_CSS, render_brand, render_section_intro,
    render_condition, render_progress,
)
st.set_page_config(page_title="RIZAN UI smoke", layout="wide")
st.markdown(TERMINAL_CSS, unsafe_allow_html=True)
render_brand(st)
render_section_intro(st, pair="XAUUSD", detail="USD Lead")
render_progress(st, passed=2, failed=1, unknown=1, total=4)
render_condition(st, title="US2Y spread", state="PASS", detail="Official published daily")
render_condition(st, title="DXY", state="UNKNOWN", detail="Quote stale")
"""
    app = AppTest.from_string(source, default_timeout=12).run()
    assert not app.exception
    rendered = "\n".join(str(x.value) for x in app.markdown)
    assert "RIZAN" in rendered
    assert "USD Lead" in rendered
    assert "2/4 terpenuhi" in rendered
    assert "DATA BELUM VALID" in rendered

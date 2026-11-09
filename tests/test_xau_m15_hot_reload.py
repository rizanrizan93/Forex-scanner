"""Regression checks for the XAU M15 dashboard deployment reload chain.

A fresh market feed with old Python imports previously rendered
'Snapshot cTrader M15 stale' even while broker M1/M15 were updating.
"""
import ast
from pathlib import Path

PAGE = Path("pages/2_US10Y_Regime_Timing.py")
ENGINE = Path("src/fx_scanner/xau_m15_macro_forecast.py")
UI = Path("src/fx_scanner/xau_macro_risk_monitor.py")
SETTINGS = Path(".streamlit/config.toml")


def _reload_chain():
    parsed = ast.parse(PAGE.read_text(encoding="utf-8"))
    fn = next(x for x in parsed.body
              if isinstance(x, ast.FunctionDef)
              and x.name == "_refresh_macro_code_if_changed")
    assignment = next(x for x in ast.walk(fn)
                      if isinstance(x, ast.Assign) and any(
                          isinstance(t, ast.Name) and t.id == "modules"
                          for t in x.targets
                      ))
    return [item.id for item in assignment.value.elts]


def test_dependencies_reload_before_consumer_ui():
    chain = _reload_chain()
    assert chain.index("_m15_engine") < chain.index("_m15_feed")
    assert chain.index("_m15_feed") < chain.index("_macro_ui")
    assert len(chain) == len(set(chain))


def test_file_revision_signature_monitors_all_m15_modules():
    text = PAGE.read_text(encoding="utf-8")
    assert "module.__file__" in text
    assert "st_mtime_ns" in text
    assert "reload(module)" in text
    assert "_m15_engine" in text and "_m15_feed" in text


def test_page_shows_independent_build_marker():
    text = ENGINE.read_text(encoding="utf-8")
    assert 'M15_BUILD = "M15-R2-20261109-RELOAD"' in text
    assert 'st.caption("Engine " + M15_BUILD' in text


def test_streamlit_reruns_when_source_is_redeployed():
    assert "runOnSave = true" in SETTINGS.read_text(encoding="utf-8")


def test_macro_loader_does_not_reintroduce_stale_manual_fallback():
    source = UI.read_text(encoding="utf-8")
    fn = source.split("def load_macro_m15_snapshot_readonly():", 1)[1].split(
        "def render_gold_macro_conclusion(", 1
    )[0]
    assert "fetch_fast_m15()" in fn
    assert "fetch_manual_map" not in fn

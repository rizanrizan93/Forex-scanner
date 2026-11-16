"""Regression for Streamlit Cloud crash: missing optional Yahoo curl-cffi transport.

The uploaded Streamlit Cloud traceback failed at a module-level import while
opening USD Lead. A broken secondary quote source must result in UNKNOWN/WAIT,
never prevent the entire ForexScanner page from rendering.
"""
from __future__ import annotations

import ast
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "pages" / "5_USD_Lead_Engine.py"


def _supplemental_function():
    source = PAGE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    fn = next(n for n in tree.body
              if isinstance(n, ast.FunctionDef) and n.name == "supplemental_quotes")
    namespace = {"datetime": datetime}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), str(PAGE), "exec"), namespace)
    return tree, namespace


def test_secondary_transport_is_not_imported_at_page_top_level():
    tree, _ = _supplemental_function()
    assert not [
        x for x in tree.body
        if isinstance(x, ast.ImportFrom)
        and x.module == "fx_scanner.xau_intraday_macro_v398"
    ]


def test_missing_curl_cffi_keeps_original_macro_and_marks_fallback_unavailable():
    _, ns = _supplemental_function()

    def no_transport():
        raise ModuleNotFoundError("No module named 'curl_cffi'", name="curl_cffi")

    ns["_load_intraday_market_helpers"] = no_transport
    initial = {"fed_funds_futures": {"available": True, "current_at": "test"}}
    updated, notes = ns["supplemental_quotes"](initial, datetime.now(UTC))
    assert updated == initial
    assert "curl_cffi" in notes["fed_funds_futures"]
    assert "curl_cffi" in notes["dxy_intraday"]


def test_failing_network_request_does_not_crash_or_mark_quote_valid():
    _, ns = _supplemental_function()
    ns["_load_intraday_market_helpers"] = (
        lambda: (lambda *a, **kw: None, lambda *a, **kw: None,
                 lambda *a, **kw: None)
    )
    ns["obj"] = lambda x: dict(x or {})
    ns["fresh"] = lambda *a, **kw: False

    class SimulatedCurlRequestException(Exception):
        pass

    def bad_network(_symbol):
        raise SimulatedCurlRequestException("Yahoo unreachable")

    ns["fallback_market"] = bad_network
    output, note = ns["supplemental_quotes"]({}, datetime.now(UTC))
    assert output == {}
    assert "SimulatedCurlRequestException" in note["fed_funds_futures"]
    assert "SimulatedCurlRequestException" in note["dxy_intraday"]


def test_streamlit_cloud_requirements_covers_macro_transport():
    reqs = (ROOT / "requirements.txt").read_text().splitlines()
    spec = (ROOT / "pyproject.toml").read_text()
    assert "curl-cffi==0.16.3" in reqs
    assert '"curl-cffi==0.16.3"' in spec

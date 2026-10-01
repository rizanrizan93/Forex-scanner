from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_v327_decision_center_publishes_liquidity_pool_envelope():
    source = _read("src/fx_scanner/demo_xau_decision_center_v296.py")
    assert "build_liquidity_pool_envelope" in source
    assert 'decision["liquidity_sweep_map_v327"]' in source
    assert 'decision["liquidity_sweep_map_v317"]' in source


def test_v327_dashboard_prefers_pool_envelope_and_keeps_structural_fallback():
    app = _read("streamlit_app.py")
    assert "liquidity_sweep_map_v327" in app
    assert "Liquidity pool utama sebelum reversal" in app
    assert "Liquidity pools V327" in app
    assert "WAIT_STRUCTURAL_CONTEXT_ONLY" in app
    assert "build_liquidity_pool_envelope" in app
    assert "Canonical entry" in app
    assert "BELUM ADA • WAIT" in app

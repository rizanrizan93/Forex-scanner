from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_v210_auto_refresh_clears_cached_fast_reader_not_merge_wrapper() -> None:
    text = _read("streamlit_app.py")
    assert "def _clear_backend_snapshot_cache(*, include_slow: bool)" in text
    assert "_load_backend_fast_snapshot.clear()" in text
    assert "_load_backend_slow_snapshot.clear()" in text
    assert "_load_backend_snapshot.clear()" not in text
    assert "_clear_backend_snapshot_cache(include_slow=False)" in text
    assert "_clear_backend_snapshot_cache(include_slow=True)" in text


def test_v210_arrow_serialization_is_explicit_for_mixed_columns() -> None:
    text = _read("streamlit_app.py")
    assert 'if "details" in heartbeats.columns:' in text
    assert "json.dumps(" in text
    assert '"minimum": str(acceptance["profit_factor_min"])' in text
    assert '"minimum": str(acceptance["aggregate_oos_trades_min"])' in text


def test_v210_streamlit_width_api_is_current() -> None:
    text = _read("streamlit_app.py")
    assert "use_container_width=" not in text
    assert 'width="stretch"' in text

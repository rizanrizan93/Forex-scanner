from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_v219_chart_upgrade_is_preserved_inside_rizan_style_dashboard() -> None:
    text = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
    assert "Peta Harga & Supply/Demand — RIZAN-style" in text
    assert "TARGET 1" in text
    assert "NEXT SOURCE" in text
    assert "touch {_fmt_pct(p_touch)}" in text
    assert "hold50 {_fmt_pct(p_hold)}" in text
    assert "FancyArrowPatch" in text
    assert "_rizan_chart_png" in text
    assert "Download chart RIZAN-style (PNG)" in text
    assert 'file_name=f"xauusd_rizan_supply_demand_{rizan_chart_tf.lower()}.png"' in text
    assert "Timeframe chart" in text
    assert "chart_bars_m15" in text


def test_v219_chart_does_not_create_execution_authority() -> None:
    text = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
    assert "Panah menunjukkan jalur preparation, bukan jaminan pergerakan harga." in text
    assert "izin order tetap mengikuti admission dan protection contract" in text

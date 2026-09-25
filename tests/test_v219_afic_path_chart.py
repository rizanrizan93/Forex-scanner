from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_v219_afic_chart_prioritizes_path_and_is_downloadable() -> None:
    text = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
    assert "Peta Supply/Demand Terdekat — AFIC-style" in text
    assert "1ST OPPOSING ZONE" in text
    assert "NEXT-LEG SOURCE" in text
    assert "touch={_fmt_pct(p_touch)} hold50={_fmt_pct(p_hold)}" in text
    assert "FancyArrowPatch" in text
    assert "harga sekarang → reaction target → opposing Supply/Demand" in text
    assert "Download peta Supply/Demand AFIC-style (PNG)" in text
    assert 'file_name="xauusd_afic_supply_demand_path.png"' in text


def test_v219_chart_does_not_create_execution_authority() -> None:
    text = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
    assert "Forecast preparation/shadow" in text or "forecast preparation/shadow" in text
    assert "bukan jaminan harga atau execution authority" in text

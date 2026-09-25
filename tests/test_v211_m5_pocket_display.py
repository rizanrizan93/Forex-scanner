from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_v211_dashboard_shows_candidate_and_refined_m5_pockets_independently() -> None:
    text = _read("streamlit_app.py")

    assert 'f"INITIAL M5 **{dc_current_leg_direction}** POCKET: "' in text
    assert 'f"REFINED M5 **{dc_current_leg_direction}** POCKET: "' in text
    assert "dc_current_pocket_shown = False" in text
    assert "if dc_initial_candidate:" in text
    assert "if dc_refined_display:" in text
    assert "elif dc_initial_candidate:" not in text

    assert 'f"INITIAL M5 **{dc_next_leg_direction}** POCKET berikutnya: "' in text
    assert 'f"REFINED M5 **{dc_next_leg_direction}** POCKET berikutnya: "' in text
    assert "dc_next_pocket_shown = False" in text
    assert "if dc_next_initial_candidate:" in text
    assert "if dc_next_refined_display:" in text

    assert "Reaction target={dc_current_target_text}" in text
    assert "Reaction target={dc_next_target_text}" in text


def test_v211_refined_display_does_not_change_execution_authority() -> None:
    text = _read("streamlit_app.py")
    assert "**SHADOW/PREPARE — belum otomatis menjadi entry resmi.**" in text
    assert "Refined pocket tetap tidak menjadi izin broker tanpa admission yang valid." in text

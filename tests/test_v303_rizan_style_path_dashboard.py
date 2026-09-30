from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
DECISION_CENTER = (
    ROOT / "src" / "fx_scanner" / "demo_xau_decision_center_v296.py"
).read_text(encoding="utf-8")


def test_v303_dashboard_surfaces_rizan_style_path_engine() -> None:
    assert "RIZAN STYLE PATH ENGINE" in DASHBOARD
    assert "Peta alur bercabang: source → decision zone → rejection atau acceptance" in DASHBOARD
    assert "Decision zone berikut" in DASHBOARD
    assert "KEY rejection / reclaim" in DASHBOARD
    assert "KEY break / acceptance" in DASHBOARD
    assert "Primary path" in DASHBOARD
    assert "Jika REJECTION terkonfirmasi" in DASHBOARD
    assert "Jika ACCEPTANCE / break" in DASHBOARD


def test_v303_dashboard_uses_current_atlas_and_fresh_price() -> None:
    assert "build_rizan_style_path_engine" in DASHBOARD
    assert "atlas_evaluation=dc_sd_eval" in DASHBOARD
    assert "price_now=dc_reference_price" in DASHBOARD
    assert "path_direction=v240_direction" in DASHBOARD


def test_v303_decision_center_embeds_non_voting_style_path() -> None:
    assert "build_rizan_style_path_engine" in DECISION_CENTER
    assert 'decision["rizan_style_path_engine"]' in DECISION_CENTER
    assert '"engine": "RIZAN_STYLE_PATH_ENGINE"' in DECISION_CENTER
    assert '"role": "NON_VOTING_BRANCHING_STRUCTURAL_FORECAST"' in DECISION_CENTER

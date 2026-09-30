from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ATLAS = (
    ROOT / "src" / "fx_scanner" / "demo_xau_supply_demand_atlas_v182.py"
).read_text(encoding="utf-8")
DECISION_CENTER = (
    ROOT / "src" / "fx_scanner" / "demo_xau_decision_center_v296.py"
).read_text(encoding="utf-8")


def test_v304_atlas_evaluates_reference_after_path_is_built() -> None:
    assert "evaluate_v304" in ATLAS
    assert 'payload["rizan_style_path_engine_v303"]' in ATLAS
    assert 'payload["rizan_style_path_calibration_v304"]' in ATLAS
    assert "bars=raw" in ATLAS
    assert "as_of=now" in ATLAS


def test_v304_decision_center_exposes_reference_calibration_as_non_voting() -> None:
    assert 'decision["rizan_style_path_calibration_v304"]' in DECISION_CENTER
    assert '"engine": "RIZAN_STYLE_PATH_CALIBRATION_V304"' in DECISION_CENTER
    assert '"role": "NON_VOTING_PUBLIC_REFERENCE_CALIBRATION"' in DECISION_CENTER

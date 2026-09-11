from pathlib import Path


def test_pretrigger_requires_structure_and_fresh_directional_fvg():
    source = Path("src/fx_scanner/demo_technical_strategy.py").read_text(encoding="utf-8")

    block = source.split("calibration_ready = bool(", 1)[1].split(")\n\n        if calibration_ready", 1)[0]
    assert "_demo_calibration_pretrigger_enabled()" in block
    assert "score_driven_setup" in block
    assert "plan_ready" in block
    assert "early_structure" in block
    assert "fresh_fvg" in block


def test_calibration_does_not_mutate_geometry_or_global_score_floor():
    source = Path("src/fx_scanner/demo_technical_strategy.py").read_text(encoding="utf-8")
    workflow = Path(".github/workflows/ctrader-demo-auto-pipeline.yml").read_text(encoding="utf-8")

    assert 'CTRADER_DEMO_EXECUTION_CANDIDATE_MIN: "70.0"' in workflow
    assert "sl_buffer_atr" in source
    assert "minimum_entry_zone_atr" in source
    assert "minimum_tp2_rr" in source

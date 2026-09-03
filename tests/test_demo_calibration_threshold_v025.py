from dataclasses import replace

import pytest

from fx_scanner.config import load_project_config
from fx_scanner.demo_calibration import apply_demo_calibration_threshold


def test_demo_calibration_accepts_threshold_50(monkeypatch):
    cfg = load_project_config(None)
    monkeypatch.setenv("CTRADER_DEMO_EXECUTION_CANDIDATE_MIN", "50")

    adjusted, production = apply_demo_calibration_threshold(cfg)

    assert production == 90.0
    assert adjusted.scoring["states"]["execution_candidate_min"] == 50.0
    assert cfg.scoring["states"]["execution_candidate_min"] == 90


def test_demo_calibration_rejects_below_50(monkeypatch):
    cfg = load_project_config(None)
    monkeypatch.setenv("CTRADER_DEMO_EXECUTION_CANDIDATE_MIN", "49.99")

    with pytest.raises(SystemExit, match="CTRADER_DEMO_CALIBRATION_THRESHOLD_OUT_OF_RANGE"):
        apply_demo_calibration_threshold(cfg)


def test_demo_calibration_does_not_change_canonical_watch_floor(monkeypatch):
    cfg = load_project_config(None)
    original_states = dict(cfg.scoring["states"])
    monkeypatch.setenv("CTRADER_DEMO_EXECUTION_CANDIDATE_MIN", "50")

    adjusted, _ = apply_demo_calibration_threshold(cfg)

    assert adjusted.scoring["states"]["watch_min"] == original_states["watch_min"]
    assert adjusted.scoring["states"]["armed_min"] == original_states["armed_min"]
    assert adjusted.scoring["states"]["execution_candidate_min"] == 50.0

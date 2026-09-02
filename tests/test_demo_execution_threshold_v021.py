import pytest

from fx_scanner.cli import _apply_demo_execution_threshold
from fx_scanner.config import load_project_config


def test_demo_threshold_defaults_to_canonical_90(monkeypatch):
    monkeypatch.delenv("CTRADER_DEMO_EXECUTION_CANDIDATE_MIN", raising=False)
    cfg = load_project_config()

    derived, production_default = _apply_demo_execution_threshold(cfg)

    assert production_default == 90.0
    assert derived.scoring["states"]["execution_candidate_min"] == 90.0


def test_demo_threshold_can_be_lowered_to_70_without_mutating_canonical_config(monkeypatch):
    monkeypatch.setenv("CTRADER_DEMO_EXECUTION_CANDIDATE_MIN", "70")
    cfg = load_project_config()

    derived, production_default = _apply_demo_execution_threshold(cfg)

    assert production_default == 90.0
    assert derived.scoring["states"]["execution_candidate_min"] == 70.0
    assert cfg.scoring["states"]["execution_candidate_min"] == 90.0


def test_demo_threshold_cannot_drop_below_watch_floor(monkeypatch):
    monkeypatch.setenv("CTRADER_DEMO_EXECUTION_CANDIDATE_MIN", "64")
    cfg = load_project_config()

    with pytest.raises(SystemExit, match="CTRADER_DEMO_EXECUTION_THRESHOLD_OUT_OF_RANGE"):
        _apply_demo_execution_threshold(cfg)


def test_demo_threshold_cannot_exceed_production_default(monkeypatch):
    monkeypatch.setenv("CTRADER_DEMO_EXECUTION_CANDIDATE_MIN", "91")
    cfg = load_project_config()

    with pytest.raises(SystemExit, match="CTRADER_DEMO_EXECUTION_THRESHOLD_OUT_OF_RANGE"):
        _apply_demo_execution_threshold(cfg)

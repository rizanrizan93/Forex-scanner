import pytest

from fx_scanner.config import load_project_config
from fx_scanner.demo_calibration import apply_demo_deep_analysis_top


def test_deep_top_still_rejects_below_canonical_request(monkeypatch):
    cfg = load_project_config(None)
    monkeypatch.setenv("CTRADER_DEMO_DEEP_ANALYSIS_TOP", "4")

    with pytest.raises(SystemExit, match="CTRADER_DEMO_DEEP_ANALYSIS_TOP_OUT_OF_RANGE"):
        apply_demo_deep_analysis_top(cfg)


def test_deep_top_still_rejects_above_hard_cap(monkeypatch):
    cfg = load_project_config(None)
    monkeypatch.setenv("CTRADER_DEMO_DEEP_ANALYSIS_TOP", "11")

    with pytest.raises(SystemExit, match="CTRADER_DEMO_DEEP_ANALYSIS_TOP_OUT_OF_RANGE"):
        apply_demo_deep_analysis_top(cfg)

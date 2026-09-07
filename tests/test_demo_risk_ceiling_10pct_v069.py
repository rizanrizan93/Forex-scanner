from pathlib import Path

import pytest

from fx_scanner.config import load_project_config
from fx_scanner.demo_calibration import apply_demo_calibration_risk


def test_demo_calibration_accepts_ten_percent_ceiling(monkeypatch):
    cfg = load_project_config()
    monkeypatch.setenv("CTRADER_DEMO_RISK_PER_TRADE_PCT", "10.0")

    adjusted, requested = apply_demo_calibration_risk(cfg, max_risk_pct=10.0)

    assert requested == 10.0
    assert adjusted.risk["risk_per_trade_pct"] == 10.0
    assert adjusted.risk["max_risk_per_trade_pct"] == 10.0


def test_demo_calibration_rejects_above_ten_percent(monkeypatch):
    cfg = load_project_config()
    monkeypatch.setenv("CTRADER_DEMO_RISK_PER_TRADE_PCT", "10.01")

    with pytest.raises(SystemExit, match="CTRADER_DEMO_RISK_PER_TRADE_OUT_OF_RANGE"):
        apply_demo_calibration_risk(cfg, max_risk_pct=10.0)


def test_auto_pipeline_exposes_ten_percent_as_ceiling_only():
    source = Path(".github/workflows/ctrader-demo-auto-pipeline.yml").read_text(
        encoding="utf-8"
    )
    assert 'CTRADER_DEMO_RISK_PER_TRADE_PCT: "10.0"' in source
    assert "python -m fx_scanner.demo_fresh_ready_handoff --limit 10" in source

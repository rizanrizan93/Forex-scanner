from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_demo_fast_pass_fetches_fast_timeframes_for_universe_then_hydrates_shortlist():
    text = (ROOT / "src/fx_scanner/demo_signal_producer.py").read_text()
    assert 'fast_tfs = ("H1", "M15", "M5")' in text
    assert 'for tf in ("D1", "H4")' in text
    assert "self._fetch_fast_market" in text
    assert "self._hydrate_slow_timeframes" in text
    assert "request_pacing" not in text


def test_demo_risk_is_hard_capped_to_half_percent_and_two_positions():
    risk = yaml.safe_load((ROOT / "config/risk.yaml").read_text())
    execution = yaml.safe_load((ROOT / "config/execution.yaml").read_text())
    auto_workflow = (ROOT / ".github/workflows/ctrader-demo-auto-pipeline.yml").read_text()
    discovery_workflow = (ROOT / ".github/workflows/ctrader-demo-discovery-pipeline.yml").read_text()

    assert float(risk["risk_per_trade_pct"]) == 0.25
    assert float(risk["max_risk_per_trade_pct"]) == 0.50
    assert float(execution["demo_safety"]["max_risk_pct"]) == 0.5
    assert 'CTRADER_DEMO_RISK_PER_TRADE_PCT: "0.5"' in auto_workflow
    assert 'CTRADER_DEMO_RISK_PER_TRADE_PCT: "0.5"' in discovery_workflow
    assert 'CTRADER_DEMO_MAX_ORDER_LOTS: "0.01"' in auto_workflow
    assert int(execution["demo_safety"]["max_concurrent_positions"]) == 2
    assert execution["ctrader"]["environment"] == "DEMO"
    assert execution["mode"] == "DISABLED"


def test_demo_process_wrapper_keeps_fail_closed_risk_cap_path():
    text = (ROOT / "src/fx_scanner/demo_calibration.py").read_text()
    guard_text = (ROOT / "src/fx_scanner/demo_correlation_evidence.py").read_text()
    executor_text = (ROOT / "src/fx_scanner/demo_calibration_autotrade.py").read_text()
    assert "apply_demo_calibration_risk" in text
    assert "CTRADER_DEMO_RISK_PER_TRADE_PCT" in text
    assert "DEMO_RISK_CEILING_PCT = 0.5" in text
    assert "replace(cfg, risk=risk)" in text
    assert "self.demo_max_risk_pct = max" in guard_text
    assert 'demo_safety["max_risk_pct"] = 5.0' not in executor_text
    assert "max_risk_pct=5.0" not in executor_text


def test_demo_fast_pass_observability_markers_exist():
    text = (ROOT / "src/fx_scanner/demo_technical_producer.py").read_text()
    workflow = (ROOT / ".github/workflows/ctrader-demo-auto-pipeline.yml").read_text()
    assert "CTRADER_DEMO_FAST_PASS" in text
    assert "CTRADER_DEMO_RISK" in text
    assert "production_chase_block_atr" in text
    assert 'CTRADER_DEMO_CHASE_BLOCK_ATR: "2.0"' in workflow

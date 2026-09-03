from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_demo_fast_pass_fetches_fast_timeframes_for_universe_then_hydrates_shortlist():
    text = (ROOT / "src/fx_scanner/demo_signal_producer.py").read_text()
    assert 'fast_tfs = ("H1", "M15", "M5")' in text
    assert 'for tf in ("D1", "H4")' in text
    assert "self._fetch_fast_market" in text
    assert "self._hydrate_slow_timeframes" in text
    assert "request_pacing" not in text  # implementation must not add a pacing bypass


def test_demo_risk_is_capped_at_one_percent_and_lot_cap_is_preserved():
    risk = yaml.safe_load((ROOT / "config/risk.yaml").read_text())
    execution = yaml.safe_load((ROOT / "config/execution.yaml").read_text())
    assert float(risk["risk_per_trade_pct"]) == 1.0
    assert float(risk["max_risk_per_trade_pct"]) == 1.0
    assert float(execution["demo_safety"]["max_risk_pct"]) == 1.0
    assert float(execution["demo_safety"]["max_order_lots"]) == 0.01
    assert int(execution["demo_safety"]["max_concurrent_positions"]) == 2
    assert execution["ctrader"]["environment"] == "DEMO"
    assert execution["mode"] == "DISABLED"


def test_demo_fast_pass_observability_markers_exist():
    text = (ROOT / "src/fx_scanner/demo_technical_producer.py").read_text()
    assert "CTRADER_DEMO_FAST_PASS" in text
    assert "CTRADER_DEMO_RISK" in text
    assert "chase_block_atr=0.50" in text

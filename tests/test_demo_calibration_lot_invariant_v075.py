from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_calibration_auto_pipeline_keeps_point_zero_one_lot_runtime_cap():
    workflow = (ROOT / ".github/workflows/ctrader-demo-auto-pipeline.yml").read_text()
    execution = yaml.safe_load((ROOT / "config/execution.yaml").read_text())

    assert 'CTRADER_DEMO_MAX_ORDER_LOTS: "0.01"' in workflow
    assert float(execution["demo_safety"]["max_order_lots"]) == 0.01
    assert 'CTRADER_DEMO_MAX_CONCURRENT_POSITIONS: "10"' in workflow
    assert 'CTRADER_DEMO_RISK_PER_TRADE_PCT: "3.0"' in workflow
    assert 'CTRADER_DEMO_ALLOW_SAME_SYMBOL_STACKING: "1"' in workflow
    assert execution["ctrader"]["environment"] == "DEMO"
    assert execution["mode"] == "DISABLED"

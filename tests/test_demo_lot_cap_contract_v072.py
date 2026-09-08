from pathlib import Path

import yaml


def test_committed_demo_order_cap_stays_at_point_zero_one_lot():
    config = yaml.safe_load(Path("config/execution.yaml").read_text(encoding="utf-8"))
    assert float(config["demo_safety"]["max_order_lots"]) == 0.01


def test_core_policy_rejects_demo_order_cap_above_point_zero_one():
    source = Path("src/fx_scanner/execution/policy.py").read_text(encoding="utf-8")
    assert 'demo max_order_lots cannot exceed 0.01' in source

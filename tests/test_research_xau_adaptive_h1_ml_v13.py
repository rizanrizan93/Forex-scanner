from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_v13_has_locked_holdout_and_purged_first_checkpoint_policy():
    source = (ROOT / "src/fx_scanner/research_xau_adaptive_h1_ml_v13.py").read_text()
    assert "THRESHOLDS_R = (0.05, 0.10, 0.15, 0.20)" in source
    assert "PURGE_DAYS = 2" in source
    assert "CHECKPOINT_HOURS = (0, 7, 12, 15, 22)" in source
    assert '"holdout_used_for_selection": False' in source
    assert '"decision_policy": "FIRST_CHECKPOINT_PER_DAY_ABOVE_THRESHOLD"' in source


def test_v13_is_shadow_only_and_ml_dependency_is_research_scoped():
    source = (ROOT / "src/fx_scanner/research_xau_adaptive_h1_ml_v13.py").read_text()
    runtime = (ROOT / "src/fx_scanner/research_xau_adaptive_h1_ml_v13_runtime.py").read_text()
    workflow = (ROOT / ".github/workflows/ctrader-xau-adaptive-h1-ml-v13.yml").read_text()
    assert '"policy_effect": "SHADOW_ONLY"' in source
    assert '"execution_influence": False' in source
    assert "demo_execution_fresh_ready_handoff" not in source
    assert "demo_execution_fresh_ready_handoff" not in runtime
    assert "scikit-learn==1.7.2" in workflow
    assert "FX_LIVE_TRADING_ENABLED" not in workflow
    assert "I_UNDERSTAND_LIVE_ORDERS" not in workflow

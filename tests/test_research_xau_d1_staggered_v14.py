from pathlib import Path
import importlib.util

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "research" / "xau_d1_staggered_v14.py"


def _source():
    return MODULE_PATH.read_text()


def test_v14_preregisters_cadence_target_grid_and_locked_oos():
    source = _source()
    assert "CADENCES = (1, 2, 3, 5)" in source
    assert "TARGET_RS = (1.0, 1.25, 1.5, 2.0)" in source
    assert "MAX_ACTIVE_TRANCHES = 10" in source
    assert 'OOS_START = pd.Timestamp("2025-01-01", tz="UTC")' in source
    assert '"oos_used_for_selection": False' in source
    assert 'if selected is not None:' in source


def test_v14_is_research_only_and_preserves_d1_regime():
    source = _source()
    workflow = (ROOT / ".github/workflows/research-xau-d1-staggered-v14.yml").read_text()
    assert 'EXECUTION_INFLUENCE = False' in source
    assert 'STOP_ATR = 2.0' in source
    assert 'MAX_HOLD_DAYS = 30' in source
    assert 'd1["close"] > d1["ema200"]' in source
    assert 'd1["ret60"] > 0' in source
    assert "demo_execution_fresh_ready_handoff" not in source
    assert "FX_LIVE_TRADING_ENABLED" not in workflow
    assert "I_UNDERSTAND_LIVE_ORDERS" not in workflow

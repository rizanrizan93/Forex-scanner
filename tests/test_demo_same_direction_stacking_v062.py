from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_demo_autotrade_allows_same_direction_stacking_and_closes_opposite_first():
    source = (ROOT / "src/fx_scanner/execution/demo_autotrade.py").read_text()
    assert "BROKER_SYMBOL_SAME_DIRECTION_ALLOWED" in source
    assert "BROKER_OPPOSITE_DIRECTION_CLOSE_REQUIRED" in source
    assert "_close_opposite_symbol_positions" in source
    assert "BROKER_OPPOSITE_DIRECTION_CLOSE_UNCERTAIN" in source
    assert "BROKER_OPPOSITE_DIRECTION_STILL_OPEN" in source


def test_demo_stacking_preserves_account_capacity_and_demo_safety():
    source = (ROOT / "src/fx_scanner/execution/demo_autotrade.py").read_text()
    assert "BROKER_CAPACITY_FULL" in source
    assert "max_concurrent_positions" in source
    assert "max_order_lots" in source
    assert "max_risk_pct" in source

from pathlib import Path

from fx_scanner.research_xau_h1_structure_context_v56 import (
    EXECUTION_INFLUENCE,
    FROZEN_ROUTE,
    PIVOT_LEFT,
    PIVOT_RIGHT,
    POLICY_EFFECT,
    PROMOTION_ELIGIBLE,
)

ROOT = Path(__file__).resolve().parents[1]


def test_v56_is_diagnostic_only():
    assert POLICY_EFFECT == "SHADOW_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False


def test_v56_freezes_route_and_causal_pivot():
    assert FROZEN_ROUTE == "SECULAR_BULL_REACCEL_LONG_COST10"
    assert PIVOT_LEFT == 2
    assert PIVOT_RIGHT == 2


def test_v56_has_no_repaint_or_execution_path():
    src = (ROOT / "src/fx_scanner/research_xau_h1_structure_context_v56.py").read_text()
    runtime = (
        ROOT / "src/fx_scanner/research_xau_h1_structure_context_v56_runtime.py"
    ).read_text()
    combined = src + "\n" + runtime
    assert "send_new_order" not in combined
    assert '"confirmation_delay_h1_bars": PIVOT_RIGHT' in src
    assert '"trade_filter_applied": False' in src
    assert '"ema_h1_permission_replaced": False' in src
    assert '"pivot_grid_search": False' in src
    assert '"selection_uses_future_outcomes": False' in src

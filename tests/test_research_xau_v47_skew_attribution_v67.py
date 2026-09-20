from pathlib import Path

from fx_scanner.research_xau_v47_skew_attribution_v67 import (
    DIAGNOSTIC_ONLY,
    EXECUTION_INFLUENCE,
    FROZEN_ROUTE,
    POLICY_EFFECT,
    PROMOTION_ELIGIBLE,
    REQUIRED_COSTS,
)

ROOT = Path(__file__).resolve().parents[1]


def test_v67_is_attribution_only():
    assert POLICY_EFFECT == "SHADOW_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False
    assert DIAGNOSTIC_ONLY is True
    assert FROZEN_ROUTE == "SECULAR_BULL_REACCEL_LONG_COST10"
    assert REQUIRED_COSTS == ("LOW_1700", "V24_STRESS_4675")


def test_v67_cannot_filter_or_execute():
    src=(ROOT / "src/fx_scanner/research_xau_v47_skew_attribution_v67.py").read_text()
    runtime=(ROOT / "src/fx_scanner/research_xau_v47_skew_attribution_v67_runtime.py").read_text()
    combined=src+"\n"+runtime
    assert "send_new_order" not in combined
    assert '"trade_filter_applied": False' in src
    assert '"skew_state_selected_as_winner": False' in src
    assert '"v47_family_gate_changed": False' in src
    assert '"selection_uses_future_outcomes": False' in src

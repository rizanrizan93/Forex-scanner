from pathlib import Path

from fx_scanner.research_xau_v47_sweep_mechanism_v80 import (
    DIAGNOSTIC_ONLY,
    DISPLACEMENT_BODY_ATR,
    EXECUTION_INFLUENCE,
    FROZEN_ROUTE,
    LIQUIDITY_SWEEP_LOOKBACK,
    POLICY_EFFECT,
    PROMOTION_ELIGIBLE,
    REQUIRED_COSTS,
    SEQUENCE_STATES,
)

ROOT = Path(__file__).resolve().parents[1]


def test_v80_is_shadow_only():
    assert POLICY_EFFECT == "SHADOW_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False
    assert DIAGNOSTIC_ONLY is True
    assert FROZEN_ROUTE == "SECULAR_BULL_REACCEL_LONG_COST10"
    assert REQUIRED_COSTS == ("LOW_1700", "V24_STRESS_4675")


def test_v80_reuses_canonical_sweep_and_displacement_constants():
    assert LIQUIDITY_SWEEP_LOOKBACK == 8
    assert DISPLACEMENT_BODY_ATR == 0.80
    assert SEQUENCE_STATES == (
        "NO_SWEEP",
        "SWEEP_NO_POST_DISPLACEMENT",
        "SWEEP_POST_DISPLACEMENT_NO_FVG",
        "SWEEP_POST_DISPLACEMENT_FVG",
        "UNAVAILABLE",
    )


def test_v80_cannot_change_v69_or_execute():
    src=(ROOT / "src/fx_scanner/research_xau_v47_sweep_mechanism_v80.py").read_text()
    runtime=(ROOT / "src/fx_scanner/research_xau_v47_sweep_mechanism_v80_runtime.py").read_text()
    combined=src+"\n"+runtime
    assert "send_new_order" not in combined
    assert '"v69_forward_contract_changed": False' in src
    assert '"trade_filter_applied": False' in src
    assert '"sequence_state_selected_as_winner": False' in src
    assert '"selection_uses_future_outcomes": False' in src

from pathlib import Path

from fx_scanner.research_xau_v47_htf_liquidity_v84 import (
    DIAGNOSTIC_ONLY,
    EXECUTION_INFLUENCE,
    FROZEN_ROUTE,
    HTF_STATES,
    POLICY_EFFECT,
    PROMOTION_ELIGIBLE,
    REQUIRED_COSTS,
)

ROOT = Path(__file__).resolve().parents[1]


def test_v84_is_diagnostic_only():
    assert POLICY_EFFECT == "SHADOW_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False
    assert DIAGNOSTIC_ONLY is True
    assert FROZEN_ROUTE == "SECULAR_BULL_REACCEL_LONG_COST10"
    assert REQUIRED_COSTS == ("LOW_1700", "V24_STRESS_4675")


def test_v84_has_only_categorical_htf_states():
    assert HTF_STATES == (
        "NONE",
        "PREV_WEEK_LOW_RECLAIM",
        "PREV_MONTH_LOW_RECLAIM",
        "BOTH_RECLAIM",
        "UNAVAILABLE",
    )
    src=(ROOT / "src/fx_scanner/research_xau_v47_htf_liquidity_v84.py").read_text()
    assert '"numeric_thresholds_added": False' in src
    assert '"trade_filter_applied": False' in src
    assert '"state_selected_as_winner": False' in src
    assert '"v69_forward_contract_changed": False' in src


def test_v84_has_no_execution_path():
    src=(ROOT / "src/fx_scanner/research_xau_v47_htf_liquidity_v84.py").read_text()
    runtime=(ROOT / "src/fx_scanner/research_xau_v47_htf_liquidity_v84_runtime.py").read_text()
    combined=src+"\n"+runtime
    assert "send_new_order" not in combined
    assert "claim_signal_for_execution" not in combined
    assert '"execution_authority": False' in src

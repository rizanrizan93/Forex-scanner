from pathlib import Path

from fx_scanner.research_xau_h1_volatility_state_v63 import (
    DIAGNOSTIC_ONLY,
    EXECUTION_INFLUENCE,
    FAMILY_IDS,
    H1_ATR_PERIOD,
    POLICY_EFFECT,
    PRIOR_WINDOW_H1,
    PROMOTION_ELIGIBLE,
    VOL_STATES,
)

ROOT = Path(__file__).resolve().parents[1]


def test_v63_is_diagnostic_only():
    assert POLICY_EFFECT == "SHADOW_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False
    assert DIAGNOSTIC_ONLY is True


def test_v63_quintiles_are_frozen_and_causal():
    assert H1_ATR_PERIOD == 14
    assert PRIOR_WINDOW_H1 == 120
    assert VOL_STATES == (
        "Q1_LOW",
        "Q2",
        "Q3",
        "Q4",
        "Q5_HIGH",
        "UNAVAILABLE",
    )
    assert set(FAMILY_IDS) == {"L12", "L20"}


def test_v63_does_not_filter_or_execute():
    src = (ROOT / "src/fx_scanner/research_xau_h1_volatility_state_v63.py").read_text()
    runtime = (
        ROOT / "src/fx_scanner/research_xau_h1_volatility_state_v63_runtime.py"
    ).read_text()
    combined = src + "\n" + runtime
    assert "send_new_order" not in combined
    assert '"entry_signal_logic_retuned": False' in src
    assert '"trade_filter_applied": False' in src
    assert '"quintile_selected_as_winner": False' in src
    assert '"threshold_grid_search": False' in src
    assert '"selection_uses_future_outcomes": False' in src

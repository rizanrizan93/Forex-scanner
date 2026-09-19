from pathlib import Path

from fx_scanner.research_xau_realized_skew_state_v64 import (
    DIAGNOSTIC_ONLY,
    EXECUTION_INFLUENCE,
    FAMILY_IDS,
    POLICY_EFFECT,
    PRIOR_DAYS_WINDOW,
    PROMOTION_ELIGIBLE,
    SKEW_STATES,
)

ROOT = Path(__file__).resolve().parents[1]


def test_v64_is_diagnostic_only():
    assert POLICY_EFFECT == "SHADOW_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False
    assert DIAGNOSTIC_ONLY is True


def test_v64_uses_prior_day_skew_quintiles():
    assert PRIOR_DAYS_WINDOW == 120
    assert SKEW_STATES == (
        "Q1_MOST_NEGATIVE",
        "Q2",
        "Q3",
        "Q4",
        "Q5_MOST_POSITIVE",
        "UNAVAILABLE",
    )
    assert set(FAMILY_IDS) == {"L12", "L20"}


def test_v64_does_not_filter_or_execute():
    src = (ROOT / "src/fx_scanner/research_xau_realized_skew_state_v64.py").read_text()
    runtime = (
        ROOT / "src/fx_scanner/research_xau_realized_skew_state_v64_runtime.py"
    ).read_text()
    combined = src + "\n" + runtime
    assert "send_new_order" not in combined
    assert '"entry_signal_logic_retuned": False' in src
    assert '"trade_filter_applied": False' in src
    assert '"skew_quintile_selected_as_winner": False' in src
    assert '"threshold_grid_search": False' in src
    assert '"selection_uses_future_outcomes": False' in src

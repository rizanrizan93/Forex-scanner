from pathlib import Path

from fx_scanner.research_xau_session_causal_router_v53 import (
    DIRECTIONS,
    EXECUTION_INFLUENCE,
    LOOKBACK_TRADING_DAYS,
    MIN_COMPLETED_TRADES,
    MIN_TRAILING_EXPECTANCY_R,
    MIN_TRAILING_PF,
    POLICY_EFFECT,
    PROMOTION_ELIGIBLE,
    SELECTED_VARIANT_IDS,
    TARGET_SESSIONS,
)

ROOT = Path(__file__).resolve().parents[1]


def test_v53_is_shadow_only():
    assert POLICY_EFFECT == "SHADOW_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False


def test_v53_uses_frozen_gate_and_v3_families():
    assert LOOKBACK_TRADING_DAYS == 126
    assert MIN_COMPLETED_TRADES == 30
    assert MIN_TRAILING_PF == 1.10
    assert MIN_TRAILING_EXPECTANCY_R == 0.05
    assert SELECTED_VARIANT_IDS == (
        "XAU_V3_EUUS_REVERSAL_R15",
        "XAU_V3_EUUS_BREAKOUT_R15",
        "XAU_V3_EUUS_ADAPT_R20",
    )


def test_v53_gates_session_and_direction_independently():
    assert TARGET_SESSIONS == ("EUROPE", "US")
    assert DIRECTIONS == ("LONG", "SHORT")


def test_v53_does_not_retune_or_execute():
    src = (ROOT / "src/fx_scanner/research_xau_session_causal_router_v53.py").read_text()
    runtime = (
        ROOT / "src/fx_scanner/research_xau_session_causal_router_v53_runtime.py"
    ).read_text()
    combined = src + "\n" + runtime
    assert "send_new_order" not in combined
    assert '"session_hours_retuned": False' in src
    assert '"v3_signal_geometry_retuned": False' in src
    assert '"threshold_grid_search": False' in src
    assert '"selection_uses_future_outcomes": False' in src

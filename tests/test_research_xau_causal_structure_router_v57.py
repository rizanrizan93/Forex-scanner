from pathlib import Path

from fx_scanner.research_xau_causal_structure_router_v57 import (
    BASE_ROUTE,
    BREAK_STREAMS,
    EXECUTION_INFLUENCE,
    LOOKBACK_TRADING_DAYS,
    MIN_COMPLETED_TRADES,
    MIN_TRAILING_EXPECTANCY_R,
    MIN_TRAILING_PF,
    POLICY_EFFECT,
    PROMOTION_ELIGIBLE,
    ROUTER_TYPES,
    STRUCTURE_STREAMS,
)

ROOT = Path(__file__).resolve().parents[1]


def test_v57_is_shadow_only():
    assert POLICY_EFFECT == "SHADOW_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False


def test_v57_uses_broader_frozen_route_without_preselecting_mss():
    assert BASE_ROUTE == "LONG_REACCEL_COST10"
    assert ROUTER_TYPES == ("BREAK_EVENT", "STRUCTURE_STATE")
    assert "BULL_MSS" in BREAK_STREAMS
    assert "BULL_BOS" in BREAK_STREAMS
    assert "BULL_HH_HL" in STRUCTURE_STREAMS
    assert "BEAR_LH_LL" in STRUCTURE_STREAMS


def test_v57_uses_unchanged_causal_gate():
    assert LOOKBACK_TRADING_DAYS == 126
    assert MIN_COMPLETED_TRADES == 30
    assert MIN_TRAILING_PF == 1.10
    assert MIN_TRAILING_EXPECTANCY_R == 0.05


def test_v57_does_not_hardcode_winner_or_execute():
    src = (ROOT / "src/fx_scanner/research_xau_causal_structure_router_v57.py").read_text()
    runtime = (
        ROOT / "src/fx_scanner/research_xau_causal_structure_router_v57_runtime.py"
    ).read_text()
    combined = src + "\n" + runtime
    assert "send_new_order" not in combined
    assert '"no_stream_preselected_as_winner": True' in src
    assert '"pivot_definition_identical_to_v56": True' in src
    assert '"signal_logic_retuned": False' in src
    assert '"threshold_grid_search": False' in src
    assert '"selection_uses_future_outcomes": False' in src

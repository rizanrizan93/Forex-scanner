from pathlib import Path

from fx_scanner.research_xau_causal_cascade_gate_v52 import (
    DIRECTIONS,
    DISCOVERY_VARIANTS,
    EXECUTION_INFLUENCE,
    LOOKBACK_TRADING_DAYS,
    MIN_COMPLETED_TRADES,
    MIN_TRAILING_EXPECTANCY_R,
    MIN_TRAILING_PF,
    POLICY_EFFECT,
    PROMOTION_ELIGIBLE,
)

ROOT = Path(__file__).resolve().parents[1]


def test_v52_is_shadow_only():
    assert POLICY_EFFECT == "SHADOW_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False


def test_v52_uses_frozen_v40_v47_gate():
    assert LOOKBACK_TRADING_DAYS == 126
    assert MIN_COMPLETED_TRADES == 30
    assert MIN_TRAILING_PF == 1.10
    assert MIN_TRAILING_EXPECTANCY_R == 0.05


def test_v52_bounds_discovery_and_direction_streams():
    assert DISCOVERY_VARIANTS == (
        "PD_CASCADE_D1_H1_2R",
        "PD_CASCADE_D1_H1_RANGE_CREDIBLE_2R",
    )
    assert DIRECTIONS == ("LONG", "SHORT")


def test_v52_does_not_retune_or_execute():
    src = (ROOT / "src/fx_scanner/research_xau_causal_cascade_gate_v52.py").read_text()
    runtime = (
        ROOT / "src/fx_scanner/research_xau_causal_cascade_gate_v52_runtime.py"
    ).read_text()
    combined = src + "\n" + runtime
    assert "send_new_order" not in combined
    assert '"gate_thresholds_identical_to_v40_v47": True' in src
    assert '"v51_entry_geometry_retuned": False' in src
    assert '"threshold_grid_search": False' in src
    assert '"selection_uses_future_outcomes": False' in src

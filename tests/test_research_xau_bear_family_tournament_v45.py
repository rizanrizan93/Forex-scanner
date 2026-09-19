from pathlib import Path

from fx_scanner.research_xau_bear_family_tournament_v45 import (
    COST_MODES,
    COST_R_CAP,
    EXECUTION_INFLUENCE,
    FAMILIES,
    HOLD_BARS,
    POLICY_EFFECT,
    PROMOTION_ELIGIBLE,
)
from fx_scanner.research_xau_m15_dual_strategy import (
    EMA_STRATEGY_ID,
    MAX_HOLD_BARS,
    SWEEP_STRATEGY_ID,
)

ROOT = Path(__file__).resolve().parents[1]


def test_v45_is_shadow_only():
    assert POLICY_EFFECT == "SHADOW_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False


def test_v45_uses_only_frozen_existing_families_and_holds():
    assert FAMILIES == (EMA_STRATEGY_ID, SWEEP_STRATEGY_ID)
    assert HOLD_BARS == tuple(MAX_HOLD_BARS)
    assert HOLD_BARS == (16, 32, 64, 96)


def test_v45_cost_modes_are_bounded():
    assert COST_MODES == ("RAW", "COST10")
    assert COST_R_CAP == 0.10


def test_v45_has_no_execution_or_retune_path():
    src = (ROOT / "src/fx_scanner/research_xau_bear_family_tournament_v45.py").read_text()
    runtime = (
        ROOT / "src/fx_scanner/research_xau_bear_family_tournament_v45_runtime.py"
    ).read_text()
    combined = src + "\n" + runtime
    assert "send_new_order" not in combined
    assert '"signal_logic_retuned": False' in src
    assert '"stop_target_retuned": False' in src
    assert '"hold_horizons_newly_invented": False' in src
    assert '"dense_grid_search": False' in src
    assert '"selection_uses_future_outcomes": False' in src

from pathlib import Path

from fx_scanner.research_xau_nested_event_router_v62 import (
    DIAGNOSTIC_ONLY,
    EVENT_STREAMS,
    EXECUTION_INFLUENCE,
    MIN_COMPLETED_TRADES,
    MIN_TRAILING_EXPECTANCY_R,
    MIN_TRAILING_PF,
    POLICY_EFFECT,
    PROMOTION_ELIGIBLE,
    REQUIRED_COSTS,
)
from fx_scanner.research_xau_h1_event_stability_v61 import FROZEN_ROUTE

ROOT = Path(__file__).resolve().parents[1]


def test_v62_is_shadow_only():
    assert POLICY_EFFECT == "SHADOW_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False
    assert DIAGNOSTIC_ONLY is True


def test_v62_preserves_v47_and_all_event_streams():
    assert FROZEN_ROUTE == "SECULAR_BULL_REACCEL_LONG_COST10"
    assert REQUIRED_COSTS == ("LOW_1700", "V24_STRESS_4675")
    assert set(EVENT_STREAMS) == {
        "BULL_MSS",
        "BULL_BOS",
        "BEAR_MSS",
        "BEAR_BOS",
        "NONE",
    }


def test_v62_reuses_frozen_health_thresholds():
    assert MIN_COMPLETED_TRADES == 30
    assert MIN_TRAILING_PF == 1.10
    assert MIN_TRAILING_EXPECTANCY_R == 0.05


def test_v62_structure_can_only_suppress():
    src = (ROOT / "src/fx_scanner/research_xau_nested_event_router_v62.py").read_text()
    runtime = (
        ROOT / "src/fx_scanner/research_xau_nested_event_router_v62_runtime.py"
    ).read_text()
    combined = src + "\n" + runtime
    assert "send_new_order" not in combined
    assert '"no_event_preselected_as_winner": True' in src
    assert '"market_structure_can_only_suppress_v47_trades": True' in src
    assert '"market_structure_cannot_open_new_v47_ineligible_trades": True' in src
    assert '"threshold_grid_search": False' in src
    assert '"selection_uses_future_outcomes": False' in src

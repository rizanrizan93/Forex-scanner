from pathlib import Path

from fx_scanner.research_xau_round_number_barrier_v54 import (
    COOLDOWN_BARS_PER_EVENT,
    EVENT_KINDS,
    EXECUTION_INFLUENCE,
    FORWARD_HORIZONS,
    MAJOR_STEP,
    MINOR_STEP,
    POLICY_EFFECT,
    PROMOTION_ELIGIBLE,
)

ROOT = Path(__file__).resolve().parents[1]


def test_v54_is_diagnostic_only():
    assert POLICY_EFFECT == "SHADOW_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False


def test_v54_barriers_and_horizons_are_preregistered():
    assert MAJOR_STEP == 100.0
    assert MINOR_STEP == 10.0
    assert FORWARD_HORIZONS == (1, 4, 16)
    assert COOLDOWN_BARS_PER_EVENT == 16
    assert EVENT_KINDS == (
        "UP_CROSS",
        "DOWN_CROSS",
        "REJECT_FROM_BELOW",
        "REJECT_FROM_ABOVE",
    )


def test_v54_does_not_create_execution_or_directional_strategy():
    src = (ROOT / "src/fx_scanner/research_xau_round_number_barrier_v54.py").read_text()
    runtime = (
        ROOT / "src/fx_scanner/research_xau_round_number_barrier_v54_runtime.py"
    ).read_text()
    combined = src + "\n" + runtime
    assert "send_new_order" not in combined
    assert '"directional_trade_rule_created": False' in src
    assert '"threshold_grid_search": False' in src
    assert '"selection_uses_future_outcomes": False' in src
    assert '"execution_authority": False' in src

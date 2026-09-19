from pathlib import Path

from fx_scanner.research_xau_external_liquidity_cascade_v51 import (
    BODY_ATR_MIN,
    CLOSE_LOCATION_MIN,
    COOLDOWN_BARS,
    EXECUTION_INFLUENCE,
    MAX_HOLD_BARS,
    MIN_RISK_ATR,
    POLICY_EFFECT,
    PROMOTION_ELIGIBLE,
    STOP_BUFFER_ATR,
    TARGET_R,
    VARIANTS,
)

ROOT = Path(__file__).resolve().parents[1]


def test_v51_is_shadow_only():
    assert POLICY_EFFECT == "SHADOW_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False


def test_v51_reuses_frozen_breakout_geometry():
    assert BODY_ATR_MIN == 0.55
    assert CLOSE_LOCATION_MIN == 0.68
    assert STOP_BUFFER_ATR == 0.15
    assert MIN_RISK_ATR == 0.50
    assert COOLDOWN_BARS == 4
    assert TARGET_R == 2.0
    assert MAX_HOLD_BARS == 16


def test_v51_variants_are_bounded():
    assert VARIANTS == (
        "PD_CASCADE_2R_CONTROL",
        "PD_CASCADE_H1_NORMAL_2R",
        "PD_CASCADE_D1_MATCH_2R",
        "PD_CASCADE_D1_H1_2R",
        "PD_CASCADE_D1_H1_RANGE_CREDIBLE_2R",
    )


def test_v51_has_no_execution_or_grid_tuning():
    src = (
        ROOT / "src/fx_scanner/research_xau_external_liquidity_cascade_v51.py"
    ).read_text()
    runtime = (
        ROOT / "src/fx_scanner/research_xau_external_liquidity_cascade_v51_runtime.py"
    ).read_text()
    combined = src + "\n" + runtime
    assert "send_new_order" not in combined
    assert '"parameter_grid_search": False' in src
    assert '"selection_uses_future_outcomes": False' in src
    assert '"execution_authority": False' in src

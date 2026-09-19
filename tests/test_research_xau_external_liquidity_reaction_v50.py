from pathlib import Path

from fx_scanner.research_xau_external_liquidity_reaction_v50 import (
    COST_R_CAP,
    EXECUTION_INFLUENCE,
    MAX_HOLD_BARS,
    MSS_CONFIRM_BARS,
    POLICY_EFFECT,
    PROMOTION_ELIGIBLE,
    RANGE_LOOKBACK_DAYS,
    TARGET_R,
    VARIANTS,
)

ROOT = Path(__file__).resolve().parents[1]


def test_v50_is_shadow_only():
    assert POLICY_EFFECT == "SHADOW_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False


def test_v50_preregistered_geometry_is_bounded():
    assert MSS_CONFIRM_BARS == 4
    assert TARGET_R == 2.0
    assert RANGE_LOOKBACK_DAYS == 60
    assert MAX_HOLD_BARS == 32
    assert COST_R_CAP == 0.10


def test_v50_has_incremental_controls():
    assert VARIANTS == (
        "PD_SWEEP_RECLAIM_2R_CONTROL",
        "PD_SWEEP_MSS_2R",
        "PD_SWEEP_MSS_D1_ALIGNED_2R",
        "PD_SWEEP_MSS_RANGE_CREDIBLE_2R",
        "PD_SWEEP_MSS_D1_ALIGNED_RANGE_CREDIBLE_2R",
    )


def test_v50_does_not_claim_proprietary_replication_or_execute():
    src = (
        ROOT / "src/fx_scanner/research_xau_external_liquidity_reaction_v50.py"
    ).read_text()
    runtime = (
        ROOT / "src/fx_scanner/research_xau_external_liquidity_reaction_v50_runtime.py"
    ).read_text()
    combined = src + "\n" + runtime
    assert "send_new_order" not in combined
    assert '"airv3_replication_claimed": False' in src
    assert '"parameter_grid_search": False' in src
    assert '"selection_uses_future_outcomes": False' in src
    assert '"execution_authority": False' in src

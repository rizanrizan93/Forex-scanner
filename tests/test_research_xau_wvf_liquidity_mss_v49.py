from pathlib import Path

from fx_scanner.research_xau_wvf_liquidity_mss_v49 import (
    COST_R_CAP,
    EXECUTION_INFLUENCE,
    MAX_HOLD_BARS,
    MSS_CONFIRM_BARS,
    POLICY_EFFECT,
    PROMOTION_ELIGIBLE,
    TARGET_R,
    VARIANTS,
    WVF_LOOKBACK_H1,
    WVF_PERCENTILE,
    WVF_PERCENTILE_WINDOW,
)

ROOT = Path(__file__).resolve().parents[1]


def test_v49_is_research_only_and_long_first():
    assert POLICY_EFFECT == "SHADOW_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False
    assert len(VARIANTS) == 5
    assert all("SHORT" not in x for x in VARIANTS)


def test_v49_preregistered_contract_is_bounded():
    assert WVF_LOOKBACK_H1 == 22
    assert WVF_PERCENTILE_WINDOW == 50
    assert WVF_PERCENTILE == 0.85
    assert MSS_CONFIRM_BARS == 4
    assert TARGET_R == 1.80
    assert MAX_HOLD_BARS == 32
    assert COST_R_CAP == 0.10


def test_v49_has_control_and_incremental_layers():
    assert VARIANTS == (
        "SWEEP_RECLAIM_LONG_CONTROL",
        "WVF_SWEEP_RECLAIM_LONG",
        "WVF_SWEEP_MSS_LONG",
        "WVF_SWEEP_MSS_D1_NONBEAR_LONG",
        "WVF_SWEEP_MSS_D1_BULL_LONG",
    )


def test_v49_no_execution_or_grid_tuning():
    src = (ROOT / "src/fx_scanner/research_xau_wvf_liquidity_mss_v49.py").read_text()
    runtime = (
        ROOT / "src/fx_scanner/research_xau_wvf_liquidity_mss_v49_runtime.py"
    ).read_text()
    combined = src + "\n" + runtime
    assert "send_new_order" not in combined
    assert '"parameter_grid_search": False' in src
    assert '"selection_uses_future_outcomes": False' in src
    assert '"execution_authority": False' in src

from pathlib import Path

from fx_scanner.research_xau_v47_direct_sweep_entry_v85 import (
    COST_R_CAP,
    DIAGNOSTIC_ONLY,
    DIRECT_VARIANTS,
    EXECUTION_INFLUENCE,
    FROZEN_ROUTE,
    POLICY_EFFECT,
    PROMOTION_ELIGIBLE,
)

ROOT=Path(__file__).resolve().parents[1]


def test_v85_is_shadow_only():
    assert POLICY_EFFECT=="SHADOW_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False
    assert DIAGNOSTIC_ONLY is True
    assert FROZEN_ROUTE=="SECULAR_BULL_REACCEL_LONG_COST10"


def test_v85_inherits_only_frozen_family_reward_and_cooldown():
    assert DIRECT_VARIANTS["L12"]=={
        "variant_id":"V85_DIRECT_SWEEP_L12_R150",
        "reward_r":1.50,
        "cooldown_bars":3,
    }
    assert DIRECT_VARIANTS["L20"]=={
        "variant_id":"V85_DIRECT_SWEEP_L20_R200",
        "reward_r":2.00,
        "cooldown_bars":4,
    }
    assert COST_R_CAP==0.10


def test_v85_no_parameter_search_or_execution():
    src=(ROOT/"src/fx_scanner/research_xau_v47_direct_sweep_entry_v85.py").read_text()
    runtime=(ROOT/"src/fx_scanner/research_xau_v47_direct_sweep_entry_v85_runtime.py").read_text()
    combined=src+"\n"+runtime
    assert '"current_bar_sweep_only": True' in src
    assert '"post_sweep_displacement_required": False' in src
    assert '"fvg_required": False' in src
    assert '"target_grid_search": False' in src
    assert '"stop_grid_search": False' in src
    assert '"v69_forward_contract_changed": False' in src
    assert "send_new_order" not in combined
    assert "claim_signal_for_execution" not in combined

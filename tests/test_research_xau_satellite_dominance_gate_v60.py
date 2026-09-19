from pathlib import Path

from fx_scanner.research_xau_satellite_dominance_gate_v60 import (
    DIAGNOSTIC_ONLY,
    EXECUTION_INFLUENCE,
    POLICY_EFFECT,
    PROMOTION_ELIGIBLE,
    REQUIRED_COSTS,
)

ROOT = Path(__file__).resolve().parents[1]


def test_v60_is_shadow_only_and_requires_both_costs():
    assert POLICY_EFFECT == "SHADOW_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False
    assert DIAGNOSTIC_ONLY is True
    assert REQUIRED_COSTS == ("LOW_1700", "V24_STRESS_4675")


def test_v60_uses_zero_threshold_dominance_not_v59_tuning():
    src = (
        ROOT / "src/fx_scanner/research_xau_satellite_dominance_gate_v60.py"
    ).read_text()
    assert '"numeric_thresholds_tuned_from_v59": False' in src
    assert '"v48_original_absolute_gate_replaced": False' in src
    assert '"strategy_retuned": False' in src


def test_v60_has_no_execution_path():
    src = (
        ROOT / "src/fx_scanner/research_xau_satellite_dominance_gate_v60.py"
    ).read_text()
    runtime = (
        ROOT / "src/fx_scanner/research_xau_satellite_dominance_gate_v60_runtime.py"
    ).read_text()
    combined = src + "\n" + runtime
    assert "send_new_order" not in combined
    assert '"execution_authority": False' in src

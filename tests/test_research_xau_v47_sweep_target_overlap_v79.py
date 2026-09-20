from fx_scanner.research_xau_v47_sweep_target_overlap_v79 import (
    CELLS,
    DIAGNOSTIC_ONLY,
    EXECUTION_INFLUENCE,
    POLICY_EFFECT,
    PROMOTION_ELIGIBLE,
    REQUIRED_COSTS,
    TARGET_THRESHOLD,
    _phi,
)


def test_v79_is_dependency_audit_only():
    assert POLICY_EFFECT == "SHADOW_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False
    assert DIAGNOSTIC_ONLY is True
    assert REQUIRED_COSTS == ("LOW_1700", "V24_STRESS_4675")
    assert TARGET_THRESHOLD == 0.75
    assert "SWEEP_TARGET_GT" in CELLS
    assert "NONSWEEP_TARGET_LE" in CELLS


def test_v79_phi_zero_when_independent_counts():
    counts = {
        "SWEEP_TARGET_GT": 25,
        "SWEEP_TARGET_LE": 25,
        "NONSWEEP_TARGET_GT": 25,
        "NONSWEEP_TARGET_LE": 25,
    }
    assert abs(float(_phi(counts))) < 1e-12


def test_v79_phi_positive_when_sweep_and_wide_target_cluster():
    counts = {
        "SWEEP_TARGET_GT": 40,
        "SWEEP_TARGET_LE": 10,
        "NONSWEEP_TARGET_GT": 10,
        "NONSWEEP_TARGET_LE": 40,
    }
    assert float(_phi(counts)) > 0.0

from pathlib import Path

from fx_scanner.research_xau_v47_frozen_validation_v48 import (
    EXECUTION_INFLUENCE,
    FROZEN_ROUTE,
    POLICY_EFFECT,
    PROMOTION_ELIGIBLE,
    VALIDATION_COST_IDS,
)

ROOT = Path(__file__).resolve().parents[1]


def test_v48_is_research_only():
    assert POLICY_EFFECT == "SHADOW_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False


def test_v48_freezes_one_v47_candidate():
    assert FROZEN_ROUTE == "SECULAR_BULL_REACCEL_LONG_COST10"
    assert VALIDATION_COST_IDS == ("LOW_1700", "V24_STRESS_4675")


def test_v48_has_no_execution_or_retuning_path():
    src = (ROOT / "src/fx_scanner/research_xau_v47_frozen_validation_v48.py").read_text()
    runtime = (
        ROOT / "src/fx_scanner/research_xau_v47_frozen_validation_v48_runtime.py"
    ).read_text()
    combined = src + "\n" + runtime
    assert "send_new_order" not in combined
    assert '"parameter_retuning": False' in src
    assert '"gate_logic": "V47_UNCHANGED"' in src
    assert "promotion_eligible" in combined.lower()

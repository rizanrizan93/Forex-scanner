from pathlib import Path

from fx_scanner.research_xau_satellite_attribution_v59 import (
    DIAGNOSTIC_ONLY,
    EXECUTION_INFLUENCE,
    POLICY_EFFECT,
    PROMOTION_ELIGIBLE,
)
from fx_scanner.research_xau_v47_frozen_validation_v48 import FROZEN_ROUTE

ROOT = Path(__file__).resolve().parents[1]


def test_v59_is_attribution_only():
    assert POLICY_EFFECT == "SHADOW_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False
    assert DIAGNOSTIC_ONLY is True


def test_v59_keeps_v48_frozen_candidate():
    assert FROZEN_ROUTE == "SECULAR_BULL_REACCEL_LONG_COST10"


def test_v59_does_not_relax_v48_gate_or_execute():
    src = (
        ROOT / "src/fx_scanner/research_xau_satellite_attribution_v59.py"
    ).read_text()
    runtime = (
        ROOT / "src/fx_scanner/research_xau_satellite_attribution_v59_runtime.py"
    ).read_text()
    combined = src + "\n" + runtime
    assert "send_new_order" not in combined
    assert '"strategy_or_threshold_retuning": False' in src
    assert "does not replace or relax the V48" in src

from pathlib import Path

from fx_scanner.research_xau_round_number_geometry_v55 import (
    EXECUTION_INFLUENCE,
    FROZEN_ROUTE,
    MAJOR_STEP,
    MINOR_STEP,
    POLICY_EFFECT,
    PROMOTION_ELIGIBLE,
)

ROOT = Path(__file__).resolve().parents[1]


def test_v55_is_diagnostic_only():
    assert POLICY_EFFECT == "SHADOW_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False


def test_v55_freezes_candidate_and_barrier_levels():
    assert FROZEN_ROUTE == "SECULAR_BULL_REACCEL_LONG_COST10"
    assert MAJOR_STEP == 100.0
    assert MINOR_STEP == 10.0


def test_v55_has_no_filter_or_execution_path():
    src = (ROOT / "src/fx_scanner/research_xau_round_number_geometry_v55.py").read_text()
    runtime = (
        ROOT / "src/fx_scanner/research_xau_round_number_geometry_v55_runtime.py"
    ).read_text()
    combined = src + "\n" + runtime
    assert "send_new_order" not in combined
    assert '"trade_filter_applied": False' in src
    assert '"target_or_stop_modified": False' in src
    assert '"threshold_grid_search": False' in src
    assert '"selection_uses_future_outcomes": False' in src

from datetime import datetime, timedelta, timezone
from pathlib import Path

from fx_scanner.models import Bar
from fx_scanner.research_xau_cost_viability_router_v43 import (
    COST_R_LIMITS,
    EXECUTION_INFLUENCE,
    POLICY_EFFECT,
    PROMOTION_ELIGIBLE,
    ROUTES,
    _friction_pips,
)
from fx_scanner.research_xau_m15_dual_strategy import M15ResearchCosts

ROOT = Path(__file__).resolve().parents[1]
UTC = timezone.utc


def test_v43_is_research_only():
    assert POLICY_EFFECT == "SHADOW_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False


def test_v43_cost_ladder_is_small_and_preregistered():
    assert COST_R_LIMITS == (0.20, 0.15, 0.10)
    assert len(ROUTES) == 7
    assert "REACCEL_1_20_NORMAL_COST20" in ROUTES
    assert "REACCEL_1_20_NORMAL_COST15" in ROUTES
    assert "REACCEL_1_20_NORMAL_COST10" in ROUTES


def test_friction_formula_is_entry_known():
    costs = M15ResearchCosts(
        spread_pips=37.0,
        slippage_pips=0.2,
        commission_pips_round_trip=0.2,
        swap_pips_per_day=0.0,
        spread_multiplier=1.25,
        slippage_multiplier=1.50,
    )
    assert abs(_friction_pips(costs) - 46.75) < 1e-9


def test_v43_contract_has_no_future_outcome_gate_or_execution_path():
    src = (ROOT / "src/fx_scanner/research_xau_cost_viability_router_v43.py").read_text()
    runtime = (
        ROOT / "src/fx_scanner/research_xau_cost_viability_router_v43_runtime.py"
    ).read_text()
    combined = src + "\n" + runtime
    assert "send_new_order" not in combined
    assert '"cost_gate_is_ex_ante": True' in src
    assert '"swap_excluded_from_entry_gate": True' in src
    assert '"dense_grid_search": False' in src
    assert '"selection_uses_future_outcomes": False' in src

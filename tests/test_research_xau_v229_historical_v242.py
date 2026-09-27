from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd

from fx_scanner.research_xau_v229_historical_v242 import (
    BASE_SLIPPAGE_PIPS,
    BASE_SPREAD_PIPS,
    COMMISSION_PIPS_ROUND_TRIP,
    EXECUTION_AUTHORITY,
    EXECUTION_INFLUENCE,
    FROZEN_LADDER_DEPTHS,
    LIVE_EXECUTION_ENABLED,
    PIP_SIZE,
    SYMBOL,
    _depth_price,
    _simulate_limit_trade,
    price_arrays,
)
from fx_scanner.research_xau_v229_historical_v242_aggregate import (
    CONFIGURED_ACCEPTANCE,
    _numeric_gate,
)

ROOT = Path(__file__).resolve().parents[1]


def test_v242_xau_cost_and_symbol_contract() -> None:
    assert SYMBOL == "XAUUSD"
    assert PIP_SIZE == 0.01
    assert BASE_SPREAD_PIPS == 37.0
    assert BASE_SLIPPAGE_PIPS == 0.2
    assert COMMISSION_PIPS_ROUND_TRIP == 0.2


def test_v242_uses_current_frozen_four_slot_depth_prior() -> None:
    assert set(FROZEN_LADDER_DEPTHS) == {
        ("H4", "LONG"), ("H4", "SHORT"),
        ("H1", "LONG"), ("H1", "SHORT"),
        ("M15", "LONG"), ("M15", "SHORT"),
    }
    assert all(len(values) == 4 for values in FROZEN_LADDER_DEPTHS.values())
    assert all(tuple(values) == tuple(sorted(values)) for values in FROZEN_LADDER_DEPTHS.values())


def test_v242_depth_price_direction() -> None:
    assert _depth_price("LONG", 4300.0, 4400.0, 0.0) == 4400.0
    assert _depth_price("LONG", 4300.0, 4400.0, 1.0) == 4300.0
    assert _depth_price("SHORT", 4300.0, 4400.0, 0.0) == 4300.0
    assert _depth_price("SHORT", 4300.0, 4400.0, 1.0) == 4400.0


def test_v242_rejects_target_crossed_after_costs() -> None:
    start = datetime(2026, 1, 5, 0, 0, tzinfo=UTC)
    frame = pd.DataFrame(
        [
            {
                "timestamp": start + timedelta(minutes=1),
                "open": 4300.0,
                "high": 4300.5,
                "low": 4299.5,
                "close": 4300.0,
            }
        ]
    )
    result = _simulate_limit_trade(
        px=price_arrays(frame),
        direction="LONG",
        order_at=start,
        expires_at=start + timedelta(minutes=10),
        entry=4300.0,
        stop=4290.0,
        target=4300.05,
        spread_pips=37.0,
        slippage_pips=0.2,
        commission_pips=0.2,
    )
    assert result["state"] == "REJECTED"
    assert result["reason"] == "INVALID_TARGET_AFTER_COSTS"


def test_v242_configured_numeric_gate_contract() -> None:
    assert CONFIGURED_ACCEPTANCE == {
        "win_rate_min": 0.55,
        "profit_factor_min": 1.30,
        "expectancy_r_min": 0.15,
        "aggregate_trades_min": 250,
    }
    good = _numeric_gate(
        {
            "completed": 300,
            "win_rate": 0.56,
            "profit_factor_r": 1.31,
            "expectancy_r": 0.16,
        }
    )
    assert good["all_numeric_gates_met"] is True
    weak_pf = _numeric_gate(
        {
            "completed": 300,
            "win_rate": 0.56,
            "profit_factor_r": 1.29,
            "expectancy_r": 0.16,
        }
    )
    assert weak_pf["all_numeric_gates_met"] is False


def test_v242_is_retrospective_shadow_not_oos_authority() -> None:
    assert EXECUTION_INFLUENCE is False
    assert EXECUTION_AUTHORITY is False
    assert LIVE_EXECUTION_ENABLED is False
    source = (
        ROOT / "src/fx_scanner/research_xau_v229_historical_v242_aggregate.py"
    ).read_text(encoding="utf-8")
    assert "RETROSPECTIVE_CURRENT_PARAMETER_REPLAY_NOT_INDEPENDENT_OOS" in source
    assert '"independent_oos_pass": False' in source
    assert '"model_performance_persistence_eligible": False' in source

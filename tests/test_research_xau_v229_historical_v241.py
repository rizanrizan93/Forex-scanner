from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd

from fx_scanner.research_xau_v229_historical_v241 import (
    BASE_SLIPPAGE_PIPS,
    BASE_SPREAD_PIPS,
    CHILD_LOT,
    CHILD_UNITS,
    COMMISSION_PIPS_ROUND_TRIP,
    CONTRACT_UNITS_PER_LOT,
    EXECUTION_AUTHORITY,
    EXECUTION_INFLUENCE,
    FROZEN_LADDER_DEPTHS,
    LIVE_EXECUTION_ENABLED,
    PIP_SIZE,
    SYMBOL,
    _simulate_limit_trade,
    account_ledger,
    price_arrays,
)

ROOT = Path(__file__).resolve().parents[1]


def test_v241_xau_contract_and_raw_cost_model() -> None:
    assert SYMBOL == "XAUUSD"
    assert PIP_SIZE == 0.01
    assert CHILD_LOT == 0.01
    assert CONTRACT_UNITS_PER_LOT == 100.0
    assert CHILD_UNITS == 1.0
    assert BASE_SPREAD_PIPS == 11.0
    assert BASE_SLIPPAGE_PIPS == 5.0
    assert COMMISSION_PIPS_ROUND_TRIP == 6.0


def test_v241_uses_current_xau_v225_depth_ladder_as_diagnostic() -> None:
    assert set(FROZEN_LADDER_DEPTHS) == {
        ("H4", "LONG"),
        ("H4", "SHORT"),
        ("H1", "LONG"),
        ("H1", "SHORT"),
        ("M15", "LONG"),
        ("M15", "SHORT"),
    }
    assert all(len(values) == 4 for values in FROZEN_LADDER_DEPTHS.values())


def test_v241_target_after_fill_guard_is_inherited() -> None:
    start = datetime(2026, 1, 5, 0, 0, tzinfo=UTC)
    frame = pd.DataFrame(
        [
            {
                "timestamp": start + timedelta(minutes=1),
                "open": 4000.00,
                "high": 4000.10,
                "low": 3999.90,
                "close": 4000.00,
            }
        ]
    )
    result = _simulate_limit_trade(
        px=price_arrays(frame),
        direction="LONG",
        order_at=start,
        expires_at=start + timedelta(minutes=10),
        entry=4000.00,
        stop=3990.00,
        target=4000.01,
        spread_pips=11.0,
        slippage_pips=5.0,
        commission_pips=6.0,
    )
    assert result["state"] == "REJECTED"
    assert result["reason"] == "INVALID_TARGET_AFTER_COSTS"


def _trade(index: int) -> dict:
    start = datetime(2026, 1, 5, 0, 0, tzinfo=UTC)
    return {
        "plan_id": f"P{index}",
        "slot": 1,
        "state": "WIN",
        "entry_at": (start + timedelta(minutes=index)).isoformat(),
        "exit_at": (start + timedelta(hours=2)).isoformat(),
        "fill_price": 4000.0,
        "planned_entry": 4000.0,
        "net_pnl_usd": 10.0,
        "net_r": 1.0,
        "mae_r": 0.2,
        "mfe_r": 1.2,
    }


def test_v241_100_usd_margin_cap_reflects_one_ounce_child() -> None:
    rows = [_trade(i) for i in range(3)]
    result = account_ledger(
        rows,
        initial_balance=100.0,
        leverage=100.0,
        margin_cap_fraction=0.50,
    )
    # 0.01 lot = 1 oz; at $4,000 and 1:100 each child requires $40 margin.
    assert result["accepted_trades"] == 1
    assert result["margin_rejected"] == 2
    assert result["max_used_margin_usd"] == 40.0
    assert result["ending_balance"] == 110.0


def test_v241_is_explicitly_shadow_and_in_sample_diagnostic() -> None:
    assert EXECUTION_INFLUENCE is False
    assert EXECUTION_AUTHORITY is False
    assert LIVE_EXECUTION_ENABLED is False

    core = (
        ROOT / "src/fx_scanner/research_xau_v229_historical_v241.py"
    ).read_text(encoding="utf-8")
    aggregate = (
        ROOT / "src/fx_scanner/research_xau_v229_historical_v241_aggregate.py"
    ).read_text(encoding="utf-8")
    assert 'POLICY_EFFECT = "SHADOW_ONLY"' in core
    assert "IN-SAMPLE DIAGNOSTIC" in core
    assert '"in_sample_depth_prior": True' in aggregate

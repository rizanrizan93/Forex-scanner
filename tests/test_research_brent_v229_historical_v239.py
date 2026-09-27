from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd

from fx_scanner.research_brent_v229_historical_v239 import (
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
    _depth_price,
    _simulate_limit_trade,
    account_ledger,
    price_arrays,
)

ROOT = Path(__file__).resolve().parents[1]


def test_v239_brent_contract_and_cost_model() -> None:
    assert SYMBOL == "BRENT"
    assert PIP_SIZE == 0.01
    assert CHILD_LOT == 0.01
    assert CONTRACT_UNITS_PER_LOT == 1000.0
    assert CHILD_UNITS == 10.0
    assert BASE_SPREAD_PIPS == 4.0
    assert BASE_SLIPPAGE_PIPS == 1.0
    assert COMMISSION_PIPS_ROUND_TRIP == 0.0


def test_v239_keeps_four_slot_frozen_causal_prior() -> None:
    assert set(FROZEN_LADDER_DEPTHS) == {
        ("H4", "LONG"),
        ("H4", "SHORT"),
        ("H1", "LONG"),
        ("H1", "SHORT"),
        ("M15", "LONG"),
        ("M15", "SHORT"),
    }
    assert all(len(values) == 4 for values in FROZEN_LADDER_DEPTHS.values())
    assert all(tuple(values) == tuple(sorted(values)) for values in FROZEN_LADDER_DEPTHS.values())


def test_v239_depth_price_maps_brent_zone_edges() -> None:
    assert _depth_price("LONG", 79.0, 81.0, 0.0) == 81.0
    assert _depth_price("LONG", 79.0, 81.0, 1.0) == 79.0
    assert _depth_price("SHORT", 79.0, 81.0, 0.0) == 79.0
    assert _depth_price("SHORT", 79.0, 81.0, 1.0) == 81.0


def test_v239_stop_first_remains_conservative() -> None:
    start = datetime(2026, 1, 5, 0, 0, tzinfo=UTC)
    frame = pd.DataFrame(
        [
            {
                "timestamp": start + timedelta(minutes=1),
                "open": 80.0,
                "high": 81.5,
                "low": 78.5,
                "close": 80.0,
            },
            {
                "timestamp": start + timedelta(minutes=2),
                "open": 80.0,
                "high": 80.2,
                "low": 79.8,
                "close": 80.0,
            },
        ]
    )
    result = _simulate_limit_trade(
        px=price_arrays(frame),
        direction="LONG",
        order_at=start,
        expires_at=start + timedelta(minutes=10),
        entry=80.0,
        stop=79.0,
        target=81.0,
        spread_pips=4.0,
        slippage_pips=1.0,
        commission_pips=0.0,
    )
    assert result["state"] == "LOSS"
    assert result["reason"] == "STOP_FIRST_AMBIGUOUS"
    assert result["ambiguous_bar"] is True


def _trade(index: int) -> dict:
    start = datetime(2026, 1, 5, 0, 0, tzinfo=UTC)
    return {
        "plan_id": f"P{index}",
        "slot": 1,
        "state": "WIN",
        "entry_at": (start + timedelta(minutes=index)).isoformat(),
        "exit_at": (start + timedelta(hours=2)).isoformat(),
        "fill_price": 80.0,
        "planned_entry": 80.0,
        "net_pnl_usd": 10.0,
        "net_r": 1.0,
        "mae_r": 0.2,
        "mfe_r": 1.2,
    }


def test_v239_100_usd_1_to_100_margin_uses_ten_barrels_per_child() -> None:
    rows = [_trade(i) for i in range(7)]
    result = account_ledger(
        rows,
        initial_balance=100.0,
        leverage=100.0,
        margin_cap_fraction=0.50,
    )
    # 0.01 lot = 10 barrels; at $80 and 1:100 each child uses $8 margin.
    assert result["accepted_trades"] == 6
    assert result["margin_rejected"] == 1
    assert result["max_used_margin_usd"] == 48.0
    assert result["ending_balance"] == 160.0


def test_v239_is_shadow_only() -> None:
    assert EXECUTION_INFLUENCE is False
    assert EXECUTION_AUTHORITY is False
    assert LIVE_EXECUTION_ENABLED is False

    source = (
        ROOT / "src/fx_scanner/research_brent_v229_historical_v239.py"
    ).read_text(encoding="utf-8")
    assert 'POLICY_EFFECT = "SHADOW_ONLY"' in source

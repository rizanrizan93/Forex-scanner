from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd

from fx_scanner.research_eurusd_v229_historical_v236 import (
    CHILD_LOT,
    EXECUTION_AUTHORITY,
    EXECUTION_INFLUENCE,
    FROZEN_LADDER_DEPTHS,
    LIVE_EXECUTION_ENABLED,
    _depth_price,
    _simulate_limit_trade,
    account_ledger,
    effective_trades,
    price_arrays,
)

ROOT = Path(__file__).resolve().parents[1]


def test_v236_frozen_xau_ladder_prior_is_directional_and_four_slot() -> None:
    assert set(FROZEN_LADDER_DEPTHS) == {
        ("H4", "LONG"),
        ("H4", "SHORT"),
        ("H1", "LONG"),
        ("H1", "SHORT"),
        ("M15", "LONG"),
        ("M15", "SHORT"),
    }
    assert all(len(values) == 4 for values in FROZEN_LADDER_DEPTHS.values())
    assert all(list(values) == sorted(values) for values in FROZEN_LADDER_DEPTHS.values())


def test_v236_depth_price_maps_long_and_short_from_near_to_far_edge() -> None:
    assert _depth_price("LONG", 1.0900, 1.1000, 0.0) == 1.1000
    assert _depth_price("LONG", 1.0900, 1.1000, 1.0) == 1.0900
    assert _depth_price("SHORT", 1.0900, 1.1000, 0.0) == 1.0900
    assert _depth_price("SHORT", 1.0900, 1.1000, 1.0) == 1.1000


def test_v236_stop_first_on_ambiguous_fill_bar() -> None:
    start = datetime(2026, 1, 5, 0, 0, tzinfo=UTC)
    frame = pd.DataFrame(
        [
            {
                "timestamp": start + timedelta(minutes=1),
                "open": 1.1000,
                "high": 1.1020,
                "low": 1.0980,
                "close": 1.1000,
            },
            {
                "timestamp": start + timedelta(minutes=2),
                "open": 1.1000,
                "high": 1.1005,
                "low": 1.0995,
                "close": 1.1000,
            },
        ]
    )
    result = _simulate_limit_trade(
        px=price_arrays(frame),
        direction="LONG",
        order_at=start,
        expires_at=start + timedelta(minutes=10),
        entry=1.1000,
        stop=1.0990,
        target=1.1010,
        spread_pips=0.8,
        slippage_pips=0.2,
    )
    assert result["state"] == "LOSS"
    assert result["reason"] == "STOP_FIRST_AMBIGUOUS"
    assert result["ambiguous_bar"] is True


def test_v236_next_parent_cancels_unfilled_old_child() -> None:
    start = datetime(2026, 1, 5, 0, 0, tzinfo=UTC)
    plans = [
        {
            "plan_id": "P1",
            "plan_at": start.isoformat(),
            "signal_expires_at": (start + timedelta(hours=16)).isoformat(),
        },
        {
            "plan_id": "P2",
            "plan_at": (start + timedelta(hours=2)).isoformat(),
            "signal_expires_at": (start + timedelta(hours=18)).isoformat(),
        },
    ]
    trades = [
        {
            "plan_id": "P1",
            "state": "WIN",
            "entry_at": (start + timedelta(hours=3)).isoformat(),
            "exit_at": (start + timedelta(hours=4)).isoformat(),
            "net_r": 1.5,
            "net_pnl_usd": 1.5,
        }
    ]
    effective, _ = effective_trades(plans, trades)
    assert effective[0]["state"] == "CANCELLED"
    assert effective[0]["reason"] == "PARENT_SUPERSEDED_OR_EXPIRED_BEFORE_FILL"


def _trade(index: int) -> dict:
    start = datetime(2026, 1, 5, 0, 0, tzinfo=UTC)
    return {
        "plan_id": f"P{index}",
        "slot": 1,
        "state": "WIN",
        "entry_at": (start + timedelta(minutes=index)).isoformat(),
        "exit_at": (start + timedelta(hours=2)).isoformat(),
        "fill_price": 1.1000,
        "planned_entry": 1.1000,
        "net_pnl_usd": 1.0,
        "net_r": 1.0,
        "mae_r": 0.2,
        "mfe_r": 1.2,
    }


def test_v236_100_usd_1_to_100_margin_cap_rejects_fifth_overlapping_child() -> None:
    # EURUSD 0.01 lot at 1.1000 requires about $11 margin at 1:100.
    rows = [_trade(i) for i in range(5)]
    result = account_ledger(
        rows,
        initial_balance=100.0,
        leverage=100.0,
        margin_cap_fraction=0.50,
    )
    assert result["accepted_trades"] == 4
    assert result["margin_rejected"] == 1
    assert result["max_used_margin_usd"] == 44.0
    assert result["ending_balance"] == 104.0


def test_v236_is_research_only_and_does_not_unlock_live_execution() -> None:
    assert CHILD_LOT == 0.01
    assert EXECUTION_INFLUENCE is False
    assert EXECUTION_AUTHORITY is False
    assert LIVE_EXECUTION_ENABLED is False

    workflow = (
        ROOT / ".github/workflows/research-eurusd-v229-historical-v236.yml"
    ).read_text(encoding="utf-8")
    assert "2012" in workflow
    assert "2026" in workflow
    assert "research_eurusd_v229_historical_v236_year_runtime" in workflow
    assert "research_eurusd_v229_historical_v236_aggregate" in workflow

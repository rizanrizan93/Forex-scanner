from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd

from fx_scanner.research_brent_direct_m15_depth_v240 import (
    DEPTH_VARIANTS,
    EXECUTION_AUTHORITY,
    EXECUTION_INFLUENCE,
    LIVE_EXECUTION_ENABLED,
    PRIMARY_VARIANT,
    PROMOTION_AUTHORITY,
    DepthEpisode,
    _depth_price,
    _simulate_direct_trade,
    account_ledger,
    price_arrays,
)

ROOT = Path(__file__).resolve().parents[1]


def _episode(
    *,
    direction: str = "LONG",
    touch_at: datetime | None = None,
    outcome_at: datetime | None = None,
) -> DepthEpisode:
    touch = touch_at or datetime(2026, 1, 5, 0, 0, tzinfo=UTC)
    outcome = outcome_at or (touch + timedelta(minutes=30))
    if direction == "LONG":
        proximal, distal = 80.8, 80.0
    else:
        proximal, distal = 80.2, 81.0
    return DepthEpisode(
        zone_id="z1",
        timeframe="M15",
        zone_class="IMBALANCE",
        pattern="DBR" if direction == "LONG" else "RBD",
        direction=direction,
        available_at=touch - timedelta(hours=2),
        touch_at=touch,
        outcome_at=outcome,
        zone_low=80.0,
        zone_high=81.0,
        proximal=proximal,
        distal=distal,
        atr_points=1.0,
        zone_width=1.0,
        outcome="HOLD_050",
        reaction_hit=True,
        break_hit=False,
        max_depth_reached=0.2,
        turning_depth=0.2,
        turning_price=80.8,
        minutes_to_outcome=30.0,
        departure_range_atr=1.2,
        departure_body_fraction=0.7,
        base_range_atr=1.0,
        structural_bos=False,
    )


def test_v240_primary_depth_is_predeclared_10_percent() -> None:
    assert PRIMARY_VARIANT == "D10"
    assert DEPTH_VARIANTS == {"D05": 0.05, "D10": 0.10, "D15": 0.15}


def test_v240_depth_price_uses_full_zone_coordinate() -> None:
    long = _episode(direction="LONG")
    short = _episode(direction="SHORT")
    assert _depth_price(long, 0.10) == 80.9
    assert _depth_price(short, 0.10) == 80.1


def test_v240_stop_first_on_fill_bar_ambiguity() -> None:
    touch = datetime(2026, 1, 5, 0, 0, tzinfo=UTC)
    episode = _episode(
        touch_at=touch,
        outcome_at=touch + timedelta(minutes=2),
    )
    frame = pd.DataFrame(
        [
            {
                "timestamp": touch,
                "open": 80.9,
                "high": 81.6,
                "low": 79.6,
                "close": 80.5,
            },
            {
                "timestamp": touch + timedelta(minutes=1),
                "open": 80.5,
                "high": 80.7,
                "low": 80.4,
                "close": 80.6,
            },
            {
                "timestamp": touch + timedelta(hours=4),
                "open": 80.6,
                "high": 80.6,
                "low": 80.6,
                "close": 80.6,
            },
        ]
    )
    result = _simulate_direct_trade(
        px=price_arrays(frame),
        episode=episode,
        depth=0.10,
        spread_pips=4.0,
        slippage_pips=1.0,
        commission_pips=0.0,
    )
    assert result["state"] == "LOSS"
    assert result["reason"] == "STOP_FIRST_AMBIGUOUS"
    assert result["ambiguous_bar"] is True


def test_v240_does_not_fill_after_first_touch_outcome() -> None:
    touch = datetime(2026, 1, 5, 0, 0, tzinfo=UTC)
    episode = _episode(
        touch_at=touch,
        outcome_at=touch + timedelta(minutes=1),
    )
    frame = pd.DataFrame(
        [
            {
                "timestamp": touch,
                "open": 81.0,
                "high": 81.2,
                "low": 80.95,
                "close": 81.1,
            },
            {
                "timestamp": touch + timedelta(minutes=1),
                "open": 81.1,
                "high": 81.2,
                "low": 81.0,
                "close": 81.1,
            },
            {
                "timestamp": touch + timedelta(minutes=2),
                "open": 81.0,
                "high": 81.0,
                "low": 80.8,
                "close": 80.9,
            },
        ]
    )
    result = _simulate_direct_trade(
        px=price_arrays(frame),
        episode=episode,
        depth=0.10,
        spread_pips=4.0,
        slippage_pips=1.0,
        commission_pips=0.0,
    )
    assert result["state"] == "MISSED"
    assert result["reason"] == "DEPTH_NOT_REACHED_ON_FIRST_TOUCH"


def _ledger_trade(index: int) -> dict:
    start = datetime(2026, 1, 5, 0, 0, tzinfo=UTC)
    return {
        "zone_id": f"z{index}",
        "state": "WIN",
        "entry_at": (start + timedelta(seconds=index)).isoformat(),
        "exit_at": (start + timedelta(hours=2)).isoformat(),
        "fill_price": 80.0,
        "planned_entry": 80.0,
        "net_pnl_usd": 1.0,
        "net_r": 0.5,
        "mae_r": 0.2,
        "mfe_r": 0.6,
    }


def test_v240_account_ledger_enforces_ten_position_cap() -> None:
    rows = [_ledger_trade(i) for i in range(12)]
    result = account_ledger(
        rows,
        initial_balance=1000.0,
        leverage=100.0,
        margin_cap_fraction=None,
        max_positions=10,
    )
    assert result["accepted_trades"] == 10
    assert result["position_rejected"] == 2
    assert result["ending_balance"] == 1010.0


def test_v240_remains_shadow_only() -> None:
    assert EXECUTION_INFLUENCE is False
    assert EXECUTION_AUTHORITY is False
    assert PROMOTION_AUTHORITY is False
    assert LIVE_EXECUTION_ENABLED is False

    source = (
        ROOT / "src/fx_scanner/research_brent_direct_m15_depth_v240.py"
    ).read_text(encoding="utf-8")
    assert 'POLICY_EFFECT = "SHADOW_ONLY"' in source

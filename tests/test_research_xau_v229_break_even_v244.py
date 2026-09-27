from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd

from fx_scanner.research_xau_v229_break_even_v244 import (
    EXECUTION_AUTHORITY,
    EXECUTION_INFLUENCE,
    LIVE_EXECUTION_ENABLED,
    MANAGEMENT_VARIANTS,
    _managed_limit_trade,
)
from fx_scanner.research_xau_v229_historical_v242 import PriceArrays


def _px(rows: list[tuple[float, float, float, float]]) -> PriceArrays:
    start = datetime(2026, 1, 5, 0, 0, tzinfo=UTC)
    times = tuple(pd.Timestamp(start + timedelta(minutes=i + 1)) for i in range(len(rows)))
    return PriceArrays(
        timestamps=times,
        opens=np.array([row[0] for row in rows], dtype=float),
        highs=np.array([row[1] for row in rows], dtype=float),
        lows=np.array([row[2] for row in rows], dtype=float),
        closes=np.array([row[3] for row in rows], dtype=float),
    )


def _run(px: PriceArrays, *, trigger: float, spread: float = 0.0, slip: float = 0.0, commission: float = 0.0):
    start = px.timestamps[0].to_pydatetime() - timedelta(minutes=1)
    return _managed_limit_trade(
        px=px,
        direction="LONG",
        order_at=start,
        expires_at=start + timedelta(minutes=20),
        entry=100.0,
        stop=99.0,
        target=103.0,
        spread_pips=spread,
        slippage_pips=slip,
        commission_pips=commission,
        be_trigger_r=trigger,
    )


def test_v244_only_pre_registered_management_variants_exist() -> None:
    assert MANAGEMENT_VARIANTS == {
        "BASELINE": None,
        "BE_0_5R": 0.50,
        "BE_1_0R": 1.00,
    }


def test_v244_fill_bar_trigger_is_ignored_as_noncausal() -> None:
    result = _run(
        _px(
            [
                (100.0, 100.70, 99.90, 100.40),  # fill bar also prints +0.5R
                (100.4, 103.10, 99.80, 103.00), # must remain original-stop + target
            ]
        ),
        trigger=0.5,
    )
    assert result["state"] == "WIN"
    assert result["reason"] == "TARGET_HIT"
    assert result["be_triggered"] is False


def test_v244_break_even_activates_only_on_next_m1_bar() -> None:
    result = _run(
        _px(
            [
                (100.0, 100.10, 99.90, 100.00),  # fill
                (100.0, 100.60, 99.80, 100.40),  # trigger +0.5R, retrace same bar
                (100.4, 103.10, 100.20, 103.00), # BE is active, but target arrives first
            ]
        ),
        trigger=0.5,
    )
    assert result["state"] == "WIN"
    assert result["reason"] == "TARGET_HIT"
    assert result["be_triggered"] is True


def test_v244_break_even_stops_on_later_bar_after_trigger() -> None:
    result = _run(
        _px(
            [
                (100.0, 100.10, 99.90, 100.00),
                (100.0, 100.60, 100.10, 100.40),
                (100.4, 100.45, 99.95, 100.00),
            ]
        ),
        trigger=0.5,
    )
    assert result["state"] == "BREAKEVEN"
    assert result["reason"] == "NET_BE_STOP_HIT_AFTER_0_5R"
    assert result["net_r"] == 0.0


def test_v244_original_stop_wins_trigger_bar_ambiguity() -> None:
    result = _run(
        _px(
            [
                (100.0, 100.10, 99.90, 100.00),
                (100.0, 100.60, 98.90, 99.00),
            ]
        ),
        trigger=0.5,
    )
    assert result["state"] == "LOSS"
    assert result["reason"] == "STOP_HIT"
    assert result["be_triggered"] is False


def test_v244_net_break_even_offsets_remaining_cost_term() -> None:
    result = _run(
        _px(
            [
                (100.0, 100.05, 99.95, 100.00),
                (100.0, 100.60, 100.20, 100.40),
                (100.4, 100.45, 99.90, 100.00),
            ]
        ),
        trigger=0.5,
        spread=2.0,
        slip=0.2,
        commission=0.2,
    )
    assert result["state"] == "BREAKEVEN"
    assert abs(float(result["net_r"])) <= 1e-12
    assert float(result["be_stop"]) > float(result["fill_price"])


def test_v244_remains_research_only() -> None:
    assert EXECUTION_INFLUENCE is False
    assert EXECUTION_AUTHORITY is False
    assert LIVE_EXECUTION_ENABLED is False

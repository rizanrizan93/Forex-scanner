from datetime import UTC, datetime, timedelta

import pandas as pd

from fx_scanner.research_xau_h4_h1_m15_m5_portfolio_v233_aggregate import (
    _select_continuation,
    simulate_account,
)
from fx_scanner.research_xau_h4_h1_m15_m5_portfolio_v233_year import (
    _aggregate,
    _m5_trigger,
)


def _row(
    *,
    variant: str,
    year: int,
    pnl: float,
    offset: int,
    direction: str = "LONG",
) -> dict:
    fill = datetime(year, 1, 2, tzinfo=UTC) + timedelta(hours=offset * 20)
    return {
        "variant_id": variant,
        "year": year,
        "gross_points": pnl,
        "fill_at": fill.isoformat(),
        "exit_at": (fill + timedelta(hours=1)).isoformat(),
        "entry": 2000.0,
        "margin_usd_1_to_100": 20.0,
        "direction": direction,
        "trade_key": f"{variant}-{year}-{offset}",
        "exit_reason": "TP" if pnl > 0 else "SL",
    }


def test_v233_selection_uses_train_era_only() -> None:
    rows = []
    # A passes the frozen train gates but is deliberately awful later.
    for year in range(2012, 2019):
        for idx in range(20):
            rows.append(
                _row(
                    variant="A",
                    year=year,
                    pnl=2.0 if idx < 13 else -1.0,
                    offset=idx,
                )
            )
    for year in range(2019, 2027):
        for idx in range(20):
            rows.append(_row(variant="A", year=year, pnl=-2.0, offset=idx))

    # B is fantastic after 2018 but fails the 2012-2018 train gate.
    for year in range(2012, 2019):
        for idx in range(20):
            rows.append(
                _row(
                    variant="B",
                    year=year,
                    pnl=1.0 if idx < 5 else -1.0,
                    offset=idx,
                )
            )
    for year in range(2019, 2027):
        for idx in range(20):
            rows.append(_row(variant="B", year=year, pnl=4.0, offset=idx))

    selected, evidence = _select_continuation(rows)
    assert selected == "A"
    assert evidence["A"]["selection_passed"] is True
    assert evidence["B"]["selection_passed"] is False


def test_v233_account_compounding_is_margin_based_not_risk_percent() -> None:
    rows = [
        _row(variant="A", year=2025, pnl=10.0, offset=0),
        _row(variant="A", year=2025, pnl=10.0, offset=2),
    ]
    fixed = simulate_account(rows, friction=0.5, margin_fraction=None)
    compounded = simulate_account(rows, friction=0.5, margin_fraction=0.50)
    assert fixed["max_lot_used"] == 0.01
    assert compounded["max_lot_used"] > 0.01
    assert compounded["final_balance"] > fixed["final_balance"]


def test_v233_m5_trigger_requires_completed_break() -> None:
    row = pd.Series(
        {
            "prev3_high": 100.0,
            "prev3_low": 95.0,
            "open": 99.0,
            "high": 102.0,
            "low": 98.0,
            "close": 101.0,
            "atr14": 2.0,
            "body": 2.0,
            "close_loc": 0.75,
        }
    )
    assert _m5_trigger(row, direction="LONG", mode="BASIC_BREAK") is True
    assert _m5_trigger(row, direction="LONG", mode="DISPLACEMENT_BREAK") is True
    assert _m5_trigger(row, direction="SHORT", mode="BASIC_BREAK") is False


def test_v233_aggregate_candles_are_timestamped_at_close() -> None:
    start = pd.Timestamp("2025-01-01T00:00:00Z")
    frame = pd.DataFrame(
        {
            "timestamp": [start + pd.Timedelta(minutes=i) for i in range(5)],
            "open": [100.0, 101.0, 102.0, 103.0, 104.0],
            "high": [101.0, 102.0, 103.0, 104.0, 105.0],
            "low": [99.0, 100.0, 101.0, 102.0, 103.0],
            "close": [100.5, 101.5, 102.5, 103.5, 104.5],
        }
    )
    out = _aggregate(frame, "5min", 5)
    assert len(out) == 1
    assert out.iloc[0]["timestamp"] == start
    assert out.iloc[0]["close_at"] == start + pd.Timedelta(minutes=5)
    assert out.iloc[0]["open"] == 100.0
    assert out.iloc[0]["close"] == 104.5

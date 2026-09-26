from datetime import UTC, datetime, timedelta

import pandas as pd

from fx_scanner.research_xau_h4_h1_m15_m5_breakout_v234_aggregate import _select
from fx_scanner.research_xau_h4_h1_m15_m5_breakout_v234_year import _find_retest


def _trade(variant: str, year: int, pnl: float, idx: int) -> dict:
    fill = datetime(year, 1, 3, tzinfo=UTC) + timedelta(hours=idx)
    return {
        "variant_id": variant,
        "year": year,
        "gross_points": pnl,
        "fill_at": fill.isoformat(),
        "exit_at": (fill + timedelta(minutes=30)).isoformat(),
        "entry": 2000.0,
        "margin_usd_1_to_100": 20.0,
        "direction": "LONG",
        "trade_key": f"{variant}-{year}-{idx}",
        "exit_reason": "TP" if pnl > 0 else "SL",
    }


def test_v234_selection_is_train_only() -> None:
    rows = []
    for year in range(2012, 2019):
        for idx in range(15):
            rows.append(_trade("A", year, 2.0 if idx < 10 else -1.0, idx))
            rows.append(_trade("B", year, 1.0 if idx < 4 else -1.0, idx))
    for year in range(2019, 2027):
        for idx in range(15):
            rows.append(_trade("A", year, -5.0, idx))
            rows.append(_trade("B", year, 10.0, idx))

    selected, evidence = _select(rows)
    assert selected == "A"
    assert evidence["A"]["selection_passed"] is True
    assert evidence["B"]["selection_passed"] is False


def test_v234_m5_retest_occurs_after_m15_signal_close() -> None:
    base = pd.Timestamp("2025-01-01T00:00:00Z")
    rows = []
    for i in range(10):
        ts = base + pd.Timedelta(minutes=5 * i)
        rows.append(
            {
                "timestamp": ts,
                "close_at": ts + pd.Timedelta(minutes=5),
                "open": 101.0,
                "high": 102.0,
                "low": 100.5,
                "close": 101.5,
            }
        )
    frame = pd.DataFrame(rows)
    signal_close = base + pd.Timedelta(minutes=15)
    # First eligible post-signal completed M5 bar closes at 00:20.
    frame.loc[3, ["open", "high", "low", "close"]] = [100.8, 101.8, 99.8, 101.2]
    idx = _find_retest(
        frame,
        signal_close=signal_close,
        level=100.0,
        direction="LONG",
    )
    assert idx == 3
    assert frame.iloc[idx]["close_at"] > signal_close

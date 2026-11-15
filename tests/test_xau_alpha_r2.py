from __future__ import annotations

from dataclasses import replace

import pandas as pd
import pytest

from fx_scanner.xau_alpha_r2 import (
    EXECUTION_AUTHORITY, ResearchSettings, indicators, latest_indicator, simulate,
)


def trend_data(count: int = 360, cadence: str = "h") -> pd.DataFrame:
    dates = pd.date_range("2026-01-05", periods=count, freq=cadence, tz="UTC")
    prices = [4000.0 + i * 0.5 for i in range(count)]
    return pd.DataFrame({
        "datetime": dates, "open": [x - 0.1 for x in prices],
        "high": [x + 0.8 for x in prices],
        "low": [x - 0.9 for x in prices],
        "close": prices,
    })


def test_no_live_execution_authority() -> None:
    assert EXECUTION_AUTHORITY is False


def test_breakout_excludes_current_bar_from_donchian() -> None:
    frame = indicators(trend_data())
    assert frame.iloc[-1]["close"] > frame.iloc[-1]["channel_high20"]
    assert frame.iloc[-1]["signal"] == 1


def test_risk_gate_blocks_unsafe_minimum_lot() -> None:
    frame = indicators(trend_data())
    cfg = replace(ResearchSettings(), risk_fraction=0.01, stop_atr=2.0)
    payload = latest_indicator(frame, cfg)
    assert payload["direction"] == "BUY"
    assert payload["state"] == "BLOCKED_BY_RISK"
    assert payload["execution_authority"] is False


def test_non_h1_rejected() -> None:
    with pytest.raises(ValueError, match="INPUT_IS_NOT_CLOSED_H1"):
        indicators(trend_data(cadence="5min"))


def test_1pct_risk_may_legitimately_generate_no_trades() -> None:
    frame = indicators(trend_data())
    cfg = replace(ResearchSettings(), risk_fraction=0.01, stop_atr=2.0)
    report, trades = simulate(frame, cfg)
    assert report["initial_usd"] == 100.0
    assert report["trades"] == 0
    assert report["blocked_by_risk"] > 0
    assert trades.empty

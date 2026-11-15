from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from fx_scanner.xau_microalpha_r4 import (
    CONTRACT, EXECUTION_AUTHORITY, R4Settings, apply_lagged_macro_filter,
    backtest, build_liquidity_signals,
)


def synthetic_m5(n: int = 3200) -> pd.DataFrame:
    dt = pd.date_range("2026-03-02", periods=n, freq="5min", tz="UTC")
    p = 2500.0 + np.arange(n) * .005 + np.sin(np.arange(n) / 11) * 2.0
    return pd.DataFrame({
        "datetime": dt, "open": p - .1, "high": p + .4,
        "low": p - .4, "close": p,
    })


def forced_replay() -> pd.DataFrame:
    f = synthetic_m5(140)
    f["r4_signal"] = 0
    f["r4_structural_stop"] = np.nan
    # Entry is the NEXT candle open.
    f.loc[20, "r4_signal"] = 1
    f.loc[20, "r4_structural_stop"] = f.loc[21, "open"] - 2.0
    return f


def test_research_only() -> None:
    assert EXECUTION_AUTHORITY is False and "RESEARCH_ONLY" in CONTRACT


@pytest.mark.parametrize("pool", ["ROLL12", "ROLL24", "ASIA_OPEN_06_08"])
def test_no_future_candles_affect_past_signals(pool: str) -> None:
    base = synthetic_m5(3200)
    new = base.copy()
    extra = synthetic_m5(3212).iloc[3200:]
    extra.loc[:, "close"] += 300
    extra.loc[:, "open"] += 300
    extra.loc[:, "high"] += 300
    extra.loc[:, "low"] += 300
    new = pd.concat([new, extra], ignore_index=True)
    before = build_liquidity_signals(base, pool=pool, trend="M15")
    after = build_liquidity_signals(new, pool=pool, trend="M15")
    assert np.array_equal(before["r4_signal"], after["r4_signal"].iloc[:len(before)])


def test_bad_lookback_and_trend_rejected() -> None:
    with pytest.raises(ValueError, match="BAD_R4_POOL"):
        build_liquidity_signals(synthetic_m5(), pool="UNDEFINED")
    with pytest.raises(ValueError, match="BAD_R4_TREND"):
        build_liquidity_signals(synthetic_m5(), trend="PREDICT_FUTURE")


def test_minimum_lot_risk_is_enforced() -> None:
    src = forced_replay()
    cfg = replace(R4Settings(), risk_fraction=.01)
    out, _ = backtest(src, cfg)
    assert out["count"] == 0
    assert out["blocked_risk"] == 1


def test_same_candle_stop_precedes_target() -> None:
    src = forced_replay()
    cfg = R4Settings()
    # Make both SL and TP reachable on the next candle.
    src.loc[21, "high"] = float(src.loc[21, "open"]) + 12.0
    src.loc[21, "low"] = float(src.loc[21, "open"]) - 12.0
    out, trades = backtest(src, cfg, session="ALL")
    assert out["count"] == 1
    assert trades.iloc[0]["exit_reason"] == "STOP"
    assert trades.iloc[0]["pnl_usd"] < 0


def test_historical_macro_is_asof_and_missing_wait() -> None:
    sample = forced_replay()
    sample["closed_at"] = sample["datetime"] + pd.Timedelta(minutes=5)
    macro = pd.DataFrame({
        "asof": pd.DatetimeIndex([sample.loc[20, "closed_at"] - pd.Timedelta(minutes=30)]),
        "macro_DFII10_chg7d": [-.12],
        "macro_DGS10_chg7d": [-.11],
        "macro_DTWEXBGS_pct7d": [-.3],
    })
    allowed = apply_lagged_macro_filter(sample, macro, mode="REAL_NOMINAL_USD")
    assert allowed.loc[20, "r4_signal"] == 1
    future_only = macro.assign(asof=macro["asof"] + pd.Timedelta(hours=2))
    dropped = apply_lagged_macro_filter(sample, future_only, mode="REAL_NOMINAL_USD")
    assert dropped.loc[20, "r4_signal"] == 0


def test_asia_entry_forced_exit_by_session_end() -> None:
    src = forced_replay()
    # Setup at M5 01:40 UTC => 08:40 WIB; entry 08:45.
    cfg = replace(R4Settings(), risk_fraction=.05, max_hold_bars=100)
    out, ledger = backtest(src, cfg, session="ASIA")
    assert out["trading_authority"] is False
    assert out["start_usd"] == 100
    assert out["count"] == len(ledger)

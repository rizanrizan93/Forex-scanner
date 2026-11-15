from __future__ import annotations

from datetime import UTC, datetime
from math import sin

import numpy as np
import pandas as pd
import pytest

from fx_scanner.xau_microalpha_r4 import R4Settings, backtest
from fx_scanner.xau_microalpha_r5 import (
    CANDIDATES, CONTRACT, EXECUTION_AUTHORITY, build_signals, features, live_shadow_state,
)


def synthetic_bars(n=3500):
    t = pd.date_range("2026-02-02", periods=n, freq="5min", tz="UTC")
    v = 3000 + np.arange(n) * 0.015 + np.sin(np.arange(n) / 9) * 1.2
    return pd.DataFrame({
        "datetime": t, "open": v - .09, "high": v + .30,
        "low": v - .35, "close": v,
    })


def test_r5_no_live_order_authority():
    assert EXECUTION_AUTHORITY is False
    assert "RESEARCH_ONLY" in CONTRACT


@pytest.mark.parametrize("candidate", CANDIDATES)
def test_all_candidates_are_past_candle_only(candidate):
    base = synthetic_bars(3500)
    ext = synthetic_bars(3512)
    # Massive future price shift must not affect earlier closed-bar signals.
    for col in ("open", "high", "low", "close"):
        ext.loc[3500:, col] += 100
    a = build_signals(features(base), candidate=candidate)
    b = build_signals(features(ext), candidate=candidate)
    assert np.array_equal(a["r4_signal"].to_numpy(), b["r4_signal"].iloc[:len(base)].to_numpy())


def test_regime_and_signal_do_not_allow_future_h1_close():
    f = features(synthetic_bars(3500))
    # A closed M15/H1 EMA is fixed within its incomplete higher timeframe.
    idx = f.index[f["datetime"] == pd.Timestamp("2026-02-12T08:05:00Z")][0]
    assert f.loc[idx, "h1_ema50"] == f.loc[idx-1, "h1_ema50"]


def test_signal_structural_stop_only():
    f = features(synthetic_bars(3500))
    for name in CANDIDATES:
        x = build_signals(f, candidate=name)
        valid = x.loc[x["r4_signal"].ne(0)]
        if not valid.empty:
            assert (valid.loc[valid["r4_signal"].gt(0), "r4_structural_stop"]
                    < valid.loc[valid["r4_signal"].gt(0), "close"]).all()
            assert (valid.loc[valid["r4_signal"].lt(0), "r4_structural_stop"]
                    > valid.loc[valid["r4_signal"].lt(0), "close"]).all()


def test_empty_macro_rejects_order_permission():
    x = build_signals(features(synthetic_bars()), candidate="BREAKOUT_12_H1_M15")
    x.loc[len(x)-1, "r4_signal"] = 1
    x.loc[len(x)-1, "r4_structural_stop"] = x.iloc[-1]["close"]-2.0
    now = x.iloc[-1]["closed_at"].to_pydatetime()
    st = live_shadow_state(x, {"direction": "WAIT", "state": "WAIT_MACRO_DATA"},
                           now=pd.Timestamp(now))
    assert st["state"] in {"WAIT_MACRO", "BLOCKED_BY_RISK"}
    assert st["execution_authority"] is False
    st = live_shadow_state(x, {"direction": "BUY", "state": "MACRO_ALIGNED_CONTEXT"},
                           now=pd.Timestamp(now) + pd.Timedelta(minutes=90))
    assert st["state"] == "WAIT_STALE_PRICE"


def test_r5_cannot_increase_risk_over_budget():
    x = build_signals(features(synthetic_bars()), candidate="BREAKOUT_12_H1_M15")
    x.loc[len(x)-1, "r4_signal"] = 1
    x.loc[len(x)-1, "r4_structural_stop"] = x.iloc[-1]["close"]-25.0
    m = live_shadow_state(x, {"direction": "BUY", "state": "MACRO_ALIGNED_CONTEXT"},
                          now=x.iloc[-1]["closed_at"])
    assert m["state"] == "BLOCKED_BY_RISK"


def test_replay_is_readonly():
    x = build_signals(features(synthetic_bars()), candidate="H1_TREND_M5_MICROBREAK")
    s, ledger = backtest(x, R4Settings(), session="ASIA")
    assert s["trading_authority"] is False
    assert s["start_usd"] == 100
    assert s["count"] == len(ledger)

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from math import sin

import pandas as pd
import pytest

from fx_scanner.xau_microalpha_r3 import (
    CONTRACT, EXECUTION_AUTHORITY, MicroSettings, build_features,
    latest_research_state, macro_direction, replay,
)


def market_m5(n: int = 3600) -> pd.DataFrame:
    t = pd.date_range("2026-03-02", periods=n, freq="5min", tz="UTC")
    close = [4000.0 + i * 0.008 + 2 * sin(i / 11) for i in range(n)]
    return pd.DataFrame({
        "datetime": t, "open": [x - 0.1 for x in close],
        "high": [x + 0.6 for x in close],
        "low": [x - 0.6 for x in close],
        "close": close,
    })


def test_no_order_authority() -> None:
    assert EXECUTION_AUTHORITY is False
    assert "RESEARCH_ONLY" in CONTRACT


def test_reject_malformed_and_non_m5() -> None:
    source = market_m5()
    with pytest.raises(ValueError, match="M5_CADENCE_INVALID"):
        build_features(source.assign(datetime=pd.date_range("2026-03-02", periods=len(source),
                                                           freq="1min", tz="UTC")))
    with pytest.raises(ValueError, match="M5_IMPOSSIBLE_OHLC"):
        build_features(source.assign(low=source["high"] + 1))


def test_asof_does_not_leak_new_h1_before_close() -> None:
    features = build_features(market_m5())
    # H1 EMA is unchanged within the hour until a full hour has CLOSED.
    pre = features.loc[features["datetime"] == pd.Timestamp("2026-03-11T09:35:00Z")].iloc[0]
    prev = features.loc[features["datetime"] == pd.Timestamp("2026-03-11T09:30:00Z")].iloc[0]
    assert pre["h1_ema50"] == prev["h1_ema50"]
    assert "signal" in features


def test_macro_unavailable_is_wait() -> None:
    assert macro_direction(None, now=datetime(2026, 11, 15, tzinfo=UTC))["direction"] == "WAIT"


def test_stale_replay_does_not_become_current_signal() -> None:
    features = build_features(market_m5())
    features.loc[len(features) - 1, "signal"] = 1
    s = latest_research_state(features, MicroSettings(), macro={"state": "MACRO_ALIGNED_CONTEXT",
                                                                "direction": "BUY"},
                              now=datetime(2026, 11, 15, tzinfo=UTC))
    assert s["state"] == "WAIT_STALE_M5"
    assert s["execution_authority"] is False


def test_minimum_lot_risk_gate_blocks_oversized_trade() -> None:
    features = build_features(market_m5())
    features.loc[len(features) - 1, "signal"] = 1
    cfg = replace(MicroSettings(), stop_atr=25.0, risk_fraction=.01)
    state = latest_research_state(features, cfg, macro={"state": "MACRO_ALIGNED_CONTEXT",
                                                        "direction": "BUY"},
                                  now=features.iloc[-1]["closed_at"].to_pydatetime())
    assert state["state"] == "BLOCKED_BY_RISK"


def test_no_macro_replay_pretending_to_backtest_macro() -> None:
    features = build_features(market_m5())
    result, ledger = replay(features, MicroSettings(), session="ASIA")
    assert result["scope"] == "M5_TECHNICAL_ONLY_NOT_MACRO_BACKTEST"
    assert result["execution_authority"] is False
    assert result["initial_equity"] == 100.0
    assert len(ledger) == result["trades"]


def test_macro_alignment_requires_original_quote_timestamps(monkeypatch) -> None:
    # Use a lightweight test substitute for a validated dashboard snapshot
    # without importing any network/provider stack or credentials.
    import sys
    from types import ModuleType
    fake = ModuleType("fx_scanner.dashboard_independent_feeds")
    now = datetime(2026, 11, 15, 4, 0, tzinfo=UTC)
    original_quote_time = now
    def read(snapshot, *, now):
        return {
            "observed_at": now.isoformat(),
            "evaluation": {
                "attribution_quality": {
                    "quality_state": "ALIGNED_CONTEXT_ONLY",
                    "quality_screened_bias": "BULLISH_XAU",
                    "intraday_confirmation_eligible": True,
                    "independent_families": 2,
                },
                "intraday_macro_confirmation": {
                    "components": {
                        "DXY": {"available": True, "current_at": original_quote_time.isoformat(),
                                "gold_implication": "GOLD_SUPPORT"},
                        "US10Y_INTRADAY": {"available": True, "current_at": original_quote_time.isoformat(),
                                          "gold_implication": "GOLD_SUPPORT"},
                    }
                },
            }
        }
    fake.macro_input = read
    monkeypatch.setitem(sys.modules, "fx_scanner.dashboard_independent_feeds", fake)
    state = macro_direction({"contract": "DUMMY_UNIT_TEST"}, now=now)
    assert state["direction"] == "BUY"
    assert state["state"] == "MACRO_ALIGNED_CONTEXT"
    # A next update without a genuinely current DXY must fail closed.
    late = macro_direction({"contract": "DUMMY_UNIT_TEST"}, now=now + timedelta(minutes=18))
    assert late["direction"] == "WAIT"
    assert late["state"] == "WAIT_INTRADAY"

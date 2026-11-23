"""No replay benchmark may be presented as a live model or execution-ready zone."""
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd

from fx_scanner.frozen_direction_context import context
from fx_scanner.manual_direction_map import (
    MODEL_STATE, historical_benchmarks, r2_tactical, timeframe_guidance, direction_board_rows,
)


def rising_h1(now):
    idx = pd.date_range(end=now, periods=40, freq="h")
    close = [3000 + 2 * i for i in range(40)]
    bars = pd.DataFrame({
        "open": [x - 1 for x in close],
        "high": [x + 2 for x in close],
        "low": [x - 2 for x in close],
        "close": close,
    }, index=idx)
    return bars, context(bars, "H1", now=now, observed_at=now, market_fresh=True)


def test_historical_benchmark_is_not_live_direction():
    p = Path(__file__).resolve().parents[1] / "research/direction_benchmark_lock_r281_20261122.json"
    rows = historical_benchmarks(json.loads(p.read_text()))
    assert len(rows) == 8
    assert rows[("H1", "BUY")]["version"] == "R25"
    assert rows[("W1", "BUY")]["accuracy"] == .6875
    assert rows[("W1", "SELL")]["version"] == "R24"
    assert MODEL_STATE == "WAIT MODEL"


def test_h1_wait_model_even_when_technical_buy_active():
    now = datetime(2026, 11, 18, 12, tzinfo=UTC)
    bars, report = rising_h1(now)
    result = timeframe_guidance("H1", report, bars, {"H1": report}, now=now)
    assert result["model"] == "WAIT MODEL"
    assert result["model_status"] == "NO_PORTABLE_R28_MODEL"
    assert result["technical"] == "BUY"
    assert result["watch_area"] is not None
    assert result["watch_area"]["source"].endswith("BELUM backtest")
    assert result["historically_validated_zone"] is False
    assert result["execution_authority"] is False


def test_stale_data_never_publishes_tradable_area():
    t = datetime(2026, 11, 18, 12, tzinfo=UTC)
    bars, report = rising_h1(t)
    late = t + timedelta(hours=2)
    stale = context(bars, "H1", now=late, observed_at=t, market_fresh=False)
    result = timeframe_guidance("H1", stale, bars, {"H1": stale}, now=late)
    assert result["state"] == "WAIT_TECHNICAL_OR_DATA"
    assert result["watch_area"] is None
    assert result["technical"] == "WAIT DATA"


def test_higher_timeframe_conflict_is_wait_not_entry():
    now = datetime(2026, 11, 18, 12, tzinfo=UTC)
    bars, report = rising_h1(now)
    reports = {"H1": report, "H4": {"fresh": True, "forecast": "SELL"}}
    result = timeframe_guidance("H1", report, bars, reports, now=now)
    assert result["state"] == "WAIT_OPPOSING_HIGHER_TF"
    assert result["watch_area"]["tested_entry"] is False


def test_v05_eligible_watch_prioritized_only_with_exact_tf_side():
    now = datetime(2026, 11, 18, 12, tzinfo=UTC)
    bars, report = rising_h1(now)
    exact = {"state": "WATCH", "limit": [
        {"state": "WATCH", "side": "SELL", "first_touch_verified": True,
         "entry_allowed": False, "price_at_evaluation": 3078.,
         "source": {"timeframe": "H1", "low": 3080., "high": 3090.}},
        {"state": "WATCH", "side": "BUY", "first_touch_verified": True,
         "entry_allowed": False, "price_at_evaluation": 3078.,
         "source": {"timeframe": "H4", "low": 3060., "high": 3070.}},
        {"state": "WATCH", "side": "BUY", "first_touch_verified": True,
         "entry_allowed": False, "price_at_evaluation": 3078.,
         "source": {"timeframe": "H1", "low": 3060., "high": 3070.}},
    ]}
    r = timeframe_guidance("H1", report, bars, {"H1": report}, now=now, v05_paths=exact)
    assert r["watch_area"]["source"].startswith("V05")
    assert r["watch_area"]["invalidation"] == 3060.
    assert r["watch_area"]["side"] == "BUY"
    assert r["watch_area"]["tested_entry"] is False
    exact["limit"][-1]["first_touch_verified"] = False
    fallback = timeframe_guidance("H1", report, bars, {"H1": report}, now=now, v05_paths=exact)
    assert fallback["watch_area"]["source"].endswith("BELUM backtest")


def test_r2_manual_trigger_is_not_h1_replay_forecast():
    now = datetime(2026, 11, 18, 12, 0, 30, tzinfo=UTC)
    p = {
        "contract": "RIZAN_ENTRY_DIRECTION_R2_V1",
        "execution_authority": False, "execution_influence": False,
        "model_id": "R2_RULE_670", "status": "TRIGGER_SELL",
        "direction": "SELL", "policy": "SELL_ONLY",
        "as_of": now.isoformat(),
        "quote": {"bid": 3078., "ask": 3078.3, "at": now.isoformat()},
        "signal": {"side": "SELL", "reference": 3078., "level": 3080.,
                   "signal_at": now.replace(second=0).isoformat(),
                   "valid_until": now.replace(second=0).isoformat().replace("12:00", "12:01")},
    }
    r = r2_tactical(p, now=now)
    assert r["state"] == "TRIGGER_SELL"
    assert r["model"] == "R2_RULE_670"
    assert r["execution_authority"] is False
    assert r2_tactical(p, now=now + timedelta(minutes=2))["state"] == "WAIT"


def test_direction_board_shows_actual_buy_sell_not_wait_model():
    now = datetime(2026, 11, 18, 12, tzinfo=UTC)
    bars, buy = rising_h1(now)
    sell_bars = bars.copy()
    sell_bars["open"] = 3100 - bars.open + 3000
    sell_bars["close"] = 3100 - bars.close + 3000
    sell_bars["high"] = sell_bars[["open", "close"]].max(axis=1) + 2
    sell_bars["low"] = sell_bars[["open", "close"]].min(axis=1) - 2
    sell = context(sell_bars, "H4", now=now, observed_at=now, market_fresh=True)
    guide1 = timeframe_guidance("H1", buy, bars, {"H1": buy}, now=now)
    guide4 = timeframe_guidance("H4", sell, sell_bars, {"H4": sell}, now=now)
    rows = direction_board_rows({"H1": guide1, "H4": guide4})
    assert [r["Arah"] for r in rows] == ["BUY", "SELL", "WAIT DATA", "WAIT DATA"]
    assert rows[0]["Target close (WIB)"] == "18/11 20:00 WIB"
    assert rows[1]["Target close (WIB)"] == "18/11 23:00 WIB"
    assert all(not r["model_r28_live"] and not r["execution_authority"] for r in rows)
    assert "WAIT MODEL" not in str([r["Arah"] for r in rows])


def test_direction_board_never_promotes_unproven_or_expired_direction():
    now = datetime(2026, 11, 18, 12, tzinfo=UTC)
    bars, buy = rising_h1(now)
    guide = timeframe_guidance("H1", buy, bars, {"H1": buy}, now=now)
    bad = dict(guide, technical="BUY", technical_kind="UNAVAILABLE")
    assert direction_board_rows({"H1": bad})[0]["Arah"] == "WAIT DATA"
    missing = dict(guide, target_at="not-a-timestamp")
    assert direction_board_rows({"H1": missing})[0]["Arah"] == "WAIT DATA"
    stale = context(bars, "H1", now=now + timedelta(hours=2), observed_at=now, market_fresh=False)
    result = timeframe_guidance("H1", stale, bars, {"H1": stale}, now=now + timedelta(hours=2))
    assert direction_board_rows({"H1": result})[0]["Arah"] == "WAIT DATA"

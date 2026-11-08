"""Regression tests: M15 boundaries, freshness, macro/geo vote and event guard."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fx_scanner.xau_m15_macro_forecast import forecast_m15_xau


NOW = datetime(2026, 11, 6, 18, 26, tzinfo=UTC)


def macro(score=70, *, state="ALIGNED_OR_FLAT"):
    return {
        "score": score,
        "state": state,
        "coverage_core_pct": 100,
        "score_breakdown": {
            "Treasury": 25.0, "DXY": 30.0, "Oil": 5.0,
            "Geopolitical": 5.0, "Safe Haven": 5.0,
        },
        "geo_haven_assessment": {"status": "RISK_OFF_CONFIRMED"},
    }


def snapshot(*, now=NOW, price=4064.1, close=4061.13):
    start = now.replace(minute=15 * (now.minute // 15), second=0, microsecond=0)
    return {
        "contract": "RIZAN_XAU_MANUAL_REVERSAL_MAP_V2",
        "symbol": "XAUUSD",
        "source": "CTRADER_MARKET_DATA_READ_ONLY",
        "fresh": True,
        "execution_authority": False,
        "execution_influence": False,
        "as_of": (now - timedelta(seconds=30)).isoformat(),
        "price_observed_at": (now - timedelta(seconds=45)).isoformat(),
        "price": price,
        "latest_closed_m15": {"close": close, "closed_at": start.isoformat()},
        "timeframe_fresh": {"M15": True},
    }


def test_bullish_interval_and_geopolitics_included():
    result = forecast_m15_xau(macro(), snapshot(), now=NOW, event_risk={"state": "CLEAR"})
    assert result["status"] == "READY"
    assert result["direction"] == "PREDIKSI BULLISH M15"
    assert result["candle_start"] == "2026-11-06T18:15:00+00:00"
    assert result["candle_end"] == "2026-11-06T18:30:00+00:00"
    assert result["score_breakdown"]["Geopolitical"] == 5
    assert result["execution_authority"] is False


def test_bearish_and_not_a_probability():
    result = forecast_m15_xau(macro(-80), snapshot(price=4058.0), now=NOW)
    assert result["status"] == "READY"
    assert result["direction"] == "PREDIKSI BEARISH M15"
    assert result["model"].endswith("UNCALIBRATED")


def test_old_candle_never_uses_wrong_interval():
    s = snapshot()
    s["latest_closed_m15"]["closed_at"] = (NOW - timedelta(minutes=26)).isoformat()
    result = forecast_m15_xau(macro(), s, now=NOW)
    assert result["status"] == "WAIT_DATA"


def test_future_bar_never_leaks():
    s = snapshot()
    s["latest_closed_m15"]["closed_at"] = "2026-11-06T18:30:00+00:00"
    assert forecast_m15_xau(macro(), s, now=NOW)["status"] == "WAIT_DATA"


def test_stale_snapshot_and_stale_quote_refuse_prediction():
    s = snapshot()
    s["as_of"] = (NOW - timedelta(minutes=8)).isoformat()
    assert forecast_m15_xau(macro(), s, now=NOW)["status"] == "WAIT_DATA"
    s = snapshot()
    s["price_observed_at"] = (NOW - timedelta(minutes=6)).isoformat()
    assert forecast_m15_xau(macro(), s, now=NOW)["status"] == "WAIT_DATA"


def test_missing_core_macro_is_fail_closed():
    assert forecast_m15_xau(macro(None), snapshot(), now=NOW)["status"] == "WAIT_DATA"
    assert forecast_m15_xau({"score": 45, "coverage_core_pct": 60}, snapshot(), now=NOW)["status"] == "WAIT_DATA"


def test_event_risk_blocks_even_when_bullish():
    r = forecast_m15_xau(macro(), snapshot(), now=NOW, event_risk={"state": "HIGH"})
    assert r["status"] == "EVENT_RISK"
    assert r["index"] is None


def test_contract_mismatch_and_wrong_source_refused():
    s = snapshot()
    s["source"] = "EXCHANGE_DELAYED_FUTURES"
    assert forecast_m15_xau(macro(), s, now=NOW)["status"] == "WAIT_DATA"
    s = snapshot()
    s["execution_authority"] = True
    assert forecast_m15_xau(macro(), s, now=NOW)["status"] == "WAIT_DATA"


def test_advance_to_next_candle_fails_until_new_m15_close_arrives():
    following = NOW + timedelta(minutes=5)  # 18:31 UTC
    old_snapshot = snapshot(now=following)
    old_snapshot["latest_closed_m15"]["closed_at"] = "2026-11-06T18:15:00+00:00"
    assert forecast_m15_xau(macro(), old_snapshot, now=following)["status"] == "WAIT_DATA"
    new_snapshot = snapshot(now=following)
    r = forecast_m15_xau(macro(), new_snapshot, now=following)
    assert r["status"] == "READY"
    assert r["candle_start"] == "2026-11-06T18:30:00+00:00"

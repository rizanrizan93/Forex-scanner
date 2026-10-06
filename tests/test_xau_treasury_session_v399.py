from datetime import UTC, datetime, timedelta

from fx_scanner.xau_treasury_session_v399 import (
    evaluate_treasury_futures_pressure,
    resolve_us10y_session_context,
)

NOW = datetime(2026, 10, 7, 0, 0, tzinfo=UTC)


def _points(values, *, minutes=15):
    start = NOW - timedelta(minutes=minutes * (len(values) - 1))
    return [
        {"observed_at": start + timedelta(minutes=minutes * idx), "value": value}
        for idx, value in enumerate(values)
    ]


def test_treasury_futures_down_means_yield_up_gold_headwind():
    out = evaluate_treasury_futures_pressure(
        _points([112.25, 112.1875]),
        now=NOW,
        flat_threshold_points=0.03125,
    )
    assert out["available"] is True
    assert out["state"] == "TREASURY_FUTURES_DOWN_YIELD_UP_PROXY"
    assert out["yield_pressure"] == "YIELD_UP_PROXY"
    assert out["gold_implication"] == "GOLD_HEADWIND"


def test_treasury_futures_up_means_yield_down_gold_support():
    out = evaluate_treasury_futures_pressure(
        _points([112.00, 112.0625]),
        now=NOW,
        flat_threshold_points=0.03125,
    )
    assert out["available"] is True
    assert out["state"] == "TREASURY_FUTURES_UP_YIELD_DOWN_PROXY"
    assert out["yield_pressure"] == "YIELD_DOWN_PROXY"
    assert out["gold_implication"] == "GOLD_SUPPORT"


def test_stale_cash_with_fresh_futures_keeps_last_cash_value_but_uses_proxy_direction():
    cash = {
        "available": False,
        "state": "INTRADAY_YIELD_STALE",
        "freshness": "STALE",
        "gold_implication": "UNAVAILABLE",
        "current": 5.311,
        "current_at": (NOW - timedelta(hours=2)).isoformat(),
        "age_seconds": 7200.0,
        "reference": 5.29,
        "reference_at": (NOW - timedelta(hours=3)).isoformat(),
    }
    futures = {
        "available": True,
        "freshness": "FRESH",
        "state": "TREASURY_FUTURES_DOWN_YIELD_UP_PROXY",
        "gold_implication": "GOLD_HEADWIND",
        "yield_pressure": "YIELD_UP_PROXY",
        "current": 112.1875,
        "current_at": (NOW - timedelta(minutes=5)).isoformat(),
        "age_seconds": 300.0,
        "change_points": -0.0625,
        "change_pct": -0.05,
    }
    out = resolve_us10y_session_context(cash_yield=cash, treasury_futures=futures)
    assert out["available"] is True
    assert out["freshness"] == "PROXY_FRESH"
    assert out["state"] == "US10Y_CASH_LAST_VALID_FUTURES_ACTIVE"
    assert out["current"] == 5.311
    assert out["last_cash_yield"] == 5.311
    assert out["gold_implication"] == "GOLD_HEADWIND"
    assert out["effective_source"] == "YAHOO_FINANCE_ZN_FRONT_PROXY"
    assert out["net_bps"] is None


def test_fresh_cash_remains_preferred_over_futures_proxy():
    cash = {
        "available": True,
        "state": "INTRADAY_YIELD_UP",
        "gold_implication": "GOLD_HEADWIND",
        "current": 5.30,
        "current_at": NOW.isoformat(),
        "age_seconds": 0.0,
        "net_bps": 2.0,
    }
    futures = {
        "available": True,
        "freshness": "FRESH",
        "state": "TREASURY_FUTURES_UP_YIELD_DOWN_PROXY",
        "gold_implication": "GOLD_SUPPORT",
        "current": 112.30,
    }
    out = resolve_us10y_session_context(cash_yield=cash, treasury_futures=futures)
    assert out["available"] is True
    assert out["state"] == "US10Y_CASH_LIVE"
    assert out["effective_source"] == "YAHOO_FINANCE_TNX_INTRADAY_PROXY"
    assert out["gold_implication"] == "GOLD_HEADWIND"


def test_no_fresh_cash_or_futures_fails_closed_but_preserves_last_cash_yield():
    cash = {
        "available": False,
        "state": "INTRADAY_YIELD_STALE",
        "current": 5.311,
        "current_at": (NOW - timedelta(hours=2)).isoformat(),
        "age_seconds": 7200.0,
    }
    futures = {
        "available": False,
        "freshness": "STALE",
        "state": "TREASURY_FUTURES_STALE",
        "gold_implication": "UNAVAILABLE",
    }
    out = resolve_us10y_session_context(cash_yield=cash, treasury_futures=futures)
    assert out["available"] is False
    assert out["state"] == "US10Y_CASH_LAST_VALID_NO_FRESH_PROXY"
    assert out["current"] == 5.311
    assert out["gold_implication"] == "UNAVAILABLE"

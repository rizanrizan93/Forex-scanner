from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from fx_scanner.xau_yield_pressure_nowcast_v1 import (
    CONTRACT, EXECUTION_AUTHORITY, evaluate_yield_pressure,
)


NOW = datetime(2026, 11, 16, 1, 15, tzinfo=UTC)


def at(minutes=0):
    return (NOW - timedelta(minutes=minutes)).isoformat()


def zn(change=-.03125):
    return {
        "available": True,
        "timing_basis": "TREASURY_FUTURES_PROXY",
        "source": "CASH_LAST_VALID_PLUS_ZN_FUTURES_PROXY",
        "effective_source": "YAHOO_FINANCE_ZN_FRONT_PROXY",
        "session_state": "GLOBEX_PROXY_ACTIVE",
        "futures_at": at(4),
        "futures_price": 105.25,
        "futures_change_points": change,
        "futures_yield_pressure": (
            "YIELD_UP_PROXY" if change < 0 else
            "YIELD_DOWN_PROXY" if change > 0 else "YIELD_FLAT_PROXY"
        ),
    }


def zq(delta=2.0):
    ref = 96.80
    return {
        "source": "YAHOO_FINANCE_ZQ_FRONT_PROXY",
        "available": True,
        "reference": ref,
        "current": ref - delta / 100,
        "reference_at": at(63),
        "current_at": at(3),
        "implied_rate_change_bps": delta,
    }


def test_strong_rate_up_potential_sell_side():
    result = evaluate_yield_pressure(
        {"intraday_yield_context": zn(-.03125)},
        fed_funds=zq(2), now=NOW,
    )
    assert result["contract"] == CONTRACT
    assert result["yield_direction"] == "UP"
    assert result["state"] == "CONCORDANT_PROXY"
    assert result["concordance"] is True
    assert result["execution_authority"] is False
    assert result["predicted_numeric_yield_percent"] is None


def test_rate_down_potential_buy_side():
    result = evaluate_yield_pressure(
        {"intraday_yield_context": zn(.0625)},
        fed_funds=zq(-3.0), now=NOW,
    )
    assert result["yield_direction"] == "DOWN"
    assert result["state"] == "CONCORDANT_PROXY"
    assert EXECUTION_AUTHORITY is False


def test_zq_conflict_forces_wait():
    result = evaluate_yield_pressure(
        {"intraday_yield_context": zn(.03125)},
        fed_funds=zq(2), now=NOW,
    )
    assert result["state"] == "WAIT_CONFLICT"
    assert result["yield_direction"] == "WAIT"


def test_zq_absent_is_only_one_source_proxy_not_confirmed():
    result = evaluate_yield_pressure(
        {"intraday_yield_context": zn(.03125)}, now=NOW,
    )
    assert result["yield_direction"] == "DOWN"
    assert result["state"] == "ZN_PROXY_ONLY"


def test_stale_original_futures_quote_forces_wait_even_if_cached_age_fresh():
    v = zn(-.03125)
    v["futures_at"] = at(32)
    v["age_seconds"] = 10
    result = evaluate_yield_pressure(
        {"intraday_yield_context": v}, fed_funds=zq(), now=NOW,
    )
    assert result["state"] == "WAIT_SOURCE"
    assert result["yield_direction"] == "WAIT"


def test_stale_weekend_cash_yield_cannot_count_as_zn():
    result = evaluate_yield_pressure({
        "intraday_yield_context": {
            "available": True, "source": "US_TREASURY_DAILY_XML",
            "current_at": at(2), "net_bps": 5.0,
            "futures_yield_pressure": "YIELD_UP_PROXY",
        },
    }, fed_funds=zq(), now=NOW)
    assert result["yield_direction"] == "WAIT"


def test_mislabeled_zn_direction_rejected():
    z = zn(-.0625)
    z["futures_yield_pressure"] = "YIELD_DOWN_PROXY"
    result = evaluate_yield_pressure({
        "intraday_yield_context": z,
    }, fed_funds=zq(), now=NOW)
    assert result["zn"]["quality"] == "INCONSISTENT"
    assert result["yield_direction"] == "WAIT"


def test_flat_zn_is_not_direction_forecast():
    result = evaluate_yield_pressure(
        {"intraday_yield_context": zn(.001)}, fed_funds=zq(), now=NOW,
    )
    assert result["state"] == "WAIT_SOURCE"


def test_future_timestamp_rejected():
    z = zn(.03125)
    z["futures_at"] = (NOW + timedelta(seconds=30)).isoformat()
    assert evaluate_yield_pressure({
        "intraday_yield_context": z,
    }, now=NOW)["yield_direction"] == "WAIT"


def test_reject_naive_now():
    with pytest.raises(ValueError, match="NOW_MUST_HAVE_TIMEZONE"):
        evaluate_yield_pressure({}, now=datetime(2026, 11, 16))

"""Focused M15 source tests: closed-candle timestamps, price age, account and orders."""
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
import pytest

from scripts.collect_xau_m15_readonly import ReadOnly, to_snapshot
from fx_scanner.xau_m15_macro_forecast import (
    validate_fast_m15_snapshot, forecast_m15_xau,
)

NOW = datetime(2026, 11, 9, 1, 57, 18, tzinfo=UTC)
START = datetime(2026, 11, 9, 1, 45, tzinfo=UTC)


def b(at, close):
    return SimpleNamespace(timestamp=at, close=close)


def fresh():
    return to_snapshot(
        [b(NOW.replace(second=0, microsecond=0) - timedelta(minutes=1), 4062.4)],
        [b(START - timedelta(minutes=15), 4060.2)],
        now=NOW,
    )


def macro():
    return {"score": 65, "coverage_core_pct": 100, "state": "ALIGNED_OR_FLAT",
            "score_breakdown": {"Treasury": 25, "DXY": 20}}


def test_closed_m15_from_previous_candle_is_ready():
    snap = fresh()
    assert snap["latest_closed_m15"]["closed_at"] == START.isoformat()
    assert snap["price_observed_at"] == "2026-11-09T01:57:00+00:00"
    result = forecast_m15_xau(macro(), snap, now=NOW)
    assert result["status"] == "READY"
    assert result["data_source"].startswith("cTrader LIVE 7903")


def test_wrong_account_cannot_validate():
    s = fresh()
    s["account_suffix"] = "4480"
    with pytest.raises(ValueError):
        validate_fast_m15_snapshot(s, now=NOW)
    assert forecast_m15_xau(macro(), s, now=NOW)["status"] == "WAIT_DATA"


def test_old_bar_and_forming_bar_cannot_publish():
    with pytest.raises(ValueError):
        to_snapshot([b(START - timedelta(minutes=2), 4050)],
                    [b(START - timedelta(minutes=15), 4060)], now=NOW)
    with pytest.raises(ValueError):
        to_snapshot([b(START + timedelta(minutes=11), 4060)],
                    [b(START, 4050)], now=NOW)


def test_source_price_does_not_gain_freshness_from_new_publish_time():
    snap = fresh()
    snap["price_observed_at"] = (NOW - timedelta(minutes=5)).isoformat()
    with pytest.raises(ValueError):
        validate_fast_m15_snapshot(snap, now=NOW)
    assert forecast_m15_xau(macro(), snap, now=NOW)["status"] == "WAIT_DATA"


def test_next_m15_candle_refuses_yesterday_close():
    snap = fresh()
    future = NOW + timedelta(minutes=5)
    with pytest.raises(ValueError):
        validate_fast_m15_snapshot(snap, now=future)


def test_readonly_protocol_has_no_orders_positions_or_refresh():
    assert "ProtoOANewOrderReq" not in ReadOnly.allowed
    assert "ProtoOAReconcileReq" not in ReadOnly.allowed
    assert "ProtoOARefreshTokenReq" not in ReadOnly.allowed
    assert "ProtoOAGetTrendbarsReq" in ReadOnly.allowed

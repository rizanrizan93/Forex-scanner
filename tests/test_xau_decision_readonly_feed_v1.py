"""Isolated broker read-only candle collector and delivery validation tests."""
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from scripts.collect_xau_decision_readonly import ReadOnly, TIMEFRAMES, make_payload
from fx_scanner.xau_decision_candle_feed_v1 import validate_candle_snapshot


NOW = datetime(2026, 11, 16, 12, 0, tzinfo=UTC)


def fake_series(*, now=NOW):
    out = {}
    for tf, spec in TIMEFRAMES.items():
        span = spec["interval"]
        n = spec["required"]
        out[tf] = [
            SimpleNamespace(
                timestamp=now-(n-i)*span,
                open=3990+i*.2, high=3991+i*.2,
                low=3989+i*.2, close=3990.5+i*.2,
            )
            for i in range(n)
        ]
    return out


def test_collector_permitted_requests_exclude_orders():
    assert "ProtoOAGetTrendbarsReq" in ReadOnly.allowed
    for req in ("ProtoOANewOrderReq", "ProtoOAReconcileReq",
                "ProtoOARefreshTokenReq", "ProtoOAAmendPositionSLTPReq"):
        assert req not in ReadOnly.allowed


def test_fully_closed_history_can_publish():
    payload = make_payload(fake_series(), now=NOW)
    assert payload["account_suffix"] == "7903"
    assert payload["execution_authority"] is False
    assert len(payload["bars"]["H1"]) >= 210
    assert len(payload["bars"]["M15"]) >= 70
    assert len(payload["bars"]["M5"]) >= 30
    assert validate_candle_snapshot(payload, now=NOW) == payload


def test_partial_candle_not_counted():
    bars = fake_series()
    bars["H1"][-1].timestamp = NOW
    with pytest.raises(ValueError, match="NOT_ENOUGH_CLOSED_H1"):
        make_payload(bars, now=NOW)


def test_wrong_source_account_or_age_refused():
    payload = make_payload(fake_series(), now=NOW)
    payload["account_suffix"] = "7904"
    with pytest.raises(ValueError):
        validate_candle_snapshot(payload, now=NOW)
    payload = make_payload(fake_series(), now=NOW)
    payload["source"] = "RESEARCH_HISTORICAL_CSV"
    with pytest.raises(ValueError):
        validate_candle_snapshot(payload, now=NOW)
    payload = make_payload(fake_series(), now=NOW)
    with pytest.raises(ValueError, match="SNAPSHOT_STALE"):
        validate_candle_snapshot(payload, now=NOW+timedelta(minutes=20))


def test_future_time_cannot_be_republished():
    payload = make_payload(fake_series(), now=NOW)
    with pytest.raises(ValueError, match="SNAPSHOT_STALE"):
        validate_candle_snapshot(payload, now=NOW-timedelta(minutes=3))

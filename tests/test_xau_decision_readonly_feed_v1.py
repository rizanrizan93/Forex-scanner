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


def test_cached_raw_m5_uses_cache_busted_contents_api():
    import base64
    import json
    from fx_scanner.xau_decision_candle_feed_v1 import fetch_decision_candles
    old = make_payload(fake_series(now=NOW-timedelta(minutes=5)), now=NOW-timedelta(minutes=5))
    new = make_payload(fake_series(), now=NOW)
    urls = []
    class Response:
        def __init__(self, data): self.data = data
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, size): return self.data[:size]
    def opener(request, timeout):
        urls.append(request.full_url)
        if 'api.github.com' in request.full_url:
            return Response(json.dumps({'encoding':'base64','content':base64.b64encode(json.dumps(new).encode()).decode()}).encode())
        return Response(json.dumps(old).encode())
    result = fetch_decision_candles(now=NOW, opener=opener, direct_url=None)
    assert result['as_of'] == NOW.isoformat()
    assert len(urls) == 3
    assert '/refs/heads/' in urls[1]
    assert '&slot=' in urls[2]
    assert result['bars']['M5'][-1]['closed_at'] == NOW.isoformat()


def test_delivery_diagnostics_do_not_leak_http_url_or_body():
    from urllib.error import HTTPError
    from fx_scanner.xau_decision_candle_feed_v1 import fetch_decision_candles
    def opener(request, timeout):
        raise HTTPError('https://host/?private_token=SECRET',429,'SECRET',{},None)
    with pytest.raises(ValueError) as raised:
        fetch_decision_candles(now=NOW, opener=opener, direct_url=None)
    message = str(raised.value)
    assert 'raw=HTTP_429' in message and 'api=HTTP_429' in message
    assert 'SECRET' not in message and 'https' not in message


def test_raw_ref_recovers_latest_candle_without_calling_rate_limited_api():
    import json
    from io import BytesIO
    from fx_scanner.xau_decision_candle_feed_v1 import fetch_decision_candles
    old = make_payload(fake_series(now=NOW-timedelta(minutes=5)), now=NOW-timedelta(minutes=5))
    new = make_payload(fake_series(), now=NOW)
    urls = []
    def opener(request, timeout):
        urls.append(request.full_url)
        assert 'api.github.com' not in request.full_url
        return BytesIO(json.dumps(new if '/refs/heads/' in request.full_url else old).encode())
    assert fetch_decision_candles(now=NOW, opener=opener, direct_url=None) == new
    assert len(urls) == 2


def test_api_403_keeps_valid_history_but_never_revives_expired_setup():
    import json
    from io import BytesIO
    from urllib.error import HTTPError
    from fx_scanner.xau_decision_candle_feed_v1 import fetch_decision_candles
    from fx_scanner.xau_technical_engine_v1 import evaluate_technical
    old = make_payload(fake_series(now=NOW-timedelta(minutes=5)), now=NOW)
    def opener(request, timeout):
        if 'api.github.com' in request.full_url:
            raise HTTPError(request.full_url, 403, 'rate limit', {}, None)
        return BytesIO(json.dumps(old).encode())
    feed = fetch_decision_candles(now=NOW, opener=opener, direct_url=None)
    assert feed['as_of'] == old['as_of']
    report = evaluate_technical(feed, now=NOW)
    assert report['direction'] == 'WAIT'
    assert report['BUY']['state'] == 'WAIT_CANDLE'
    assert report['BUY']['plan'] is None


def test_old_raw_and_api_403_still_fail_closed():
    import json
    from io import BytesIO
    from urllib.error import HTTPError
    from fx_scanner.xau_decision_candle_feed_v1 import fetch_decision_candles
    old = make_payload(fake_series(now=NOW-timedelta(minutes=20)), now=NOW-timedelta(minutes=20))
    def opener(request, timeout):
        if 'api.github.com' in request.full_url:
            raise HTTPError(request.full_url, 403, 'rate limit', {}, None)
        return BytesIO(json.dumps(old).encode())
    with pytest.raises(ValueError, match='CLOSED_CANDLE_FEED_STALE_OR_UNAVAILABLE'):
        fetch_decision_candles(now=NOW, opener=opener, direct_url=None)

from types import SimpleNamespace

import pytest

from fx_scanner import demo_crypto_broker_preflight as preflight
from fx_scanner.exceptions import CollectorUnavailable


def _policy(max_attempts=3):
    return SimpleNamespace(
        runtime={
            "reconnect": {
                "max_attempts": max_attempts,
                "backoff_initial_seconds": 0,
                "backoff_multiplier": 2,
                "backoff_max_seconds": 0,
            }
        }
    )


def test_preflight_retries_only_transient_connection_timeout(monkeypatch):
    calls = []
    feed = object()

    def fake_builder(_policy, symbols):
        calls.append(tuple(symbols))
        if len(calls) < 3:
            raise CollectorUnavailable("cTrader connection timeout")
        return feed

    monkeypatch.setattr(preflight, "build_ctrader_research_feed", fake_builder)

    result = preflight._build_feed_with_bounded_retry(_policy(), ("BTCUSD", "ETHUSD"))

    assert result is feed
    assert len(calls) == 3


def test_preflight_does_not_retry_non_transient_broker_contract_error(monkeypatch):
    calls = []

    def fake_builder(_policy, symbols):
        calls.append(tuple(symbols))
        raise CollectorUnavailable("unknown cTrader symbols: RPLUSD")

    monkeypatch.setattr(preflight, "build_ctrader_research_feed", fake_builder)

    with pytest.raises(CollectorUnavailable, match="unknown cTrader symbols"):
        preflight._build_feed_with_bounded_retry(_policy(), ("RPLUSD",))

    assert len(calls) == 1


def test_preflight_still_fails_closed_after_bounded_timeouts(monkeypatch):
    calls = []

    def fake_builder(_policy, symbols):
        calls.append(tuple(symbols))
        raise CollectorUnavailable("cTrader connection timeout")

    monkeypatch.setattr(preflight, "build_ctrader_research_feed", fake_builder)

    with pytest.raises(CollectorUnavailable, match="cTrader connection timeout"):
        preflight._build_feed_with_bounded_retry(_policy(max_attempts=3), ("BTCUSD",))

    assert len(calls) == 3

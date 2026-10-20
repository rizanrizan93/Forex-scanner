"""Sidecar inputs cannot alter the original zone or Candidate-A decision."""
from datetime import UTC, datetime, timedelta

from fx_scanner.manual_reversal_orderflow import SIDECAR_CONTRACT, zone_liquidity_state

NOW = datetime(2026, 10, 20, 11, 0, tzinfo=UTC)
ZONE = {"zone_id": "h1-buy", "direction": "BUY",
        "available_at": (NOW - timedelta(hours=1)).isoformat()}


def sample(**overrides):
    base = {"zone_id": "h1-buy", "symbol": "XAUUSD", "source": "CTRADER_LEVEL_II",
            "window_start": (NOW - timedelta(seconds=10)).isoformat(),
            "window_end": NOW.isoformat(), "depth_updates": 10,
            "mapped_zone_overlap": True, "depth_imbalance": .9,
            "near_wall_retention": .9, "near_wall_pull_ratio": .05}
    return {**base, **overrides}


def sidecar(observation=None, **overrides):
    base = {"contract": SIDECAR_CONTRACT, "symbol": "XAUUSD",
            "execution_authority": False, "execution_influence": False,
            "observations": [observation if observation is not None else sample()]}
    return {**base, **overrides}


def test_no_feed_fails_closed():
    result = zone_liquidity_state(ZONE, None, now=NOW)
    assert result["state"] == "NO_DATA" and result["probability"] is None
    assert not result["execution_authority"] and not result["execution_influence"]


def test_actual_broker_depth_labeled_not_bookmap():
    result = zone_liquidity_state(ZONE, sidecar(), now=NOW)
    assert result["state"] == "SUPPORTIVE"
    assert result["source"] == "CTRADER_LEVEL_II"
    assert result["reason"] == "DEPTH_ONLY_UNCALIBRATED"
    assert "cvd" not in result["components"]


def test_duplicate_zone_or_unsafe_contract_is_unavailable():
    assert zone_liquidity_state(ZONE, sidecar(observations=[sample(), sample()]), now=NOW)["state"] == "NO_DATA"
    assert zone_liquidity_state(ZONE, sidecar(contract="WRONG"), now=NOW)["state"] == "NO_DATA"
    assert zone_liquidity_state(ZONE, sidecar(execution_influence=True), now=NOW)["state"] == "NO_DATA"


def test_stale_future_wrong_market_fails_closed():
    assert zone_liquidity_state(ZONE, sidecar(), now=NOW + timedelta(seconds=91))["state"] == "STALE"
    assert zone_liquidity_state(ZONE, sidecar(sample(window_end=(NOW + timedelta(seconds=3)).isoformat())), now=NOW)["state"] == "NO_DATA"
    assert zone_liquidity_state(ZONE, sidecar(sample(source="CME_GC")), now=NOW)["state"] == "NO_DATA"

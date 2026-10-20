from datetime import UTC, datetime, timedelta

from fx_scanner.manual_reversal_orderflow import SIDECAR_CONTRACT, zone_liquidity_state

NOW = datetime(2026, 10, 20, 11, 0, tzinfo=UTC)
ZONE = {"zone_id": "h1-buy", "direction": "BUY",
        "available_at": (NOW - timedelta(hours=1)).isoformat()}


def sample(**kw):
    return {"zone_id": "h1-buy", "symbol": "XAUUSD", "source": "CTRADER_LEVEL_II",
            "window_start": (NOW - timedelta(seconds=10)).isoformat(),
            "window_end": NOW.isoformat(), "depth_updates": 10,
            "mapped_zone_overlap": True, "depth_imbalance": 0.9,
            "near_wall_retention": 0.9, "near_wall_pull_ratio": 0.05, **kw}


def sidecar(obs=None, **kw):
    return {"contract": SIDECAR_CONTRACT, "symbol": "XAUUSD",
            "execution_authority": False, "execution_influence": False,
            "observations": [obs or sample()], **kw}


def test_missing_source_is_explicit_and_does_not_change_manual_watch():
    result = zone_liquidity_state(ZONE, None, now=NOW)
    assert result["state"] == "NO_DATA" and result["probability"] is None
    assert result["execution_authority"] is False and result["execution_influence"] is False


def test_valid_broker_depth_is_depth_only_not_bookmap_trades():
    result = zone_liquidity_state(ZONE, sidecar(), now=NOW)
    assert result["state"] == "SUPPORTIVE"
    assert result["source"] == "CTRADER_LEVEL_II"
    assert result["reason"] == "DEPTH_ONLY_UNCALIBRATED"
    assert "cvd" not in result["components"]


def test_duplicate_zone_wrong_contract_and_active_sidecar_cannot_override():
    assert zone_liquidity_state(ZONE, sidecar(observations=[sample(), sample()]), now=NOW)["state"] == "NO_DATA"
    assert zone_liquidity_state(ZONE, sidecar(contract="WRONG"), now=NOW)["state"] == "NO_DATA"
    assert zone_liquidity_state(ZONE, sidecar(execution_influence=True), now=NOW)["state"] == "NO_DATA"


def test_stale_future_and_bad_source_fail_closed():
    assert zone_liquidity_state(ZONE, sidecar(), now=NOW + timedelta(seconds=91))["state"] == "STALE"
    future = sample(window_end=(NOW + timedelta(seconds=3)).isoformat())
    assert zone_liquidity_state(ZONE, sidecar(future), now=NOW)["state"] == "NO_DATA"
    bad = sample(source="CME_GC")
    assert zone_liquidity_state(ZONE, sidecar(bad), now=NOW)["state"] == "NO_DATA"

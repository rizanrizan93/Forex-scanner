"""RLFE is a read-only research layer and must never synthesize Bookmap flow."""
from datetime import UTC, datetime, timedelta

import pytest
from fx_scanner.reversal_liquidity_fusion import evaluate_zone_orderflow, CONTRACT

NOW = datetime(2026, 10, 20, 10, 0, tzinfo=UTC)
ZONE = {"zone_id": "H1-D-1", "direction": "BUY",
        "available_at": (NOW - timedelta(hours=2)).isoformat()}


def event(**overrides):
    base = {"zone_id": "H1-D-1", "symbol": "XAUUSD", "source": "CME_GC",
            "window_start": (NOW - timedelta(seconds=10)).isoformat(),
            "window_end": NOW.isoformat(), "depth_updates": 30,
            "mapped_zone_overlap": True, "mapping_error_atr": .03,
            "depth_imbalance": .5, "near_wall_retention": .95,
            "near_wall_pull_ratio": .05, "trade_count": 25,
            "signed_cvd_change": .5, "signed_absorption": .5}
    return {**base, **overrides}


def test_no_feed_does_not_claim_probability_or_entry_authority():
    row = evaluate_zone_orderflow(ZONE, None, now=NOW)
    assert row["contract"] == CONTRACT and row["state"] == "NO_DATA"
    assert row["support_index"] is None and row["probability"] is None
    assert row["execution_authority"] is False and row["execution_influence"] is False


def test_buy_sell_directional_and_only_descriptive():
    buy = evaluate_zone_orderflow(ZONE, event(), now=NOW)
    sell = evaluate_zone_orderflow({**ZONE, "direction": "SELL"}, event(), now=NOW)
    assert buy["state"] == "SUPPORTIVE" and buy["support_index"] > sell["support_index"]
    assert sell["state"] == "OPPOSING"
    assert buy["probability"] is None and buy["research_only"]


def test_stale_future_wrong_zone_and_bad_future_basis():
    assert evaluate_zone_orderflow(ZONE, event(), now=NOW + timedelta(seconds=21))["state"] == "STALE"
    assert evaluate_zone_orderflow(ZONE, event(zone_id="other"), now=NOW)["state"] == "NO_DATA"
    assert evaluate_zone_orderflow(ZONE, event(window_end=(NOW + timedelta(seconds=1)).isoformat()), now=NOW)["state"] == "NO_DATA"
    assert evaluate_zone_orderflow(ZONE, event(mapping_error_atr=.3), now=NOW)["state"] == "NO_DATA"


def test_ctrader_depth_never_impersonates_exchange_trades():
    observation = event(source="CTRADER_LEVEL_II",
                        trade_count=1000, signed_cvd_change=1., signed_absorption=1.)
    result = evaluate_zone_orderflow(ZONE, observation, now=NOW)
    assert result["reason"].startswith("DEPTH_ONLY")
    assert "cvd" not in result["components"] and "absorption" not in result["components"]


def test_invalid_ohlc_proxy_and_naive_time_rejected():
    with pytest.raises(ValueError):
        evaluate_zone_orderflow(ZONE, event(depth_imbalance=float("nan")), now=NOW)
    with pytest.raises(ValueError):
        evaluate_zone_orderflow(ZONE, event(), now=NOW.replace(tzinfo=None))


def test_eur_and_btc_have_separate_venue_contracts():
    eur_zone = {**ZONE, "zone_id": "eur-h1"}
    eur = event(zone_id="eur-h1", symbol="EURUSD", source="CME_6E")
    assert evaluate_zone_orderflow(eur_zone, eur, symbol="EURUSD", now=NOW)["state"] == "SUPPORTIVE"
    btc_zone = {**ZONE, "zone_id": "btc-h1"}
    btc = event(zone_id="btc-h1", symbol="BTCUSD", source="CRYPTO_PERP")
    assert evaluate_zone_orderflow(btc_zone, btc, symbol="BTCUSD", now=NOW)["state"] == "SUPPORTIVE"
    assert evaluate_zone_orderflow(btc_zone, btc, symbol="XAUUSD", now=NOW)["state"] == "NO_DATA"

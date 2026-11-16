"""Fail-closed tests for Frozen V1 read-only buy/sell candle-evidence ranking."""
from datetime import datetime, timedelta, timezone

from fx_scanner.frozen_v1_directional_score import evaluate_bias

NOW = datetime(2026, 11, 16, 15, 0, tzinfo=timezone.utc)


def bars(frame, count, now=NOW, *, price=100.0):
    minutes = {"M1": 1, "M5": 5, "H1": 60, "H4": 240}[frame]
    return [
        {
            "timestamp": (now - timedelta(minutes=(count-i)*minutes)).isoformat(),
            "open": price, "high": price + 1,
            "low": price - 1, "close": price + .1, "volume": 1.,
        }
        for i in range(count)
    ]


def market():
    h = bars("H1", 11)
    h[-1].update(open=101., high=116., low=100., close=115.)
    m = bars("M5", 7)
    m[-1].update(open=100., high=106., low=99., close=105.)
    return {
        "contract": "RIZAN_BOOTSTRAP125_MARKET_READONLY_V1",
        "account_suffix": "7903", "read_only": True,
        "execution_authority": False, "observed_at": NOW.isoformat(),
        "bars": {"XAUUSD": {"H1": h, "M5": m}},
    }


def test_xau_buy_dominant_from_closed_frozen_displacement_and_compression():
    report = evaluate_bias(market(), phase="GROWTH", now=NOW)
    xau = report["symbols"]["XAUUSD"]
    assert xau["BUY"]["score"] == 100
    assert xau["SELL"]["score"] < 50
    assert xau["bias"] == "BUY LEBIH KUAT"
    assert len(xau["BUY"]["families"]) == 2
    assert report["order_enabled"] is False
    assert report["score_is_native_signal"] is False
    assert xau["native_order_signal"] == "NOT_EVALUATED"


def test_stale_or_wrong_account_or_unapproved_market_disables_score():
    for mutation in ("stale", "account", "contract", "authority", "read_only"):
        snapshot = market()
        now = NOW
        if mutation == "stale":
            now = NOW + timedelta(minutes=4)
        elif mutation == "account":
            snapshot["account_suffix"] = "1234"
        elif mutation == "contract":
            snapshot["contract"] = "DEMO_WRONG"
        elif mutation == "authority":
            snapshot["execution_authority"] = True
        else:
            snapshot["read_only"] = False
        result = evaluate_bias(snapshot, phase="GROWTH", now=now)
        x = result["symbols"]["XAUUSD"]
        assert x["bias"] == "WAIT DATA", mutation
        assert x["BUY"]["score"] is None, mutation


def test_phase_seed_blocks_xau_and_btc_and_sell_eur():
    snapshot = market()
    snapshot["bars"]["EURUSD"] = {"M5": bars("M5", 65)}
    r = evaluate_bias(snapshot, phase="SEED", now=NOW)["symbols"]
    assert r["XAUUSD"]["BUY"]["score"] is None
    assert r["XAUUSD"]["bias"] == "FASE TIDAK AKTIF"
    assert r["BTCUSD"]["bias"] == "FASE TIDAK AKTIF"
    assert r["EURUSD"]["SELL"]["score"] is None
    assert "BUY SAJA" in r["EURUSD"]["bias"]


def test_seed_buy_full_market_subset_has_no_sell_score():
    snapshot = market()
    m5 = bars("M5", 65)
    m5[-1].update(open=100., high=106., low=99., close=105.)
    h4 = bars("H4", 1024, now=NOW - timedelta(hours=3))
    for i, row in enumerate(h4):
        value = 90. + i*.02
        row.update(open=value, close=value+.01, high=value+1, low=value-1)
    snapshot["bars"]["EURUSD"] = {"M5": m5, "H4": h4}
    result = evaluate_bias(snapshot, phase="SEED", now=NOW)["symbols"]["EURUSD"]
    assert result["BUY"]["score"] == 100
    assert result["SELL"]["score"] is None
    assert result["BUY"]["coverage"] == 100


def test_eur_growth_score_from_complete_15x_m1_m15_no_future_aggregation():
    snapshot = market()
    m1 = bars("M1", 150)
    # The newest 15-minute block sweeps its prior M15 low, then reclaims.
    m1[-15].update(open=100., low=98., high=101., close=100.1)
    m1[-1].update(open=100., high=101., low=99., close=100.9)
    snapshot["bars"]["EURUSD"] = {"M1": m1}
    result = evaluate_bias(snapshot, phase="GROWTH", now=NOW)["symbols"]["EURUSD"]
    assert result["BUY"]["score"] == 100
    assert result["bias"] == "BUY LEBIH KUAT"
    snapshot["bars"]["EURUSD"]["M1"].pop(-10)  # incomplete M15 block
    result = evaluate_bias(snapshot, phase="GROWTH", now=NOW)["symbols"]["EURUSD"]
    assert result["BUY"]["score"] is None
    assert result["bias"] == "WAIT DATA"


def test_btc_native_bitstamp_not_in_broker_market_snapshot():
    result = evaluate_bias(market(), phase="GROWTH", now=NOW)["symbols"]["BTCUSD"]
    assert result["BUY"]["score"] is None
    assert result["SELL"]["score"] is None
    assert "BITSTAMP" in result["reason"]
    assert result["bias"] == "WAIT DATA"


def test_forming_or_corrupted_broker_bar_cannot_promote_direction():
    for mutation in ("forming", "nan", "unordered"):
        snapshot = market()
        series = snapshot["bars"]["XAUUSD"]["M5"]
        if mutation == "forming":
            series[-1]["timestamp"] = NOW.isoformat()
        elif mutation == "nan":
            series[-1]["close"] = float("nan")
        else:
            series[-1]["timestamp"] = series[-2]["timestamp"]
        result = evaluate_bias(snapshot, phase="GROWTH", now=NOW)["symbols"]["XAUUSD"]
        assert all(x["family"] != "XAU compression M5" for x in (
            [result["BUY"]] if result["BUY"]["family"] else []
        )) or result["BUY"]["score"] == 100  # H1 valid independent family
        assert result["BUY"]["families"][1]["score"] is None, mutation
        assert result["BUY"]["families"][1]["coverage"] == 0


def test_unknown_phase_returns_wait_and_no_fake_positive():
    result = evaluate_bias(market(), phase="UNKNOWN", now=NOW)
    for item in result["symbols"].values():
        assert item["bias"] == "WAIT DATA"
        assert item["BUY"]["score"] is None

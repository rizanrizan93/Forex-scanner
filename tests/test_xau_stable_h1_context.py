"""Stable H1 context tests; rapid M5 signals stay completely independent."""
from datetime import datetime, timedelta, timezone

from fx_scanner.xau_stable_h1_context import (
    from_research_candles, from_v1_market, explain_vs_fast,
)

NOW = datetime(2026, 11, 16, 15, 0, tzinfo=timezone.utc)


def _rows(count, trend, *, native):
    out = []
    for i in range(count):
        close = 100 + trend * i * .85
        close_at = NOW - timedelta(hours=count - 1 - i)
        at = close_at - timedelta(hours=1) if native else close_at
        row = {
            "open": close - .25 if trend >= 0 else close + .25,
            "high": close + 1, "low": close - 1, "close": close,
            "volume": 2,
        }
        row["timestamp" if native else "closed_at"] = at.isoformat()
        out.append(row)
    return out


def v1(trend=1):
    return {
        "contract": "RIZAN_BOOTSTRAP125_MARKET_READONLY_V1",
        "account_suffix": "7903", "read_only": True, "execution_authority": False,
        "observed_at": NOW.isoformat(),
        "bars": {"XAUUSD": {"H1": _rows(11, trend, native=True)}},
    }


def research(trend=1):
    return {
        "contract": "RIZAN_XAU_CLOSED_CANDLES_READONLY_V1",
        "symbol": "XAUUSD", "account_suffix": "7903",
        "source": "CTRADER_MARKET_DATA_READ_ONLY",
        "execution_authority": False, "execution_influence": False,
        "as_of": NOW.isoformat(),
        "bars": {"H1": _rows(210, trend, native=False)},
    }


def test_same_uptrend_yields_stable_buy_on_both_independent_sources():
    a = from_v1_market(v1(), NOW)
    b = from_research_candles(research(), NOW)
    assert a["direction"] == "BUY"
    assert b["direction"] == "BUY"
    assert a["last_h1_close"] == b["last_h1_close"] == NOW.isoformat()
    assert a["order_enabled"] is False and b["order_enabled"] is False
    assert "KONTRA H1" in explain_vs_fast(a, "SELL")
    assert "SEARAH" in explain_vs_fast(a, "BUY")


def test_downtrend_yields_sell_and_flat_yields_neutral():
    assert from_v1_market(v1(-1), NOW)["direction"] == "SELL"
    assert from_research_candles(research(-1), NOW)["direction"] == "SELL"
    assert from_v1_market(v1(0), NOW)["direction"] == "NETRAL"
    assert "RANGE/TRANSISI" in explain_vs_fast(
        from_v1_market(v1(0), NOW), "BUY"
    )


def test_one_h1_opposite_displacement_does_not_instant_flip_regime():
    feed = v1(1)
    last = feed["bars"]["XAUUSD"]["H1"][-1]
    last.update(open=100., high=109., low=98., close=99.)
    result = from_v1_market(feed, NOW)
    assert result["direction"] != "SELL"


def test_stale_wrong_account_and_untrusted_source_fail_closed():
    s = v1()
    s["observed_at"] = (NOW - timedelta(minutes=4)).isoformat()
    assert from_v1_market(s, NOW)["direction"] == "WAIT DATA"
    s = v1()
    s["account_suffix"] = "OTHER"
    assert from_v1_market(s, NOW)["direction"] == "WAIT DATA"
    s = research()
    s["source"] = "PUBLIC_CSV"
    assert from_research_candles(s, NOW)["direction"] == "WAIT DATA"


def test_h1_gap_is_not_synthetic_two_bar_confirmation():
    feed = v1()
    # Latest H1 closes at NOW while preceding H1 closes two hours earlier.
    feed["bars"]["XAUUSD"]["H1"][-2]["timestamp"] = (
        NOW - timedelta(hours=3)
    ).isoformat()
    assert from_v1_market(feed, NOW)["direction"] == "WAIT DATA"


def test_no_h1_data_never_uses_fast_m5_to_impute_trend():
    assert from_v1_market({}, NOW)["direction"] == "WAIT DATA"
    assert from_research_candles({}, NOW)["direction"] == "WAIT DATA"
    assert "WAIT DATA" in explain_vs_fast({"direction": "WAIT DATA"}, "BUY")

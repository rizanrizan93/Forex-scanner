"""R6 ForexScanner manual zones: deterministic source, timing and no-trade tests."""
from datetime import UTC, datetime
import pandas as pd
import pytest

from fx_scanner.fed_r6_manual_entry_areas import (
    CONTRACT, _completed_tf, confirmed_pivots,
    evaluate_areas, verified_macro_direction
)

NOW = pd.Timestamp("2026-11-20T08:50:05+00:00")

def candles():
    idx = pd.date_range(end="2026-11-20T08:49:00Z",
                        periods=4000,freq="min",tz="UTC")
    d = pd.DataFrame({"open":100., "high":100.1, "low":99.9,
                      "close":100.},index=idx)
    # Synthetic distinct demand and supply pivots; both visible only
    # after two following complete M5 bars.
    d.iloc[-90,d.columns.get_loc("low")] = 96.
    d.iloc[-65,d.columns.get_loc("high")] = 104.
    return d

def evaluation(**kwargs):
    defaults={"now":NOW,"bid":99.95,"ask":100.05,
              "quote_at":NOW-pd.Timedelta(seconds=5),
              "news_events":[]}
    defaults.update(kwargs)
    return evaluate_areas(candles(),**defaults)

def test_both_buy_sell_watch_zones_derive_from_real_completed_m5_not_guesses():
    r = evaluation()
    assert r["contract"]==CONTRACT
    assert r["status"]=="WATCH"
    assert r["macro_direction"]=="WAIT"
    assert r["entry_allowed"] is False
    assert r["authority_to_send_orders"] is False
    assert {z["side"] for z in r["zones"]}=={"BUY","SELL"}
    for z in r["zones"]:
        assert z["confirmed_at"]>z["formed_at"]
        assert z["low"] < z["high"]
        assert z["entry_eligible"] is False
        assert z["macro_alignment"]=="WAIT"
        assert z["checks"]["MACRO_R4_VERIFIED"] is False
        assert z["tp1_scenario"] is not None
        assert z["sl_scenario"] is not None
    buy=next(x for x in r["zones"] if x["side"]=="BUY")
    sell=next(x for x in r["zones"] if x["side"]=="SELL")
    assert buy["sl_scenario"]<buy["entry_reference"]<buy["tp1_scenario"]
    assert sell["tp1_scenario"]<sell["entry_reference"]<sell["sl_scenario"]

def test_source_m1_open_not_promoted_before_candle_close():
    d=candles()
    at=d.index[-1]+pd.Timedelta(seconds=20)
    d5=_completed_tf(d,5,at)
    assert all(x<=at for x in d5.index)
    r=evaluate_areas(d,now=at,bid=100,ask=100.1,quote_at=at,
                     news_events=[])
    assert r["last_closed_m1"]==(d.index[-2]+pd.Timedelta(minutes=1)).isoformat()

def test_m5_pivot_known_only_after_two_completed_right_bars():
    d=candles()
    m5=_completed_tf(d,5,NOW)
    pivots=confirmed_pivots(m5,NOW)
    lows=[x for x in pivots if x["kind"]=="SWING_LOW" and x["price"]==96]
    highs=[x for x in pivots if x["kind"]=="SWING_HIGH" and x["price"]==104]
    assert len(lows)==1 and len(highs)==1
    assert pd.Timestamp(lows[0]["confirmed_at"])>pd.Timestamp(lows[0]["pivot_at"])
    right_cut=pd.Timestamp(highs[0]["pivot_at"])+pd.Timedelta(minutes=5)
    assert not any(x["price"]==104 for x in
                   confirmed_pivots(m5[m5.index<=right_cut],right_cut))

def test_stale_m1_suppresses_all_numeric_live_zones():
    r = evaluation(now=NOW+pd.Timedelta(minutes=5),
                   quote_at=NOW+pd.Timedelta(minutes=5))
    assert r["status"]=="WAIT"
    assert r["price"] is None
    assert r["zones"]==[]

def test_macro_buy_not_inferred_from_direction_only():
    r = evaluation(macro={"direction":"BUY","watch_bias":"SEARCH_BUY_DIP"})
    assert r["macro_direction"]=="WAIT"
    assert all(z["entry_eligible"] is False for z in r["zones"])

def test_wrong_fomc_macro_side_must_wait():
    m={
        "contract":"FED_R4_POLICY_INFORMATION_XAU_READONLY_V1",
        "market_data_status":"VALIDATED_CAPTURED_PRE_POST_INTRADAY",
        "policy_information_regime":"POLICY_LIKE",
        "event_id":"FOMC_TEST","direction":"SELL",
        "watch_bias":"SEARCH_BUY_DIP",
        "authority_to_send_orders":False,"authority_to_deploy":False,
        "predicted_probability":None,"verified_80pct_both_sides":False,
        "release_at":"2026-11-20T08:00:00Z",
        "decision_at":"2026-11-20T08:49:00Z",
    }
    assert verified_macro_direction(m,NOW)==("WAIT","CONTRADICTORY_R4_DIRECTION")
    m["watch_bias"]="SEARCH_SELL_REBOUND"
    assert verified_macro_direction(m,NOW)==("SELL","VALID_R4_READONLY_WATCH")
    m["decision_at"]="2026-11-20T08:25:00Z"
    assert verified_macro_direction(m,NOW)[0]=="WAIT"
    m["decision_at"]="2026-11-20T08:49:00Z"
    m["market_data_status"]="EXPOST_USMPD"
    assert verified_macro_direction(m,NOW)[0]=="WAIT"

def test_quote_stale_zone_is_watch_only_with_no_trigger():
    r=evaluation(quote_at=NOW-pd.Timedelta(seconds=120))
    assert r["quote_at"] is None
    assert "QUOTE_UNAVAILABLE" in r["reason"]
    assert all(z["checks"]["QUOTE_SPREAD_FRESH"] is False for z in r["zones"])

def test_missing_calendar_blocks_entries():
    r=evaluation(news_events=None)
    assert r["news_reason"]=="CALENDAR_UNVERIFIED"
    assert all(z["checks"]["NEWS_WINDOW_OK"] is False for z in r["zones"])

def test_duplicate_or_invalid_ohlc_fails_closed():
    d=candles()
    dupe=pd.concat([d,d.tail(1)])
    assert evaluate_areas(dupe,now=NOW)["zones"]==[]
    d.iloc[-1,d.columns.get_loc("low")]=105
    assert evaluate_areas(d,now=NOW)["reason"]=="INVALID_M1_OHLC"

def test_old_or_already_broken_pivot_cannot_be_used():
    d=candles()
    # Subsequent completed M5 closes below low of an old swing.
    # A whole five-minute candle closes BELOW the old swing 96.\n    # One stray M1 wick would be merely a touch, not an M5 break.\n    start=pd.Timestamp("2026-11-20T08:30:00Z")\n    end=start+pd.Timedelta(minutes=4)\n    d.loc[start:end,["open","high","low","close"]]=[94.5,95.,94.,94.5]
    r=evaluate_areas(d,now=NOW,bid=99.95,ask=100.05,quote_at=NOW,news_events=[])
    assert not any(z["side"]=="BUY" and abs(z["low"]-96)<0.001
                   for z in r["zones"])

def test_hardcoded_old_m1_timestamp_never_pretends_current_entry():
    r=evaluation(now=NOW+pd.Timedelta(hours=72))
    assert r["price"] is None
    assert r["entry_allowed"] is False

"""R6.1 macro source provenance and directional-context regression tests.

These use synthetic source fixtures and are NOT trading performance.
"""
from unittest.mock import patch
import pandas as pd
from fx_scanner.fed_r61_operational_macro_direction import assess_market_direction,CONTRACT
from fx_scanner.fed_r6_manual_entry_areas import evaluate_areas

NOW=pd.Timestamp("2026-11-20T02:49:10Z").to_pydatetime()

def worker(*,two_year=-4,ten_year=-3,dxy_pct=.0038,zn="YIELD_DOWN_PROXY",
           dxy_at="2026-11-20T02:48:00Z",zn_at="2026-11-20T02:48:30Z",
           daily_at="2026-11-19T00:00:00Z",health="FRESH"):
    component={
      name:{"current":v,"delta":delta,"delta_unit":"BPS","provider":"US_TREASURY_DAILY_XML",
            "freshness":health,"observed_at":daily_at}
      for name,v,delta in (("US2Y",4.76,two_year),("US10Y",5.04,ten_year))
    }
    return {"evaluation":{
        "components":component,"broader_macro_bias":"BULLISH_XAU",
        "attribution_quality":{"quality_state":"WAIT_DAILY_DATA",
                               "quality_screened_bias":"UNAVAILABLE"},
        "dxy_intraday":{"available":True,"source":"YAHOO_FINANCE_ICE_DXY_PROXY",
                        "current":103.886,"net_pct":dxy_pct,"current_at":dxy_at},
        "intraday_yield_context":{
            "available":True,"timing_basis":"TREASURY_FUTURES_PROXY",
            "futures_price":106.125,"futures_at":zn_at,
            "futures_yield_pressure":zn,
            "current_at":"2026-11-19T19:59:00Z",
            "gold_implication":"GOLD_SUPPORT",
            "source":"CASH_LAST_VALID_PLUS_ZN_FUTURES_PROXY"},
    },"observed_at":"2026-11-20T02:48:59Z",
      "published_at":"2026-11-20T02:49:00Z"}

def classify(w):
    with patch("fx_scanner.fed_r61_operational_macro_direction.macro_input",return_value=w):
        return assess_market_direction({"synthetic":"unit fixture"},now=NOW)

def test_realistic_20nov_daily_yields_down_dxy_flat_is_buy_indicative_not_r4():
    x=classify(worker())
    assert x["contract"]==CONTRACT
    assert x["direction"]=="WAIT"
    assert x["daily_direction"]=="BUY"
    assert x["strength"]=="WAIT_FOR_DXY_CONFLUENCE"
    assert x["mode"]=="OFFICIAL_DAILY_LEAN_ONLY"
    assert x["dxy_direction"]=="FLAT"
    assert x["quality_state"]=="WAIT_DAILY_DATA"
    assert x["entry_permission"] is False
    assert x["validated_fed_r4"] is False
    assert x["execution_authority"] is False

def test_both_fresh_dxy_yield_aligned_up_gold_strengthens_context_not_orders():
    x=classify(worker(dxy_pct=-.12))
    assert x["direction"]=="BUY"
    assert x["strength"]=="ALIGNED_MARKET_CONTEXT"
    assert x["mode"]=="INTRADAY_AND_DAILY_ALIGNED"
    assert x["entry_permission"] is False

def test_down_gold_from_live_dollar_blocks_bullish_daily_yield():
    x=classify(worker(dxy_pct=.12))
    assert x["direction"]=="WAIT"
    assert x["strength"]=="CONFLICT"
    assert x["reason"]=="LIVE_DXY_AND_YIELD_CONFLICT_OR_DAILY_DIVERGENCE"

def test_both_daily_yields_up_and_intraday_concur_is_sell():
    x=classify(worker(two_year=4,ten_year=3,dxy_pct=.18,zn="YIELD_UP_PROXY"))
    assert x["direction"]=="SELL"
    assert x["strength"]=="ALIGNED_MARKET_CONTEXT"
    assert x["dxy_direction"]=="SELL"
    assert x["yield_intraday_direction"]=="SELL"

def test_stale_dxy_does_not_become_live_sell():
    x=classify(worker(dxy_pct=.23,dxy_at="2026-11-20T02:31:00Z"))
    assert x["direction"]=="WAIT"
    assert x["daily_direction"]=="BUY"
    assert x["strength"]=="WAIT_FOR_DXY_CONFLUENCE"
    assert not x["dxy"]["fresh"]

def test_stale_zn_does_not_use_old_cash_time():
    x=classify(worker(dxy_pct=-.12,zn_at="2026-11-20T02:20:00Z"))
    assert x["direction"]=="BUY"
    assert x["strength"]=="YIELD_DXY_DIRECTIONAL_CONTEXT"
    assert x["intraday_yield"]["available_for_direction"] is False
    assert x["intraday_yield"]["cash_yield_claimed_from_futures"] is False

def test_conflicting_yields_or_aged_official_rows_wait():
    for w in (worker(two_year=-4,ten_year=3),worker(health="STALE"),
              worker(daily_at="2026-11-13T00:00:00Z")):
        x=classify(w)
        assert x["direction"]=="WAIT"
        assert x["entry_permission"] is False

def test_untrusted_worker_payload_waits_and_never_promotes_legacy_bias():
    with patch("fx_scanner.fed_r61_operational_macro_direction.macro_input",
               side_effect=ValueError("stale publish")):
        x=assess_market_direction({"bad":"payload"},now=NOW)
    assert x["direction"]=="WAIT"
    assert x["validated_fed_r4"] is False

def test_isolated_existing_r6_manual_zones_do_not_inherit_r61_trading_authority():
    idx=pd.date_range(end="2026-11-20T02:48:00Z",periods=4000,freq="min",tz="UTC")
    bars=pd.DataFrame({"open":100.0,"high":100.1,"low":99.9,"close":100.0},index=idx)
    bars.iloc[-90,bars.columns.get_loc("low")]=96.0
    bars.iloc[-65,bars.columns.get_loc("high")]=104.0
    context=classify(worker())
    r=evaluate_areas(bars,now=NOW,bid=99.95,ask=100.05,
                     quote_at=NOW,news_events=[],market_context=context)
    assert r["market_context"]["direction"]=="WAIT"
    assert r["market_context"]["daily_direction"]=="BUY"
    assert r["macro_direction"]=="WAIT" and r["entry_allowed"] is False
    assert r["authority_to_send_orders"] is False
    assert all(z["market_context_alignment"]=="WAIT" for z in r["zones"])
    assert all(z["entry_eligible"] is False for z in r["zones"])

def test_flat_dxy_does_not_promote_daily_yield_lean_to_trade_direction():
    x=classify(worker(dxy_pct=0.0,zn="YIELD_DOWN_PROXY"))
    assert x["daily_direction"]=="BUY"
    assert x["direction"]=="WAIT"
    assert x["entry_permission"] is False

def test_yield_and_dxy_agree_with_stale_zn_context_still_not_fomc_r4():
    x=classify(worker(dxy_pct=-0.06,zn_at="2026-11-20T01:00:00Z"))
    assert x["direction"]=="BUY"
    assert x["strength"]=="YIELD_DXY_DIRECTIONAL_CONTEXT"
    assert x["validated_fed_r4"] is False
    assert x["entry_permission"] is False

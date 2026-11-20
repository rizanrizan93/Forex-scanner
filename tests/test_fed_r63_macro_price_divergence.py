"""Fed R6.3 macro-price divergence veto; synthetic fixtures NOT backtests."""
import pytest
from fx_scanner.fed_r63_macro_price_divergence import (
    evaluate_divergence, CONTRACT
)

NOW="2026-11-20T05:50:10+00:00"
QUOTE="2026-11-20T05:50:01+00:00"
CLOSE="2026-11-20T05:50:00+00:00"

def macro(direction="WAIT",daily_direction="BUY"):
    return {
        "contract":"RIZAN_XAU_R61_MARKET_DIRECTION_CONTEXT_V1",
        "direction":direction,"daily_direction":daily_direction,
        "validated_fed_r4":False,"entry_permission":False,
    }

def price(m15="SELL",h1="SELL",h4="UNKNOWN",**changed):
    d={
        "contract":"RIZAN_XAU_FED_R6_MANUAL_AREA_V1",
        "status":"WATCH","reason":"WATCH_ZONES_NO_AUTOMATIC_ENTRY",
        "as_of":NOW,"price":3530.0,
        "quote_at":QUOTE,"last_closed_m1":CLOSE,
        "bias_m15":m15,"bias_h1":h1,"bias_h4":h4,
        "entry_allowed":False,"authority_to_send_orders":False,
    }
    d.update(changed)
    return d

def test_current_daily_yields_bullish_but_bearish_price_does_not_buy():
    x=evaluate_divergence(macro(),price())
    assert x["contract"]==CONTRACT
    assert x["daily_yield_lean"]=="BUY"
    assert x["macro_context"]=="WAIT"
    assert x["price_structure"]=="SELL"
    assert x["state"]=="DAILY_MACRO_LEAN_VS_XAU_DIVERGENCE"
    assert x["divergence"] is True
    assert x["display_direction"]=="WAIT"
    assert x["watch_side"]=="SELL"
    assert x["entry_permission"] is False
    assert x["authority_to_send_orders"] is False

@pytest.mark.parametrize(("macro_side","price_side"),[("BUY","SELL"),("SELL","BUY")])
def test_explicit_macro_direction_against_completed_price_is_wait(macro_side,price_side):
    x=evaluate_divergence(macro(macro_side,macro_side),price(price_side,price_side))
    assert x["state"]=="MACRO_PRICE_DIVERGENCE"
    assert x["display_direction"]=="WAIT"
    assert x["divergence"] is True

@pytest.mark.parametrize("side",["BUY","SELL"])
def test_price_macro_confluence_is_watch_only_not_orders(side):
    x=evaluate_divergence(macro(side,side),price(side,side))
    assert x["state"]=="MACRO_AND_PRICE_ALIGNED_WATCH"
    assert x["display_direction"]==side
    assert x["validated_historical_performance"] is False
    assert x["entry_permission"] is False
    assert x["confidence_pct"] is None
    assert not x["point_in_time_paired_macro_price_data"]

def test_unknown_h4_does_not_falsely_block_complete_m15_h1_pair():
    x=evaluate_divergence(macro("SELL","SELL"),price("SELL","SELL","UNKNOWN"))
    assert x["display_direction"]=="SELL"

def test_opposing_h4_does_block_even_if_m15_h1_agree():
    x=evaluate_divergence(macro("SELL","SELL"),price("SELL","SELL","BUY"))
    assert x["state"]=="WAIT_H4_OPPOSES_M15_H1"
    assert x["display_direction"]=="WAIT"

def test_m15_h1_mixed_does_not_imply_trend_from_macro():
    x=evaluate_divergence(macro("BUY","BUY"),price("BUY","SELL"))
    assert x["state"]=="WAIT_XAU_STRUCTURE_MIXED"
    assert x["display_direction"]=="WAIT"

def test_no_macro_lean_but_price_bearish_is_technical_only_not_sell_order():
    x=evaluate_divergence(macro("WAIT","WAIT"),price("SELL","SELL"))
    assert x["state"]=="TECHNICAL_DIRECTION_ONLY_MACRO_WAIT"
    assert x["display_direction"]=="WAIT"
    assert x["watch_side"]=="SELL"

def test_bad_or_missing_price_source_contract_no_false_direction():
    x=evaluate_divergence(macro("BUY","BUY"),{"status":"WATCH","bias_h1":"BUY"})
    assert x["display_direction"]=="WAIT"
    assert x["state"].startswith("WAIT_UNVERIFIED")

@pytest.mark.parametrize("bad_quote",["2026-11-20T05:40:01+00:00",None])
def test_stale_or_absent_quote_never_confirms_price(bad_quote):
    x=evaluate_divergence(macro("SELL","SELL"),price(quote_at=bad_quote))
    assert x["display_direction"]=="WAIT"
    assert x["price_structure"]=="WAIT"

def test_wrong_reporting_privileges_block_even_matching_price():
    x=evaluate_divergence(macro("BUY","BUY"),price("BUY","BUY",entry_allowed=True))
    assert x["display_direction"]=="WAIT"
    assert x["reason"]=="PRICE_REPORT_PRIVILEGES_UNTRUSTED"

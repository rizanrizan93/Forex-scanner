"""R6.5 prospective four-hour search: synthetic input tests, NOT backtest."""
from datetime import datetime, timezone, timedelta
import pytest
from fx_scanner.fed_r65_four_hour_search import evaluate_four_hour_search, CONTRACT

NOW=datetime(2026,11,20,10,0,10,tzinfo=timezone.utc)


def macro(side="BUY", daily=None, **changes):
    d={
        "contract":"RIZAN_XAU_R61_MARKET_DIRECTION_CONTEXT_V1",
        "as_of_utc":NOW.isoformat(),"direction":side,
        "daily_direction":daily or side,
        "daily_yields":{
            "US2Y":{"valid_official_daily":True},
            "US10Y":{"valid_official_daily":True}},
        "dxy":{"fresh":True},
        "entry_permission":False,
    }
    d.update(changes)
    return d


def price(side="BUY", **changes):
    d={
        "contract":"RIZAN_XAU_FED_R6_MANUAL_AREA_V1",
        "status":"WATCH","as_of":NOW.isoformat(),
        "quote_at":(NOW-timedelta(seconds=4)).isoformat(),
        "last_closed_m1":(NOW-timedelta(seconds=10)).isoformat(),
        "price":3500.,"atr_m5":1.2,
        "bias_m15":side,"bias_h1":side,"bias_h4":side,
        "liquidity_context":{
            "contract":"RIZAN_R63_LIQUIDITY_STRESS_RESEARCH_READONLY_V1",
            "state":"NORMAL","risk_veto":False,"liquidation_confirmed":False},
        "liquidity_pools":{"levels":[]},
        "entry_allowed":False,"authority_to_send_orders":False,
    }
    d.update(changes)
    return d


@pytest.mark.parametrize("side, expected",[
    ("BUY","SEARCH_BUY"),("SELL","SEARCH_SELL")])
def test_bidirectional_four_hour_research_watch_is_not_order(side,expected):
    x=evaluate_four_hour_search(price(side),macro(side),now=NOW,news_events=[])
    assert x["contract"]==CONTRACT
    assert x["status"]=="RESEARCH_WATCH"
    assert x["search_side"]==expected
    assert x["horizon_hours"]==4
    assert x["evidence_score"]==5
    assert datetime.fromisoformat(x["target_at"])==NOW+timedelta(hours=4)
    assert x["win_probability_pct"] is None
    assert x["validated_four_hour_accuracy"] is False
    assert x["entry_permission"] is False
    assert x["cbot_influence"] is False
    assert x["frozen_v1_influence"] is False


def test_technical_direction_works_as_research_watch_without_dxy_confluence():
    x=evaluate_four_hour_search(
        price("SELL"),macro("WAIT",daily="WAIT",dxy={"fresh":False}),
        now=NOW,news_events=[])
    assert x["search_side"]=="SEARCH_SELL"
    assert x["macro_mode"]=="TECHNICAL_ONLY_UNVERIFIED"
    assert x["evidence_score"]==4
    assert x["status"]=="RESEARCH_WATCH"


@pytest.mark.parametrize("fields",[
    {"bias_m15":"SELL"},
    {"bias_h1":"SELL"},
    {"bias_h4":"SELL"},
    {"liquidity_context":None},
    {"quote_at":"2026-11-20T09:58:00+00:00"},
    {"price":None},
])
def test_structure_source_or_staleness_blocks_buy(fields):
    x=evaluate_four_hour_search(price("BUY",**fields),macro("BUY"),
                                now=NOW,news_events=[])
    assert x["search_side"]=="WAIT"
    assert x["status"]=="WAIT"


@pytest.mark.parametrize("liq_state",[
    "DOWNSIDE_DISPLACEMENT","UPSIDE_DISPLACEMENT",
    "SWEEP_LOW_RECLAIM","SWEEP_HIGH_REJECT",
    "VOLATILITY_SPIKE","WIDE_SPREAD",
    "POST_STRESS_COOLDOWN","UNKNOWN"])
def test_liquidity_dislocations_force_wait_both_sides(liq_state):
    p=price("SELL")
    p["liquidity_context"]={
        "contract":"RIZAN_R63_LIQUIDITY_STRESS_RESEARCH_READONLY_V1",
        "state":liq_state,"risk_veto":liq_state!="UNKNOWN",
        "liquidation_confirmed":False}
    x=evaluate_four_hour_search(p,macro("SELL"),now=NOW,news_events=[])
    assert x["search_side"]=="WAIT"
    assert x["watch_side"]=="SELL"


def test_macro_opposite_prevents_search_side_upgrade():
    x=evaluate_four_hour_search(price("SELL"),macro("BUY"),
                                now=NOW,news_events=[])
    assert x["state"]=="WAIT_MACRO_CONFLICT"
    assert x["search_side"]=="WAIT"


def test_daily_treasury_lean_opposite_prevents_unverified_technical_override():
    x=evaluate_four_hour_search(price("SELL"),macro("WAIT",daily="BUY"),
                                now=NOW,news_events=[])
    assert x["state"]=="WAIT_DAILY_YIELD_LEAN_CONFLICT"


def test_macro_buy_must_have_fresh_dxy_and_official_yields():
    x=evaluate_four_hour_search(price("BUY"),macro("BUY",dxy={"fresh":False}),
                                now=NOW,news_events=[])
    assert x["state"]=="MACRO_ALIGNMENT_UNVERIFIED"


@pytest.mark.parametrize("event_in_minutes", [1,15,239,-15])
def test_high_impact_news_inside_four_hour_window_forces_wait(event_in_minutes):
    e=[{"event":"FOMC","at":(NOW+timedelta(minutes=event_in_minutes)).isoformat()}]
    x=evaluate_four_hour_search(price("BUY"),macro("BUY"),now=NOW,news_events=e)
    assert x["state"]=="WAIT_NEWS_REPRICING_RISK"


def test_news_outside_horizon_not_labeled_inside():
    e=[{"event":"CPI","at":(NOW+timedelta(hours=5)).isoformat()}]
    x=evaluate_four_hour_search(price("BUY"),macro("BUY"),now=NOW,news_events=e)
    assert x["search_side"]=="SEARCH_BUY"


def test_missing_calendar_is_unverified_not_fake_no_event():
    x=evaluate_four_hour_search(price("BUY"),macro("BUY"),now=NOW,news_events=None)
    assert x["calendar_state"]=="UNVERIFIED"
    assert x["entry_permission"] is False


def test_near_previous_session_high_waits_instead_of_assuming_breakout():
    p=price("BUY",liquidity_pools={
        "levels":[{"name":"ASIA_SESSION_HIGH","price":3500.2}]})
    x=evaluate_four_hour_search(p,macro("BUY"),now=NOW,news_events=[])
    assert x["state"]=="WAIT_NEAR_PRIOR_LIQUIDITY_EXTREME"
    assert x["nearest_pool"]["distance_atr_m5"] < .3


def test_daily_source_contract_cannot_grant_order_authority():
    p=price("BUY",authority_to_send_orders=True)
    x=evaluate_four_hour_search(p,macro("BUY"),now=NOW,news_events=[])
    assert x["status"]=="WAIT"


def test_h4_unavailable_keeps_lower_evidence_score_but_no_fake_h4_vote():
    x=evaluate_four_hour_search(price("BUY",bias_h4="UNKNOWN"),
                                macro("BUY"),now=NOW,news_events=[])
    assert x["search_side"]=="SEARCH_BUY"
    assert x["evidence_score"]==4
    assert x["h4_state"]=="UNKNOWN"


def test_future_dated_xau_and_macro_sources_are_not_allowed():
    x=evaluate_four_hour_search(
        price("BUY",as_of=(NOW+timedelta(seconds=5)).isoformat()),
        macro("BUY"),now=NOW,news_events=[])
    assert x["state"]=="SOURCE_STALE_OR_FUTURE"

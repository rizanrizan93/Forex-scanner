"""Point-in-time R6.5 horizon outcomes: entirely synthetic testing."""
import pandas as pd
import pytest
from fx_scanner.fed_r65_four_hour_replay import paired_r65_four_hour_replay


def candles():
    idx=pd.date_range("2026-11-20T00:05:00Z",periods=155,freq="5min")
    return pd.DataFrame(
        {"open":3500.,"high":3500.7,"low":3499.3,"close":3500.},index=idx)


def snapshot(t,side="SELL",stress=False):
    s=t.isoformat()
    return {
        "decision_at":s,"price_received_at":s,"macro_received_at":s,
        "price_report":{
            "contract":"RIZAN_XAU_FED_R6_MANUAL_AREA_V1",
            "status":"WATCH","as_of":s,
            "quote_at":(t-pd.Timedelta(seconds=2)).isoformat(),
            "last_closed_m1":(t-pd.Timedelta(seconds=5)).isoformat(),
            "price":3500.,"atr_m5":1.4,"bias_m15":side,"bias_h1":side,
            "bias_h4":side,"entry_allowed":False,
            "authority_to_send_orders":False,
            "liquidity_context":{
                "contract":"RIZAN_R63_LIQUIDITY_STRESS_RESEARCH_READONLY_V1",
                "state":"DOWNSIDE_DISPLACEMENT" if stress else "NORMAL",
                "risk_veto":stress,"liquidation_confirmed":False},
            "liquidity_pools":{"levels":[]},
        },
        "macro_report":{
            "contract":"RIZAN_XAU_R61_MARKET_DIRECTION_CONTEXT_V1",
            "as_of_utc":s,"direction":side,"daily_direction":side,
            "daily_yields":{
                "US2Y":{"valid_official_daily":True},
                "US10Y":{"valid_official_daily":True}},
            "dxy":{"fresh":True},
            "entry_permission":False,
        },
        "news_events":[],
    }


def test_four_hour_audit_uses_exactly_48_m5_and_tracks_cohort_coverage():
    d=candles()
    a=paired_r65_four_hour_replay(
        d,[snapshot(d.index[40]),snapshot(d.index[103],stress=True)],
        spread_points=.2)
    assert a["contract"]=="RIZAN_R65_FOUR_HOUR_PAIRED_REPLAY_V1"
    assert a["horizon_m5_bars"]==48
    assert a["baseline_candidates_before_overlap"]==2
    assert a["candidate_baseline"]["n"]==2
    assert a["candidate_guarded"]["n"]+a["blocked"]["n"]==2
    assert a["historical_2019_2026_coverage_verified"] is False
    assert a["entry_permission"] is False
    assert a["spread_points_assumed"]==.2


def test_incomplete_asof_snapshots_do_not_produce_historical_accuracy():
    d=candles()
    a=paired_r65_four_hour_replay(d,[])
    assert a["status"]=="NO_ADMISSIBLE_PAIRED_4H_SIGNAL"
    assert a["four_hour_backtest_accuracy_pct"] is None


def test_future_received_macro_cannot_backfill_signal():
    d=candles()
    x=snapshot(d.index[50])
    x["macro_received_at"]=(d.index[50]+pd.Timedelta(seconds=5)).isoformat()
    with pytest.raises(ValueError,match="FUTURE_ARRIVING"):
        paired_r65_four_hour_replay(d,[x])


def test_future_report_publication_cannot_be_backfilled():
    d=candles()
    x=snapshot(d.index[50])
    x["price_received_at"]=(d.index[50]-pd.Timedelta(seconds=1)).isoformat()
    with pytest.raises(ValueError,match="RECEIVED_BEFORE_REPORT_EXISTED"):
        paired_r65_four_hour_replay(d,[x])


def test_explicit_news_in_four_hours_blocks_candidates_not_calls_it_wrong():
    d=candles()
    x=snapshot(d.index[50])
    x["news_events"]=[{
        "event":"CPI",
        "at":(d.index[50]+pd.Timedelta(hours=2)).isoformat(),
    }]
    a=paired_r65_four_hour_replay(d,[x])
    assert a["status"]=="NO_ADMISSIBLE_PAIRED_4H_SIGNAL"


def test_outcome_changes_do_not_change_decision_veto_or_signal_side():
    d=candles()
    x=snapshot(d.index[50])
    a=paired_r65_four_hour_replay(d,[x])
    d.loc[d.index[60],["open","high","low","close"]]=[3500,3570,3430,3500]
    b=paired_r65_four_hour_replay(d,[x])
    assert a["baseline_candidates_before_overlap"]==b["baseline_candidates_before_overlap"]==1
    assert a["events"][0]["guard_state"]==b["events"][0]["guard_state"]

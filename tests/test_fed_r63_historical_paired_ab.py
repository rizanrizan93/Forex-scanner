"""Unit tests are synthetic; NEVER evidence of 2019–26 trading accuracy."""
import pandas as pd
import pytest
from scripts.fed_r63_price_veto_ab import original_r63_price_veto
from scripts.aggregate_fed_r63_paired_ab_2019_2026 import aggregate,YEARS,EXPECTED_YEAR
from scripts.replay_fed_r5_paired_pilot import RULES


def trend_data(side):
    # All timestamps represent M1 OPEN. 12 days give >24 closed H4.
    idx=pd.date_range("2023-09-01T00:00:00Z",periods=12*24*60,freq="min",tz="UTC")
    values=pd.Series(range(len(idx)),index=idx,dtype="float64")
    if side=="BUY":
        closes=2000+values*.005
    else:
        closes=2000-values*.005
    d=pd.DataFrame({
        "open":closes-.001,
        "high":closes+.015,
        "low":closes-.015,
        "close":closes,
    },index=idx)
    return d


@pytest.mark.parametrize("price_side",["BUY","SELL"])
def test_fixed_r63_source_ema20_price_agreement_does_not_authorize_trade(price_side):
    d=trend_data(price_side)
    at=d.index[-1]+pd.Timedelta(minutes=1)
    r=original_r63_price_veto(d,at=at,historical_macro_side=price_side)
    assert r["pass_r63_price_veto"] is True
    assert r["state"]=="MACRO_AND_PRICE_ALIGNED_WATCH"
    assert r["price_trend"]["bias_m15"]==price_side
    assert r["price_trend"]["bias_h1"]==price_side
    assert r["price_trend"]["bias_h4"]==price_side
    assert r["genuine_point_in_time_macro_signal"] is False
    assert r["authority_to_send_orders"] is False


def test_declining_gold_blocks_macro_buy_exact_m15_h1():
    d=trend_data("SELL")
    at=d.index[-1]+pd.Timedelta(minutes=1)
    r=original_r63_price_veto(d,at=at,historical_macro_side="BUY")
    assert r["pass_r63_price_veto"] is False
    assert r["state"]=="MACRO_PRICE_DIVERGENCE"
    assert r["price_trend"]["bias_h1"]=="SELL"
    assert r["price_trend"]["bias_m15"]=="SELL"


def test_rising_gold_blocks_macro_sell():
    d=trend_data("BUY")
    at=d.index[-1]+pd.Timedelta(minutes=1)
    r=original_r63_price_veto(d,at=at,historical_macro_side="SELL")
    assert r["pass_r63_price_veto"] is False
    assert r["state"]=="MACRO_PRICE_DIVERGENCE"


def test_future_m1_cannot_be_supplied_as_past():
    d=trend_data("BUY")
    decision=d.index[-10]+pd.Timedelta(minutes=1)
    with pytest.raises(ValueError,match="ONLY_COMPLETE"):
        original_r63_price_veto(d,at=decision,historical_macro_side="BUY")


def test_no_interpolation_over_last_sixteen_m1_gaps():
    d=trend_data("BUY")
    d=d.drop(d.index[-8])
    with pytest.raises(ValueError,match="INTRADAY_M1_DATA_GAP"):
        original_r63_price_veto(d,at=d.index[-1]+pd.Timedelta(minutes=1),
                                historical_macro_side="BUY")


def _synthetic_year(year):
    events=[]
    for i in range(EXPECTED_YEAR[year]):
        eid=f"TEST_{year}_{i}"
        stats={
            rule:{"expost_macro_side":"WAIT",
                  "r6_risk_evaluable_n":0,
                  "first_observational_h1_right_n":0,
                  "r6_target3_first_n":0}
            for rule in RULES
        }
        events.append({
            "event_id":eid,"date":f"{year}-09-20",
            "rule_stats":stats,
            "r63_first_fixed_candidate_paired_ab":[],
        })
    return {
        "year":year,
        "official_events":EXPECTED_YEAR[year],
        "real_price_event_sources":EXPECTED_YEAR[year],
        "source_failures":[],
        "events":events,
    }


def _set_example(event, *, side, passed, right, target):
    rule=RULES[0]
    event["rule_stats"][rule].update({
        "expost_macro_side":side,
        "r6_risk_evaluable_n":1,
        "first_observational_h1_right_n":int(right),
        "r6_target3_first_n":int(target),
    })
    event["r63_first_fixed_candidate_paired_ab"]=[{
        "event_id":event["event_id"],
        "rule":rule,"side":side,
        "r63_pass":passed,
        "r63_state":"MACRO_AND_PRICE_ALIGNED_WATCH" if passed
                    else "MACRO_PRICE_DIVERGENCE",
        "risk_status":"EVALUATED",
        "h1_direction_correct":right,
        "target3_before_adverse3":target,
        "static_stop_before_target":not target,
        "macro_source":"USMPD_EXPOST_EVENT_WINDOW_NOT_POINT_IN_TIME",
        "authority_to_trade":False,
    }]


def test_paired_comparison_counts_rejected_losses_and_rejected_wins():
    years=[_synthetic_year(y) for y in YEARS]
    _set_example(years[0]["events"][0],side="BUY",passed=True,right=True,target=True)
    _set_example(years[0]["events"][1],side="BUY",passed=False,right=False,target=False)
    _set_example(years[0]["events"][2],side="BUY",passed=False,right=True,target=True)
    report=aggregate(years)
    buy=report["per_model_by_side"][RULES[0]]["BUY"]
    assert buy["original_h1_evaluable_n"]==3
    assert buy["original_h1_direction_right_n"]==2
    assert buy["r63_kept_h1_evaluable_n"]==1
    assert buy["r63_kept_h1_direction_right_n"]==1
    assert buy["r63_accuracy_point_difference"]==33.33
    assert buy["rejected_wrong_directions_n"]==1
    assert buy["rejected_correct_directions_n"]==1
    assert buy["rejected_target_first_n"]==1
    assert report["new_production_edge_validated"] is False
    assert report["authority_to_trade"] is False


def test_fails_if_reselect_later_winning_m1_after_first_blocked():
    years=[_synthetic_year(y) for y in YEARS]
    a=years[0]["events"][0]
    _set_example(a,side="BUY",passed=False,right=False,target=False)
    a["r63_first_fixed_candidate_paired_ab"].append({
        **a["r63_first_fixed_candidate_paired_ab"][0],
        "r63_pass":True,"h1_direction_correct":True,
    })
    with pytest.raises(ValueError,match="MULTIPLE_SIGNALS_PER_FOMC"):
        aggregate(years)


def test_original_r6_counts_must_be_identical_at_same_first_candidate():
    years=[_synthetic_year(y) for y in YEARS]
    a=years[0]["events"][0]
    _set_example(a,side="SELL",passed=True,right=True,target=True)
    a["rule_stats"][RULES[0]]["first_observational_h1_right_n"]=0
    with pytest.raises(ValueError,match="R63_BASELINE_MUST_MATCH_SEALED_R6"):
        aggregate(years)


def test_any_missing_official_price_source_fails_not_silent():
    years=[_synthetic_year(y) for y in YEARS]
    years[0]["real_price_event_sources"]=8
    with pytest.raises(ValueError,match="INCOMPLETE_SOURCE_COVERAGE"):
        aggregate(years)

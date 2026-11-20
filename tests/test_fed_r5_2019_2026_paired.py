"""R5 full 2019–2026 paired replay aggregation: integrity, no fake n."""
import pytest
from scripts.aggregate_fed_r5_paired_2019_2026 import aggregate,YEARS
from scripts.replay_fed_r5_paired_pilot import RULES
from scripts.replay_fed_r5_2019_2026_paired import year_replay

def mk_year(year):
    return {
        "year":year,"official_events":9 if year==2019 else
                 13 if year==2020 else 7 if year==2026 else 8,
        "source_failures":[],"events":[]
    }

def event(idx,year,side="BUY",correct=True):
    metrics={}
    for rule in RULES:
        metrics[rule]={
            "expost_macro_side":side,
            "first_observational_h1_evaluable_n":1,
            "first_observational_h1_right_n":int(correct),
            "raw_m1_continuation_observations":3,
            "correlated_m1_duplicates":2,
        }
    return {"event_id":f"{year}-{idx}","date":f"{year}-09-20","rule_stats":metrics}

def test_aggregate_counts_one_meeting_not_three_overlapping_m1_signals():
    years=[mk_year(y) for y in YEARS]
    for y in years:
        y["events"]=[event(i,y["year"],side="BUY" if i%2 else "SELL",
                           correct=True) for i in range(y["official_events"])]
    r=aggregate(years)
    assert r["source_real_m1_coverage_events"]==69
    x=r["per_rule_by_side"][RULES[0]]
    assert x["BUY"]["unique_fomc_technical_evaluable_n"]==sum(
        y["official_events"]//2 for y in years)
    assert x["SELL"]["unique_fomc_technical_evaluable_n"]==sum(
        (y["official_events"]+1)//2 for y in years)
    assert x["BUY"]["statistically_valid_80pct"] is False
    assert r["genuine_pit_macro_buy_n"]==0
    assert r["production_ready"] is False

def test_incomplete_eight_years_is_error():
    with pytest.raises(ValueError,match="MISSING_2019_2026"):
        aggregate([mk_year(2019)])

def test_multiple_signals_in_same_fomc_inflate_n_and_are_rejected():
    years=[mk_year(y) for y in YEARS]
    for y in years:
        y["events"]=[event(i,y["year"]) for i in range(y["official_events"])]
    years[0]["events"][0]["rule_stats"][RULES[0]]["first_observational_h1_evaluable_n"]=3
    with pytest.raises(ValueError,match="MULTIPLE_CONTINUATIONS"):
        aggregate(years)

def test_duplicate_event_ids_forced_error():
    years=[mk_year(y) for y in YEARS]
    for y in years:
        y["events"]=[event(i,y["year"]) for i in range(y["official_events"])]
    years[0]["events"][1]["event_id"]=years[0]["events"][0]["event_id"]
    with pytest.raises(ValueError,match="DUPLICATE_MEETING"):
        aggregate(years)

def test_outside_2019_2026_year_rejected():
    with pytest.raises(ValueError,match="YEAR_OUTSIDE"):
        year_replay(2027)

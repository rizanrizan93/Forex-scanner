"""R6.3 paired historical XAU price-veto accuracy comparison 2019–2026.

Primary test: select the FIRST original R6 continuation pattern per
FOMC meeting, post-event EX-POST macro rule, and side. Compare exact
same timestamp/horizon/outcome before vs after applying R6.3 confirmed
M15/H1 price trend veto. Do not search a replacement after rejection.

No at-time archived FOMC macro inputs, no real broker fills, and
2019–2026 research-exposed sample; NEVER production-validated alpha.
"""
from __future__ import annotations
from collections import Counter
from pathlib import Path
import argparse,json
from scripts.replay_fed_r5_paired_pilot import RULES
from scripts.replay_fed_macro_80pct_r3 import wilson95

YEARS=tuple(range(2019,2027))
TOTAL_FOMC=69
EXPECTED_YEAR={2019:9,2020:13,2021:8,2022:8,2023:8,
               2024:8,2025:8,2026:7}


def _rate(wins,n):
    return round(100*wins/n,2) if n else None


def aggregate(years):
    by_year={x["year"]:x for x in years}
    if sorted(by_year)!=list(YEARS) or len(years)!=len(YEARS):
        raise ValueError("MISSING_OR_DUPLICATE_2019_2026_YEAR_SHARDS")
    all_events=[]
    for year in YEARS:
        r=by_year[year]
        if r.get("official_events")!=EXPECTED_YEAR[year]:
            raise ValueError("OFFICIAL_YEAR_FOMC_COUNT_MISMATCH")
        if r.get("real_price_event_sources")!=EXPECTED_YEAR[year] or r.get("source_failures"):
            raise ValueError("INCOMPLETE_SOURCE_COVERAGE_OR_FAILURE")
        if len(r.get("events",[]))!=EXPECTED_YEAR[year]:
            raise ValueError("MISSING_FOMC_EVENT_SUMMARIES")
        all_events.extend(r["events"])
    if len(all_events)!=TOTAL_FOMC or len({x["event_id"] for x in all_events})!=TOTAL_FOMC:
        raise ValueError("NOT_69_DISTINCT_FOMC_MEETINGS")
    study={}
    total_records=0
    for model in RULES:
        by_side={}
        for side in ("BUY","SELL"):
            selected=[]
            for event in all_events:
                matching=[x for x in event.get("r63_first_fixed_candidate_paired_ab",[])
                          if x["rule"]==model and x["side"]==side]
                if len(matching)>1:
                    raise ValueError("MULTIPLE_SIGNALS_PER_FOMC_RULE_SIDE")
                if matching:
                    o=matching[0]
                    if o["event_id"]!=event["event_id"]:
                        raise ValueError("RECORD_FOMC_ID_MISMATCH")
                    if o.get("macro_source")!="USMPD_EXPOST_EVENT_WINDOW_NOT_POINT_IN_TIME":
                        raise ValueError("FAKE_POINT_IN_TIME_MACRO_SOURCE")
                    if o.get("authority_to_trade") is not False:
                        raise ValueError("TRADING_AUTHORITY_SHOULD_BE_FALSE")
                    if o.get("r63_pass") not in (True,False):
                        raise ValueError("R63_GATE_NOT_BOOLEAN")
                    selected.append((event,o))
            total_records+=len(selected)
            evaluated=[(e,x) for e,x in selected if x.get("risk_status")=="EVALUATED"]
            kept=[(e,x) for e,x in evaluated if x["r63_pass"]]
            blocked=[(e,x) for e,x in evaluated if not x["r63_pass"]]
            if len(evaluated)!=len(kept)+len(blocked):
                raise ValueError("PAIRED_POPULATION_NOT_CONSERVED")
            orig_n=len(evaluated)
            orig_wins=sum(x["h1_direction_correct"] is True for _,x in evaluated)
            orig_target=sum(x["target3_before_adverse3"] is True for _,x in evaluated)
            kept_n=len(kept)
            kept_wins=sum(x["h1_direction_correct"] is True for _,x in kept)
            kept_target=sum(x["target3_before_adverse3"] is True for _,x in kept)
            blocked_n=len(blocked)
            blocked_wrong=sum(x["h1_direction_correct"] is False for _,x in blocked)
            blocked_right=sum(x["h1_direction_correct"] is True for _,x in blocked)
            blocked_target=sum(x["target3_before_adverse3"] is True for _,x in blocked)
            # Pair original R6 year unit counts, not a new selected
            # denominator. Fail if the R63 risk layer silently changed
            # signal timing or labels relative to the sealed prior R6.
            r6_n=sum(e["rule_stats"][model]["r6_risk_evaluable_n"]
                     for e in all_events if e["rule_stats"][model]["expost_macro_side"]==side)
            r6_wins=sum(e["rule_stats"][model]["first_observational_h1_right_n"]
                        for e in all_events if e["rule_stats"][model]["expost_macro_side"]==side)
            r6_target=sum(e["rule_stats"][model]["r6_target3_first_n"]
                          for e in all_events if e["rule_stats"][model]["expost_macro_side"]==side)
            if (r6_n,r6_wins,r6_target)!=(orig_n,orig_wins,orig_target):
                raise ValueError("R63_BASELINE_MUST_MATCH_SEALED_R6_2019_2026")
            blocked_by_state=dict(Counter(x["r63_state"] for _,x in blocked))
            pass_years={}
            for year in YEARS:
                a=[x for e,x in evaluated if e["date"].startswith(str(year))]
                b=[x for e,x in kept if e["date"].startswith(str(year))]
                pass_years[str(year)]={
                    "original_n":len(a),
                    "original_direction_right":sum(x["h1_direction_correct"] is True for x in a),
                    "kept_n":len(b),
                    "kept_direction_right":sum(x["h1_direction_correct"] is True for x in b),
                }
            gain=(round(_rate(kept_wins,kept_n)-_rate(orig_wins,orig_n),2)
                  if kept_n and orig_n else None)
            by_side[side]={
                "original_first_candidate_meetings_n":len(selected),
                "original_h1_evaluable_n":orig_n,
                "original_h1_direction_right_n":orig_wins,
                "original_h1_direction_accuracy_pct":_rate(orig_wins,orig_n),
                "original_h1_target3_first_n":orig_target,
                "original_h1_target3_first_pct":_rate(orig_target,orig_n),
                "r63_kept_h1_evaluable_n":kept_n,
                "r63_kept_h1_direction_right_n":kept_wins,
                "r63_kept_h1_direction_accuracy_pct":_rate(kept_wins,kept_n),
                "r63_kept_h1_target3_first_n":kept_target,
                "r63_kept_h1_target3_first_pct":_rate(kept_target,kept_n),
                "r63_accuracy_point_difference":gain,
                "r63_kept_direction_wilson95_pct":wilson95(kept_wins,kept_n),
                "r63_kept_target_first_wilson95_pct":wilson95(kept_target,kept_n),
                "coverage_after_gate_pct":_rate(kept_n,orig_n),
                "original_evaluable_rejected_n":blocked_n,
                "rejected_wrong_directions_n":blocked_wrong,
                "rejected_correct_directions_n":blocked_right,
                "rejected_target_first_n":blocked_target,
                "rejected_by_r63_state":blocked_by_state,
                "censored_original_first_signals_n":len(selected)-orig_n,
                "by_year":pass_years,
                "genuine_historical_macro_pit_n":0,
                "verified_80pct_both_sides":False,
                "authority_to_trade":False,
            }
        study[model]=by_side
    return {
        "contract":"RIZAN_R63_2019_2026_FIRST_SIGNAL_PAIRED_ACCURACY_AB",
        "official_fomc_event_count":TOTAL_FOMC,
        "price_sources_complete_69_of_69":True,
        "price_sources_failed":0,
        "distinct_meetings":TOTAL_FOMC,
        "historical_expost_first_pattern_records_across_overlapping_models":total_records,
        "model_counts_overlap_same_fomc_meetings":True,
        "same_signal_time_same_cost_same_outcome":True,
        "predeclared_veto":"PRODUCTION_R63_EMA20_M15_H1_H4_ASOF",
        "no_later_reentry_when_first_candidate_blocked":True,
        "per_model_by_side":study,
        "historical_macro_source":"OFFICIAL_USMPD_RETROSPECTIVE_NOT_TIMESTAMPED_LIVE_OIS_TIPS_DXY",
        "actual_broker_bids_asks_available":False,
        "synthetic_roundtrip_cost_usd_oz":0.5,
        "retrospective_in_sample_not_prospective":True,
        "new_production_edge_validated":False,
        "claimed_historical_live_accuracy":False,
        "authority_to_trade":False,
    }


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--input-dir",type=Path,required=True)
    p.add_argument("--out",type=Path,required=True)
    a=p.parse_args()
    results=[]
    for year in YEARS:
        paths=list(a.input_dir.rglob(f"fed_r63_paired_{year}.json"))
        if len(paths)!=1:
            raise ValueError(f"YEAR_SHARD_MISSING_OR_DUPLICATE_{year}")
        results.append(json.loads(paths[0].read_text()))
    final=aggregate(results)
    a.out.parent.mkdir(parents=True,exist_ok=True)
    a.out.write_text(json.dumps(final,indent=2,allow_nan=False)+"\n")
    print("FED_R63_PAIRED_2019_2026_AGGREGATE",json.dumps({
        k:v for k,v in final.items() if k!="per_model_by_side"},
        allow_nan=False))
    print("FED_R63_PAIRED_BY_SIDE",json.dumps(final["per_model_by_side"],allow_nan=False))
if __name__=="__main__":
    main()

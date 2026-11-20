"""Research-only 2019–2026 FOMC→V4 real XAU M1 paired-entry screening.

Each FOMC meeting is ONE independent unit, even if multiple M1
continuation patterns fire. Only FIRST qualified observational trigger
per rule/side/event is scored with complete future H1; no cherry-picking.

CRITICAL: official USMPD macro changes are ex-post market observations
and cannot be represented as PIT emitted BUY or SELL trading signals.
All historical price execution uses an assumed synthetic $0.50 spread.
No automatic LIVE, order, bridge, or production actions.
"""
from __future__ import annotations
from collections import Counter
from datetime import date,timedelta
from pathlib import Path
import argparse,hashlib,json
from scripts.replay_fed_macro_2019_2026_r1 import (
    event_plan,load_real_xau
)
from scripts.replay_fed_macro_event_pilot_r1 import (
    fetch_official,PINNED_SOURCE_SHA
)
from scripts.replay_fed_information_shock_r4 import source_join
from scripts.replay_fed_r5_paired_pilot import replay,RULES

EXPECTED={2019:9,2020:13,2021:8,2022:8,2023:8,
          2024:8,2025:8,2026:7}
PRE_DAYS=20
POST_DAYS=7

def year_replay(year,*,fetcher=load_real_xau,official=None):
    if year not in EXPECTED:raise ValueError("YEAR_OUTSIDE_2019_2026")
    raw=official if official is not None else fetch_official()
    if hashlib.sha256(raw).hexdigest()!=PINNED_SOURCE_SHA:
        raise ValueError("OFFICIAL_USMPD_SHA_MISMATCH")
    events=event_plan(raw,year)
    if len(events)!=EXPECTED[year]:
        raise ValueError(f"FOMC_YEAR_EVENT_COUNT_CHANGED_{year}_{len(events)}")
    events,issues=source_join(events,raw)
    if issues:
        raise ValueError("FOMC_OFFICIAL_CLOCK_JOIN_FAILED: "+json.dumps(issues)[:500])
    summaries=[];failures=[];provenance=[]
    for e in events:
        if e.get("invalid_event"):
            failures.append({"event_id":e["event_id"],"reason":"INVALID_OFFICIAL_FOMC_EVENT"})
            continue
        day=date.fromisoformat(e["date"])
        start=day-timedelta(days=PRE_DAYS)
        end=day+timedelta(days=POST_DAYS)
        try:
            data,source=fetcher(start,end)
            if (source.get("source")!="HISTDATA_XAUUSD_M1_SECONDARY_MARKET"
                or source.get("failed_periods")
                or not source.get("utc_normalized_m1_sha256")):
                raise ValueError("REPLAY_SOURCE_TIER_OR_SHA_MISMATCH")
            manifest={
                "source":"HISTDATA_XAUUSD_M1",
                "failed_periods":source["failed_periods"],
                "sha256_csv":source["utc_normalized_m1_sha256"],
            }
            result=replay(data,manifest=manifest,event=e,
                          expost_source_sha=PINNED_SOURCE_SHA)
            provenance.append({
                "event_id":e["event_id"],"year":year,
                "history_start":start.isoformat(),"history_end":end.isoformat(),
                **source})
            counters=result["counters"]
            observations=result["observations"]
            rule_stats={}
            for rule in RULES:
                col="continuation_"+rule+"_"
                rule_stats[rule]={
                    "expost_macro_side":result["macro_oracle_directions"][rule],
                    "macro_selected":result["macro_oracle_directions"][rule] in ("BUY","SELL"),
                    "first_observational_h1_evaluable_n":counters.get(col+"h1_evaluable",0),
                    "first_observational_h1_right_n":counters.get(col+"h1_direction_right",0),
                    "raw_m1_continuation_observations":counters.get(col+"same_side_raw",0),
                    "correlated_m1_duplicates":counters.get(col+"deduplicated_overlap",0),
                    "h1_censored":counters.get(col+"h1_censored",0),
                    "r6_risk_evaluable_n":counters.get(
                        "r6_continuation_"+rule+"_h1_risk_evaluable_n",0),
                    "r6_target3_first_n":counters.get(
                        "r6_continuation_"+rule+"_h1_target3_before_adverse3_n",0),
                    "r6_adverse3_first_n":counters.get(
                        "r6_continuation_"+rule+"_h1_adverse3_first_n",0),
                    "r6_neither_barrier_n":counters.get(
                        "r6_continuation_"+rule+"_h1_neither_barrier_n",0),
                    "r6_static_stop_before_target_n":counters.get(
                        "r6_continuation_"+rule+"_h1_static_stop_before_target3_n",0),
                    "r6_total_mae_usd_oz":counters.get(
                        "r6_continuation_"+rule+"_h1_total_mae_usd_oz",0.0),
                    "r6_total_mfe_usd_oz":counters.get(
                        "r6_continuation_"+rule+"_h1_total_mfe_usd_oz",0.0),
                    "r6_pivot_first_unique_signal_n":counters.get(
                        "r6_pivot_"+rule+"_first_unique_signal_n",0),
                    "r6_pivot_risk_evaluable_n":counters.get(
                        "r6_pivot_"+rule+"_risk_evaluable_n",0),
                    "r6_pivot_h1_right_n":counters.get(
                        "r6_pivot_"+rule+"_h1_right_n",0),
                    "r6_pivot_stop_before_target_n":counters.get(
                        "r6_pivot_"+rule+"_stop_before_target_n",0),
                    "v4_directional_entry_h1_evaluable_n":sum(x["rule"]==rule for x in observations),
                    "v4_directional_entry_h1_right_n":sum(
                        x["rule"]==rule and
                        x["h1_terminal_direction_correct_after_0p50_cost"]
                        for x in observations),
                }
            summaries.append({
                "event_id":e["event_id"],
                "date":e["date"],
                "window":e["window"],
                "window_end":e["window_end_utc"],
                "source_sha":source["utc_normalized_m1_sha256"],
                "screened_m1":counters.get("screened_m1_closes",0),
                "technical_data_unavailable":counters.get("technical_data_or_htf_unavailable",0),
                "v4_original_buy_candidate_m1":counters.get("v4_BUY_ENTRY_CANDIDATE",0),
                "v4_original_sell_candidate_m1":counters.get("v4_SELL_ENTRY_CANDIDATE",0),
                "rule_stats":rule_stats,
                "r6_unfiltered_first_continuation_by_side":{
                    side:{
                        "first_event_n":counters.get(
                            "r6_unfiltered_"+side+"_first_event_n",0),
                        "h1_evaluable_n":counters.get(
                            "r6_unfiltered_"+side+"_h1_evaluable_n",0),
                        "h1_correct_n":counters.get(
                            "r6_unfiltered_"+side+"_h1_correct_n",0),
                        "target_first_n":counters.get(
                            "r6_unfiltered_"+side+"_h1_target_first_n",0),
                        "stop_first_n":counters.get(
                            "r6_unfiltered_"+side+"_h1_stop_first_n",0),
                    } for side in ("BUY","SELL")},
                "r6_pivot_ablation_by_side":{
                    side:{
                        "pattern_n":counters.get(
                            "r6_pivot_"+side+"_pattern_n",0),
                        "other_gates_ok_n":counters.get(
                            "r6_pivot_"+side+"_other_gates_ok_n",0),
                        "hypothetical_n":counters.get(
                            "r6_pivot_"+side+"_hypothetical_n",0),
                        "old_room_only_recovered_n":counters.get(
                            "r6_pivot_"+side+"_old_room_only_recovered_n",0),
                        "old_candidate_blocked_n":counters.get(
                            "r6_pivot_"+side+"_old_candidate_blocked_n",0),
                    } for side in ("BUY","SELL")},
                "retro_macro_not_pit":True,
            })
        except Exception as ex:
            failures.append({"event_id":e["event_id"],"date":e["date"],
                             "reason":type(ex).__name__+":"+str(ex)[:260]})
    if not summaries:
        raise ValueError("ALL_XAU_FOMC_SOURCES_FAILED")
    per_rule={}
    for rule in RULES:
        chosen=[r["rule_stats"][rule] for r in summaries]
        keys=("first_observational_h1_evaluable_n","first_observational_h1_right_n",
              "raw_m1_continuation_observations","correlated_m1_duplicates",
              "h1_censored","v4_directional_entry_h1_evaluable_n",
              "v4_directional_entry_h1_right_n",
              "r6_risk_evaluable_n","r6_target3_first_n",
              "r6_adverse3_first_n","r6_neither_barrier_n",
              "r6_static_stop_before_target_n",
              "r6_total_mae_usd_oz","r6_total_mfe_usd_oz",
              "r6_pivot_first_unique_signal_n",
              "r6_pivot_risk_evaluable_n",
              "r6_pivot_h1_right_n",
              "r6_pivot_stop_before_target_n")
        per_rule[rule]={
            "macro_buy_meetings":sum(r["expost_macro_side"]=="BUY" for r in chosen),
            "macro_sell_meetings":sum(r["expost_macro_side"]=="SELL" for r in chosen),
            "macro_wait_meetings":sum(r["expost_macro_side"] not in ("BUY","SELL") for r in chosen),
            "by_side":{
                side:{k:sum(r[k] for r in chosen if r["expost_macro_side"]==side)
                      for k in keys}
                for side in ("BUY","SELL")
            },
            **{k:sum(r[k] for r in chosen) for k in keys},
        }
    return {
        "contract":"FED_R5_2019_2026_FOMC_TECHNICAL_PAIRED_REPLAY_EXPOST",
        "year":year,"official_events":len(events),
        "real_price_event_sources":len(summaries),
        "source_failures":failures,
        "official_data_sha":PINNED_SOURCE_SHA,
        "window":"FIRST_90_CLOCK_MINUTES_AFTER_COMPLETED_FOMC_COMMUNICATION",
        "entry_cost_assumption_usd_oz":0.50,
        "per_rule_summary":per_rule,
        "r6_unfiltered_baseline_by_side":{
            side:{
                k:sum(e["r6_unfiltered_first_continuation_by_side"][side][k]
                      for e in summaries)
                for k in ("first_event_n","h1_evaluable_n",
                          "h1_correct_n","target_first_n","stop_first_n")}
            for side in ("BUY","SELL")},
        "r6_pivot_ablation_by_side":{
            side:{
                k:sum(e["r6_pivot_ablation_by_side"][side][k]
                      for e in summaries)
                for k in ("pattern_n","other_gates_ok_n","hypothetical_n",
                          "old_room_only_recovered_n","old_candidate_blocked_n")}
            for side in ("BUY","SELL")},
        "events":summaries,
        "price_sources":provenance,
        "original_v4_entry_candidates_m1":sum(
            x["v4_original_buy_candidate_m1"]+
            x["v4_original_sell_candidate_m1"] for x in summaries),
        "genuine_timestamped_macro_buy_n":0,
        "genuine_timestamped_macro_sell_n":0,
        "production_ready":False,
        "authority_to_trade":False,
        "notes":[
            "One earliest M1 continuation observation per event/rule/side; do not pool repeated M1 matches as independent",
            "Official Fed market impact fields compiled ex post; NOT genuine at-time captured live quote sources",
            "M1 prices are real secondary-market historical sources, broker spread assumed synthetic",
            "Year-sharded 2019-2026 prices are not untouched holdout",
            "Full price replay quality measured by source failures and label censoring; report separately",
        ],
    }

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--year",type=int,required=True)
    ap.add_argument("--out",type=Path,required=True)
    a=ap.parse_args()
    report=year_replay(a.year)
    a.out.parent.mkdir(parents=True,exist_ok=True)
    a.out.write_text(json.dumps(report,indent=2,allow_nan=False)+"\n")
    print("FED_R5_YEAR_PAIRED_REPLAY",json.dumps({
        k:v for k,v in report.items() if k not in ("events","price_sources")},allow_nan=False))
if __name__=="__main__":main()

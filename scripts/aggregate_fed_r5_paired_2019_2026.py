"""Combine 8 year-sharded R5 paired post-FOMC entry studies.

Important: one FOMC meeting (not M1 bars, not model variants) is the
independent unit. Source is official USMPD ex-post; no LIVE availability.
No claim of 80% both sides based on tiny or repeatedly inspected data.
"""
from __future__ import annotations
from collections import Counter
from pathlib import Path
import argparse,json
from scripts.replay_fed_r5_paired_pilot import RULES
from scripts.replay_fed_macro_80pct_r3 import wilson95

YEARS=tuple(range(2019,2027))
EXPECTED=69

def aggregate(years):
    ys={r["year"]:r for r in years}
    if sorted(ys)!=list(YEARS):
        raise ValueError("MISSING_2019_2026_SHARDS")
    events=[e for yr in YEARS for e in ys[yr]["events"]]
    if sum(ys[y]["official_events"] for y in YEARS)!=EXPECTED:
        raise ValueError("FOMC_TOTAL_CHANGED")
    if len({e["event_id"] for e in events})!=len(events):
        raise ValueError("DUPLICATE_MEETING_IDS")
    output={}
    for rule in RULES:
        model={}
        for side in ("BUY","SELL"):
            selected=[e for e in events if e["rule_stats"][rule]["expost_macro_side"]==side]
            good=[e for e in selected
                  if e["rule_stats"][rule]["first_observational_h1_evaluable_n"]==1]
            if any(e["rule_stats"][rule]["first_observational_h1_evaluable_n"]>1 for e in selected):
                raise ValueError("MULTIPLE_CONTINUATIONS_PER_FOMC_ILLEGAL")
            wins=sum(e["rule_stats"][rule]["first_observational_h1_right_n"] for e in good)
            n=len(good)
            by_year={str(year):{"n":sum(e["date"].startswith(str(year)) for e in good),
                                "wins":sum(e["date"].startswith(str(year)) and
                                    e["rule_stats"][rule]["first_observational_h1_right_n"]==1
                                    for e in good)} for year in YEARS}
            model[side]={
                "macro_selected_events":len(selected),
                "unique_fomc_technical_evaluable_n":n,
                "unique_fomc_h1_direction_correct_n":wins,
                "h1_direction_accuracy_pct":round(100*wins/n,2) if n else None,
                "wilson95_pct":wilson95(wins,n),
                "technical_missing_or_censored_fomc_n":len(selected)-n,
                "by_year":by_year,
                "expost_wilson_lower_ge80_n30_descriptive":bool(n>=30 and
                     wilson95(wins,n) and wilson95(wins,n)[0]>=80),
                "statistically_valid_80pct":False,
                "reason_not_validated":"RETROSPECTIVE_DATA_AND_NO_PROSPECTIVE_POINT_IN_TIME_FEED",
                "genuine_pit_n":0,
                "execution_authority":False,
            }
        output[rule]=model
    total_raw=Counter()
    for e in events:
        total_raw.update({
            "BUY":e["rule_stats"][RULES[0]]["raw_m1_continuation_observations"]
            if e["rule_stats"][RULES[0]]["expost_macro_side"]=="BUY" else 0,
            "SELL":e["rule_stats"][RULES[0]]["raw_m1_continuation_observations"]
            if e["rule_stats"][RULES[0]]["expost_macro_side"]=="SELL" else 0,
        })
    return {
        "contract":"FED_R5_PAIRED_XAU_V4_CONTINUATION_2019_2026_AGGREGATE",
        "years":list(YEARS),
        "official_fomc_expected":EXPECTED,
        "source_real_m1_coverage_events":len(events),
        "source_failures":sum((ys[y]["source_failures"] for y in YEARS),[]),
        "per_rule_by_side":output,
        "all_69_events_covered":len(events)==EXPECTED,
        "genuine_pit_macro_buy_n":0,"genuine_pit_macro_sell_n":0,
        "production_ready":False,
        "execution_authority":False,
        "limitations":[
          "USMPD macro shock data are retrospective post-event study, not a captured live Fed signal",
          "Macro input direction applied only after verified completed official event-window end",
          "Past 2019-2026 repeatedly analyzed; do not claim an untouched holdout",
          "At most one first qualifying continuation observation per FOMC meeting, side and model",
          "A technical candidate is not a broker execution; historical spread synthetic $0.50",
          "Low sample Wilson interval and genuinely available future events needed before predictive claims",
          "No actual intraday OIS/TIPS feed is connected to production",
        ],
    }

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--input-dir",type=Path,required=True)
    ap.add_argument("--out",type=Path,required=True)
    a=ap.parse_args()
    shards=[]
    for year in YEARS:
        files=list(a.input_dir.rglob(f"fed_r5_paired_{year}.json"))
        if len(files)!=1:raise ValueError(f"MISSING_OR_DUPLICATE_YEAR_{year}")
        shards.append(json.loads(files[0].read_text()))
    result=aggregate(shards)
    a.out.parent.mkdir(parents=True,exist_ok=True)
    a.out.write_text(json.dumps(result,indent=2,allow_nan=False)+"\n")
    print("FED_R5_MULTIYEAR_PAIRED_AGGREGATE",json.dumps({
        k:v for k,v in result.items() if k!="source_failures" or len(v)<5
    },allow_nan=False))
if __name__=="__main__":main()

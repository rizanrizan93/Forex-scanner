"""Aggregate year-sharded 2019-2026 XAU vs official ex-post Fed repricing.

DO NOT POOL correlated statement/PC/full windows. Each calendar-day FOMC
meeting counted once. Exclude overlaps with NEXT FOMC meeting from the
nonoverlapping horizon cohort; report counts both with and without.
Zero genuine as-of trade signals (USMPD is retrospectively published).
"""
from __future__ import annotations
from collections import Counter
from pathlib import Path
import argparse, json,statistics
import pandas as pd
from scripts.replay_rejection_v2_outcomes import wilson

METHODS=("MP2_ONLY","THREE_MARKET_CONSENSUS")
HORIZONS=("H4","D1","D3","D5","D10")
SIDES=("BUY","SELL")

def macro_side(e,method):
    return e["oracle_policy_only" if method=="MP2_ONLY" else "oracle_consensus"]["side"]

def summarize(records,method,horizon,side,*,unconditional=False,exclude_overlapping=False):
    evaluated=[];selected=0;censored=0;overlapped=0
    for i,e in enumerate(records):
        if "scores" not in e or (not unconditional and macro_side(e,method)!=side):
            continue
        selected+=1
        result=e["scores"][side]["outcomes"][horizon]
        if result["status"]!="EVALUATED":
            censored+=1;continue
        ending=pd.Timestamp(result["end_at_utc"])
        if exclude_overlapping:
            next_event=next((q for q in records[i+1:]
                            if q.get("release_at_utc") and
                            pd.Timestamp(q["release_at_utc"])<ending),None)
            if next_event is not None:
                overlapped+=1;continue
        evaluated.append(result)
    n=len(evaluated);wins=sum(bool(x["direction_correct"]) for x in evaluated)
    pct=round(100*wins/n,2) if n else None
    returns=[x["signed_net_return_pct"] for x in evaluated]
    return {
        "selected":selected,"evaluable_n":n,"correct_n":wins,
        "direction_accuracy_pct":pct,"wilson95_pct":wilson(wins,n),
        "median_signed_return_pct":round(statistics.median(returns),5)
            if returns else None,
        "mean_signed_return_pct":round(statistics.mean(returns),5)
            if returns else None,
        "censored_n":censored,"excluded_next_fomc_overlap_n":overlapped,
        "pit_valid_n":0,"trading_edge_proven":False}

def aggregate(reports):
    if sorted({r["year"] for r in reports})!=list(range(2019,2027)):
        raise ValueError("MISSING_YEAR_SHARD_2019_2026")
    for r in reports:
        if r.get("production_ready") is not False or r.get("genuine_pit_backtest") is not False:
            raise ValueError("UNTRUSTED_ASOF_OR_PRODUCTION_FLAG")
    recs=sorted((e for r in reports for e in r["events"]),
                key=lambda e:(e.get("release_at_utc") or e["date"],e["event_id"]))
    if len({e["event_id"] for e in recs})!=len(recs):
        raise ValueError("DUPLICATE_FOMC_EVENT_ID")
    results={}
    for method in METHODS:
        results[method]={}
        for h in HORIZONS:
            results[method][h]={}
            for side in SIDES:
                results[method][h][side]={
                    "all_meetings_as_observed":summarize(recs,method,h,side),
                    "nonoverlapping_no_next_fomc":summarize(
                        recs,method,h,side,exclude_overlapping=True)}
    baseline={h:{side:summarize(recs,"",h,side,unconditional=True)
                 for side in SIDES} for h in HORIZONS}
    years={str(r["year"]):{
        "official_events":r["statement_events_expected"],
        "real_price_data_loaded":r["real_price_sources_loaded"],
        "source_failures":r["source_failures"],
        "stats":r["stats"],
    } for r in reports}
    return {
        "contract":"FED_MACRO_2019_2026_YEAR_AGGREGATE_RESEARCH_V1",
        "years_expected":list(range(2019,2027)),
        "official_event_rows":len(recs),
        "price_event_sources_loaded":sum(r["real_price_sources_loaded"] for r in reports),
        "independent_real_price_event_dates":len({
            e["date"] for e in recs if "scores" in e}),
        "by_year":years,
        "macro_methods":results,
        "matched_event_unconditional_baseline":baseline,
        "asof_eligible_buy_n":0,
        "asof_eligible_sell_n":0,
        "production_ready":False,
        "no_trade_execution":True,
        "oracle_not_pit":True,
        "methodology":[
            "MP2 surprise is next-meeting implied policy rate shift; not a complete expected Fed cycle",
            "USMPD is updated retrospectively; its historical event window labels were not archived in real-time",
            "D1/D3/D5/D10 are full subsequent UTC weekday sessions; H4 needs 240 continuous M1",
            "8 separate years were already research-exposed, NOT untouched out-of-sample",
            "Both all-event and next-FOMC-overlap-excluded results shown; do not sum correlated horizons",
            "Gold trends can be affected by other news/real yields/geopolitics over weekly horizons",
            "Missing historical source and censored horizons reduce n; no imputation",
            "Assumed fixed round-trip cost 0.50 USD/oz, excludes actual broker fees, carry, slippage",
            "No release or merger into ForexScanner production or LIVE cBot",
        ],
    }

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--input-dir",type=Path,required=True)
    ap.add_argument("--out",type=Path,required=True)
    args=ap.parse_args()
    reports=[]
    for year in range(2019,2027):
        files=list(args.input_dir.rglob(f"fed_macro_{year}.json"))
        if len(files)!=1:
            raise ValueError(f"MISSING_OR_DUPLICATE_{year}_SHARD_{len(files)}")
        reports.append(json.loads(files[0].read_text()))
    result=aggregate(reports)
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(result,indent=2,allow_nan=False)+"\n")
    abridged={
        "official_event_rows":result["official_event_rows"],
        "price_event_sources_loaded":result["price_event_sources_loaded"],
        "year_counts":{y:{"expected":r["official_events"],
                          "price":r["real_price_data_loaded"],
                          "failures":len(r["source_failures"])}
                       for y,r in result["by_year"].items()},
        "macro_methods":result["macro_methods"],
        "matched_event_unconditional_baseline":result["matched_event_unconditional_baseline"],
        "asof_eligible_buy_n":0,"asof_eligible_sell_n":0,
        "production_ready":False}
    print("FED_MACRO_8YEAR_AGGREGATE",json.dumps(abridged,allow_nan=False))
if __name__=="__main__":main()

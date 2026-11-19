"""R3 FOMC repricing vs US2Y/US10Y/DXY multihorizon falsification.

RESEARCH ONLY. Eight-year R1 event ledger (official SF Fed USMPD market
responses joined to genuine historical XAU M1 outcomes). All USMPD changes
are EX-POST event-study measurements, NOT archived live market snapshots.
This script cannot promote a BUY/SELL signal or deploy production.

IMPORTANT: Explicit symmetric hypotheses registered before looking at R3
results, no grid-search optimization, no MAX() over best years/sides.
Historical 2019-2026 has already been examined; *no genuine holdout*.
"""
from __future__ import annotations
from collections import Counter
from datetime import datetime
from math import isfinite, sqrt
from pathlib import Path
from statistics import median, mean
import argparse, json

EXPECTED_YEARS=tuple(range(2019,2027))
SOURCE_SHA="2b91297c42cf692dd74f65eabf7ee97f81d452676e23fa02edb222bfa60f0d0a"
HORIZONS=("D1","D3","D5","D10")
SIDES=("BUY","SELL")
FOLDS={
    "exploratory_2019_2022":(2019,2020,2021,2022),
    "research_touched_2023_2024":(2023,2024),
    "research_touched_2025_2026":(2025,2026),
    "all_2019_2026":EXPECTED_YEARS,
}
# Predeclared, directionally symmetric hypotheses; thresholds in basis
# points for future policy, 2Y, 10Y; DXY is percent return.
HYPOTHESES={
    "MP2_ONLY":{"MP2":2.0},
    "MP2_AND_2Y":{"MP2":2.0,"UST2Y":1.0},
    "MP2_AND_USD":{"MP2":2.0,"DXY":0.05},
    "MP2_2Y_USD":{"MP2":2.0,"UST2Y":1.0,"DXY":0.05},
    "MP2_2Y_10Y_USD":{"MP2":2.0,"UST2Y":1.0,"UST10Y":1.0,"DXY":0.05},
    "YIELD_2Y_10Y_USD":{"UST2Y":1.0,"UST10Y":1.0,"DXY":0.05},
    "YIELD_2Y_USD":{"UST2Y":1.0,"DXY":0.05},
    "STRONG_MP2_2Y_USD":{"MP2":3.0,"UST2Y":2.0,"DXY":0.10},
}
# These R3 gates are more stringent than describing 80% raw accuracy:
# do NOT call a small, cherry-picked n=1 signal validated.
RESEARCH_MIN_SIDE_N=30
RESEARCH_MIN_SIDE_ACCURACY=.80
RESEARCH_MIN_SIDE_WILSON95_LOWER=.70

def wilson95(wins,n):
    if not isinstance(wins,int) or not isinstance(n,int) or n<0 or wins<0 or wins>n:
        raise ValueError("INVALID_WIN_COUNTS")
    if n==0:return None
    z=1.959963984540054
    p=wins/n
    den=1+z*z/n
    center=(p+z*z/(2*n))/den
    rad=(z*sqrt(p*(1-p)/n+z*z/(4*n*n)))/den
    return [round(100*(center-rad),2),round(100*(center+rad),2)]

def _val(v):
    try:x=float(v)
    except (ValueError,TypeError):return None
    return x if isfinite(x) else None

def features(e):
    r=e.get("oracle_source_row") or {}
    # Official SF Fed USMPD MP2, UST2Y, UST10Y in percentage-point
    # changes -> basis points. DXY already percent, not bps.
    return {k:(_val(r.get(k))*(100 if k!="DXY" else 1)
               if _val(r.get(k)) is not None else None)
            for k in ("MP2","UST2Y","UST10Y","DXY")}

def classify(e,thresholds):
    values=features(e)
    if not thresholds or not set(thresholds).issubset(values):
        raise ValueError("BAD_HYPOTHESIS_FEATURES")
    if any(values[k] is None for k in thresholds):
        return "WAIT_MISSING_DATA"
    signs=[]
    for k,t in thresholds.items():
        x=values[k]
        signs.append(1 if x>=t else -1 if x<=-t else 0)
    if all(x==1 for x in signs):return "SELL"
    if all(x==-1 for x in signs):return "BUY"
    return "WAIT_CONFLICT_OR_SMALL"

def load_archive(folder):
    reports=[]
    for year in EXPECTED_YEARS:
        files=list(Path(folder).rglob(f"fed_macro_{year}.json"))
        if len(files)!=1:raise ValueError(f"NEED_ONE_YEAR_ARCHIVE_{year}")
        r=json.loads(files[0].read_text())
        if r.get("year")!=year or r.get("official_source_sha256")!=SOURCE_SHA:
            raise ValueError(f"UNTRUSTED_YEAR_SOURCE_{year}")
        if r.get("production_ready") is not False or r.get("genuine_pit_backtest") is not False:
            raise ValueError(f"FALSE_ASOF_LIVE_FLAG_{year}")
        reports.append(r)
    events=[dict(e) for r in reports for e in r["events"]]
    if len(events)!=69:
        raise ValueError(f"EXPECTED_69_EVENTS_GOT_{len(events)}")
    if len({e["event_id"] for e in events})!=len(events):
        raise ValueError("DUPLICATE_FOMC_EVENT")
    return sorted(events,key=lambda e:(e["release_at_utc"],e["event_id"]))

def with_labels(e,side,h):
    try:r=e["scores"][side]["outcomes"][h]
    except (KeyError,TypeError):return None
    return r if r.get("status")=="EVALUATED" else None

def _overlap(e,events,h,foldset):
    outcome=with_labels(e,"BUY",h)
    if outcome is None:
        outcome=with_labels(e,"SELL",h)
    if outcome is None:return False
    end=datetime.fromisoformat(outcome["end_at_utc"].replace("Z","+00:00"))
    start=datetime.fromisoformat(e["release_at_utc"].replace("Z","+00:00"))
    return any(start<datetime.fromisoformat(q["release_at_utc"].replace("Z","+00:00"))<end
               for q in events if q is not e)

def score_cohort(events,model,side,h,fold,*,exclude_next_fomc=True):
    years=set(fold)
    in_scope=[e for e in events if int(e["year"]) in years]
    selected=[e for e in in_scope if classify(e,HYPOTHESES[model])==side]
    usable=[];censored=0;overlap=0
    for e in selected:
        r=with_labels(e,side,h)
        if r is None:
            censored+=1;continue
        if exclude_next_fomc and _overlap(e,events,h,years):
            overlap+=1;continue
        usable.append((e,r))
    n=len(usable)
    wins=sum(1 for _,r in usable if r["direction_correct"] is True)
    rets=[r["signed_net_return_pct"] for _,r in usable]
    days=sorted({int(e["year"]) for e,_ in usable})
    ci=wilson95(wins,n)
    return {
        "selected_n":len(selected),"eligible_n":n,
        "correct_n":wins,
        "direction_accuracy_pct":round(100*wins/n,2) if n else None,
        "wilson95_pct":ci,
        "median_signed_net_return_pct":round(median(rets),4) if rets else None,
        "mean_signed_net_return_pct":round(mean(rets),4) if rets else None,
        "censored_n":censored,
        "excluded_next_fomc_overlap_n":overlap,
        "independent_calendar_years":days,
        "candidate_80pct_point_rate":bool(n>=RESEARCH_MIN_SIDE_N and wins/n>=RESEARCH_MIN_SIDE_ACCURACY) if n else False,
        "statistically_supported_80pct":bool(n>=RESEARCH_MIN_SIDE_N and ci and ci[0]>=80) if n else False,
        "prospective_live_wins":0,
    }

def baseline(events,side,h,fold):
    eligible=[e for e in events if e.get("scores") and int(e["year"]) in set(fold)]
    data=[with_labels(e,side,h) for e in eligible]
    valid=[x for x in data if x is not None]
    n=len(valid);w=sum(bool(x["direction_correct"]) for x in valid)
    return {"n":n,"wins":w,"accuracy_pct":round(100*w/n,2) if n else None}

def run(reports):
    events=reports
    results={}
    for model in HYPOTHESES:
        results[model]={}
        for fold,years in FOLDS.items():
            results[model][fold]={}
            for h in HORIZONS:
                results[model][fold][h]={
                    side:score_cohort(events,model,side,h,years)
                    for side in SIDES}
    baseline_stats={
        name:{h:{side:baseline(events,side,h,years) for side in SIDES}
              for h in HORIZONS}
        for name,years in FOLDS.items()}
    observed_hits=[]
    for name in HYPOTHESES:
        for h in HORIZONS:
            buy=results[name]["all_2019_2026"][h]["BUY"]
            sell=results[name]["all_2019_2026"][h]["SELL"]
            if (buy["candidate_80pct_point_rate"] and sell["candidate_80pct_point_rate"]):
                observed_hits.append({"model":name,"horizon":h,"buy":buy,"sell":sell})
    return {
        "contract":"RIZAN_FED_MACRO_80PCT_R3_FALSIFICATION_2019_2026",
        "event_count":len(events),"source":"OFFICIAL_USMPD_2019_2026_EXPOST",
        "features_units":{"MP2":"bps","UST2Y":"bps","UST10Y":"bps","DXY":"percent"},
        "predeclared_hypotheses":HYPOTHESES,
        "test_folds":FOLDS,
        "horizons":HORIZONS,
        "multi_test_warning":"8 models x 4 horizons x 2 sides; NO winner selection as validated strategy",
        "source_timestamps":"USMPD event-window retrospective publication; NOT true realtime",
        "assumed_roundtrip_cost_usd_oz":0.50,
        "results":results,
        "matched_no_filter_baseline":baseline_stats,
        "models_meeting_both_sides_raw_80pct_with_n30":observed_hits,
        "research_side_minimum_n":RESEARCH_MIN_SIDE_N,
        "release_gate":{
            "production_eligible":False,
            "live_market_feed_point_in_time_verified":False,
            "independent_prospective_holdout_verified":False,
            "actual_bid_ask_and_carry_verified":False,
            "true_live_buy_n":0,"true_live_sell_n":0,
            "no_cbot_execution_authority":True,
        },
        "limitations":[
            "2019-2026 has been studied before, not true out-of-sample",
            "USMPD market responses observed after event and published as ex-post study",
            "Only statement/FOMC policy events, not every minutes, CPI, NFP or Fed speech",
            "One event per FOMC; daily future outcomes can overlap with separate FOMC event",
            "Raw percent accuracy without sample size and confidence interval is misleading",
            "No production merge, cBots, Frozen V1, Manual R3 or order modifications",
        ],
    }

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--input-dir",type=Path,required=True)
    p.add_argument("--out",type=Path,required=True)
    args=p.parse_args()
    events=load_archive(args.input_dir)
    results=run(events)
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(results,indent=2,allow_nan=False)+"\n")
    preview={
        "event_count":results["event_count"],
        "dual_side_80pct_n30_models":len(results["models_meeting_both_sides_raw_80pct_with_n30"]),
        "baseline_D1":results["matched_no_filter_baseline"]["all_2019_2026"]["D1"],
        "baseline_D5":results["matched_no_filter_baseline"]["all_2019_2026"]["D5"],
        "method_results":{
            m:{h:{side:{k:v[k] for k in (
                "selected_n","eligible_n","correct_n","direction_accuracy_pct","wilson95_pct",
                "mean_signed_net_return_pct","censored_n","excluded_next_fomc_overlap_n")}
                  for side,v in results["results"][m]["all_2019_2026"][h].items()}
               for h in ("D1","D5","D10")}
            for m in HYPOTHESES},
    }
    print("FED_MACRO_R3_80PCT_ABLATION",json.dumps(preview,allow_nan=False))
if __name__=="__main__":main()

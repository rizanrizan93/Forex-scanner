"""Eight real-XAU 2023 FOMC meetings: H4, D1/D3/D5/D10 outcome replay.

This is EX-POST oracle falsification with official USMPD event factors,
NOT a genuine as-of trading backtest. No optimization and no execution.
Each meeting counts only once in the default FULL_MONETARY comparison.
"""
from __future__ import annotations
from datetime import timedelta, timezone
from pathlib import Path
import argparse, hashlib, json, statistics
from collections import defaultdict
import pandas as pd
from histdata_fetcher import fetch_data
from fx_scanner.research_xau_histdata_download_v193 import _normalize_frame, PROVIDER_COMMIT
from scripts.replay_rejection_v2_outcomes import wilson
from scripts.replay_fed_macro_event_pilot_r1 import (
    PINNED_SOURCE_SHA, SOURCE_URL, excel_et, load_sheet, event_schedule,
    classify_offline_window, fetch_official)
from research.fed_expectation_r1.macro_horizons import evaluate_macro_horizons, HORIZONS

YEAR=2023
AFTER_EVENT_CALENDAR_DAYS=23
COST_USD_OZ=0.50

def summarize(events):
    output={}
    for window in ("STATEMENT","PRESS_CONFERENCE","FULL_MONETARY"):
        subset=[e for e in events if e["window"]==window]
        output[window]={"independent_meeting_count":len(subset)}
        for horizon in HORIZONS:
            by_side={}
            for side in ("BUY","SELL"):
                selected=[e for e in subset if e["oracle_direction"]["side"]==side]
                labels=[e["labels"][side]["outcomes"][horizon] for e in selected]
                evaluable=[r for r in labels if r["status"]=="EVALUATED"]
                correct=sum(x["direction_correct"] for x in evaluable)
                n=len(evaluable)
                net=[x["signed_net_return_pct"] for x in evaluable]
                by_side[side]={
                    "selected_oracle_meetings":len(selected),
                    "n_evaluable":n,
                    "direction_correct_n":int(correct),
                    "direction_accuracy_pct":round(100*correct/n,2) if n else None,
                    "wilson95_pct":wilson(correct,n),
                    "median_signed_net_return_pct":round(statistics.median(net),4)
                        if net else None,
                    "censored":len(labels)-n,
                    "asof_eligible_n":0,
                    "not_valid_for_production_accuracy":True}
            output[window][horizon]=by_side
    return output

def run():
    source=fetch_official()
    if hashlib.sha256(source).hexdigest()!=PINNED_SOURCE_SHA:
        raise ValueError("OFFICIAL_USMPD_SHA_MISMATCH")
    rows=load_sheet(source,"xl/worksheets/sheet2.xml")
    meeting_days=sorted({excel_et(r["Date"]).date()
                         for r in rows if isinstance(r.get("Date"),(int,float)) and
                         excel_et(r["Date"]).year==YEAR})
    if len(meeting_days)!=8:
        raise ValueError("UNEXPECTED_2023_FOMC_EVENT_COUNT")
    events=[];sources=[];failures=[]
    for day in meeting_days:
        try:
            fetched=fetch_data(pair="XAUUSD",
                start_date=day,end_date=day+timedelta(days=AFTER_EVENT_CALENDAR_DAYS),
                timeframe="1min",output_format=None,max_workers=1)
            missing=[{"period":v.period_label,"reason":v.reason}
                     for v in fetched.failed_periods]
            if missing or fetched.data.empty:
                failures.append({"date":day.isoformat(),
                                 "reason":"MISSING_HISTDATA_PERIOD",
                                 "failed_periods":missing})
                continue
            data=_normalize_frame(fetched.data)
            data.index=pd.DatetimeIndex(data.pop("timestamp")).tz_convert("UTC")
            if data.index.has_duplicates or not data.index.is_monotonic_increasing:
                raise ValueError("UNTRUSTED_M1_ORDER")
            sha=hashlib.sha256(data.to_csv(float_format="%.6f").encode()).hexdigest()
            sources.append({"date":day.isoformat(),"rows":len(data),
                            "sha256":sha,"provider_commit":PROVIDER_COMMIT,
                            "source_timestamp_contract":"FIXED_EST_UTC_MINUS5_NO_DST",
                            "normalized_timestamp_contract":"UTC","failed_periods":[]})
            for kind,end_et,macro in event_schedule(source,day.isoformat()):
                ts=pd.Timestamp(end_et.astimezone(timezone.utc))
                offline=classify_offline_window(macro)
                labels={side:evaluate_macro_horizons(data,signal_at=ts,side=side,
                           cost_usd_oz=COST_USD_OZ)
                        for side in ("BUY","SELL")}
                events.append({
                    "meeting_date":day.isoformat(),"window":kind,
                    "signal_at_utc":ts.isoformat(),
                    "oracle_direction":offline,"labels":labels,
                    "xau_data_sha":sha,"asof_eligible":False})
        except Exception as exc:
            failures.append({"date":day.isoformat(),
                             "reason":type(exc).__name__+": "+str(exc)[:350]})
    return {
        "contract":"FED_MACRO_R1_EIGHT_FOMC_2023_DAILY_WEEKLY_REPLAY_EXPOST",
        "official_usmpd_url":SOURCE_URL,
        "official_usmpd_sha":PINNED_SOURCE_SHA,
        "year":YEAR,"meetings_expected":8,
        "meetings_with_data":len(sources),"failed_meetings":failures,
        "separate_window_statistics":summarize(events),
        "events":events,"xau_sources":sources,
        "horizon_semantics":"D1,D3,D5,D10 are NEXT full weekday UTC trading session closes; H4 requires 240 contiguous M1",
        "overlapping_window_policy":"STATEMENT,PC,FULL are not independent; default comparison FULL only",
        "macro_signal_type":"RETROSPECTIVE_ORACLE_NOT_PIT",
        "asof_eligible_buy_n":0,"asof_eligible_sell_n":0,
        "execution_authority":False,"production_eligible":False,
        "limitations":[
            "Ex-post USMPD event factors were NOT proven available at historical decision times",
            "All 2023 FOMC meetings already known research sample, NOT pristine holdout",
            "Modeled 0.50 USD/oz cost; not realized bid/ask spread or executable fills",
            "Full weekday UTC trading-day heuristic; holiday/missing weekdays censored",
            "One FOMC meeting is one independent event; windows must not be pooled",
            "No comparison yet to genuine as-of macro feed plus Rejection V4 signals",
        ]}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--out",type=Path,required=True)
    args=p.parse_args()
    r=run()
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(r,indent=2,allow_nan=False)+"\n")
    print("FED_MACRO_2023_LONG_HORIZON",json.dumps({k:v for k,v in r.items()
        if k not in ("events","xau_sources")},allow_nan=False))
if __name__=="__main__":
    main()

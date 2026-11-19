"""2023 FOMC eight-meeting pilot; real XAU M1 + official ex-post USMPD.

Falsification research ONLY. Each FOMC meeting is one independent unit;
statement/PC/full monetary windows overlap and are separate *views*, NOT
extra independent trades. No LIVE, no actual archived as-of snapshots,
hypothetical $0.50/oz cost. Data-provider failures logged and NOT imputed.
"""
from __future__ import annotations
from datetime import date, datetime, timedelta
from pathlib import Path
from collections import defaultdict
import argparse, hashlib, json
import pandas as pd
from histdata_fetcher import fetch_data
from fx_scanner.research_xau_histdata_download_v193 import _normalize_frame,PROVIDER_COMMIT
from scripts.replay_fed_macro_event_pilot_r1 import (
    PINNED_SOURCE_SHA, SOURCE_URL, excel_et, load_sheet, event_schedule,
    classify_offline_window, fetch_official)
from scripts.replay_rejection_v2_outcomes import future, wilson

YEAR=2023

def _score(d,at_utc,side):
    t=pd.Timestamp(at_utc)
    ix=d.index.get_indexer([t-pd.Timedelta(minutes=1)])
    if len(ix)!=1 or ix[0]<0:
        return {"status":"MISSING_EXACT_ENTRY_CLOCK",
                "h1_complete":False,"h4_complete":False}
    i=int(ix[0])
    h1=future(d,i,side,60,3,3)
    h4=future(d,i,side,240,10,5)
    return {
        "status":"H1_AVAILABLE" if h1 else "H1_CENSORED",
        "h1_complete":h1 is not None,"h4_complete":h4 is not None,
        "h1_direction_correct_after_cost":bool(h1["net_end"]>0) if h1 else None,
        "h1_3_before_3":bool(h1["state"]=="TARGET_FIRST") if h1 else None,
        "h1_terminal_net_usd_oz":round(h1["net_end"],3) if h1 else None,
        "h4_direction_correct_after_cost":bool(h4["net_end"]>0) if h4 else None,
        "h4_10_before_5":bool(h4["state"]=="TARGET_FIRST") if h4 else None,
        "h4_terminal_net_usd_oz":round(h4["net_end"],3) if h4 else None}

def _by_kind(items):
    out={}
    for kind in ("STATEMENT","PRESS_CONFERENCE","FULL_MONETARY"):
        filtered=[e for e in items if e.get("window")==kind]
        records={}
        for side in ("BUY","SELL"):
            both=[e["score"][side] for e in filtered if e.get("score")]
            valid=[x for x in both if x["h1_complete"]]
            wins=sum(x["h1_direction_correct_after_cost"] for x in valid)
            hits=sum(x["h1_3_before_3"] for x in valid)
            eligible=[e for e in filtered if e.get("macro_oracle",{}).get("side")==side]
            eligible_valid=[e["score"][side] for e in eligible
                            if e.get("score") and e["score"][side]["h1_complete"]]
            ew=sum(x["h1_direction_correct_after_cost"] for x in eligible_valid)
            records[side]={
                "unfiltered_counterfactual_events":len(both),
                "h1_evaluable_unfiltered":len(valid),
                "h1_direction_correct_unfiltered":int(wins),
                "h1_direction_rate_unfiltered_pct":round(100*wins/len(valid),2) if valid else None,
                "h1_3before3_unfiltered":int(hits),
                "oracle_selected_events":len(eligible),
                "oracle_h1_evaluable":len(eligible_valid),
                "oracle_h1_direction_correct":int(ew),
                "oracle_h1_direction_pct":round(100*ew/len(eligible_valid),2)
                    if eligible_valid else None,
                "oracle_wilson95_h1_pct":wilson(ew,len(eligible_valid)),
                "can_use_for_pit_accuracy":False,
            }
        out[kind]={"meetings":len(filtered),"buy_sell":records,
                   "macro_wait_events":sum(e.get("macro_oracle",{}).get("side")=="WAIT"
                                           for e in filtered)}
    return out

def run_year(raw=None):
    source=fetch_official() if raw is None else raw
    if hashlib.sha256(source).hexdigest()!=PINNED_SOURCE_SHA:
        raise ValueError("OFFICIAL_USMPD_SHA_CHANGED")
    rowset=load_sheet(source,"xl/worksheets/sheet2.xml")
    target_dates=sorted({excel_et(row["Date"]).date()
                        for row in rowset
                        if isinstance(row.get("Date"),(int,float))
                        and excel_et(row["Date"]).year==YEAR})
    results=[]; sources=[]; failures=[]
    if len(target_dates)!=8:
        raise ValueError("UNEXPECTED_2023_USMPD_FOMC_MEETING_COUNT")
    for event_date in target_dates:
        try:
            response=fetch_data(pair="XAUUSD",
                start_date=event_date,
                end_date=event_date+timedelta(days=1),
                timeframe="1min",output_format=None,max_workers=1)
            bad=[{"period":v.period_label,"reason":v.reason}
                 for v in response.failed_periods]
            if bad or response.data.empty:
                raise RuntimeError("HISTDATA_MISSING_OR_FAILED "+json.dumps(bad))
            d=_normalize_frame(response.data)
            d.index=pd.DatetimeIndex(d.pop("timestamp")).tz_convert("UTC")
            if d.index.has_duplicates or not d.index.is_monotonic_increasing:
                raise ValueError("BAD_XAU_SOURCE_TIMESTAMP")
            source_sha=hashlib.sha256(d.to_csv(float_format="%.6f").encode()).hexdigest()
            sources.append({"meeting_date":event_date.isoformat(),
                            "M1_rows":len(d),"SHA256_UTC_normalized":source_sha,
                            "source_tier":"PUBLIC_SECONDARY_MARKET_DATA",
                            "source_timestamp":"FIXED_EST_UTC_MINUS5_NO_DST",
                            "provider_commit":PROVIDER_COMMIT,"failed_periods":[]})
            for kind,window_end_et,row in event_schedule(source,event_date.isoformat()):
                side=classify_offline_window(row)
                moment=window_end_et.astimezone(__import__("datetime").timezone.utc)
                rec={"meeting_date":event_date.isoformat(),"window":kind,
                     "window_end_utc":moment.isoformat(),
                     "macro_oracle":side,"price_m1_source_sha":source_sha,
                     "score":{k:_score(d,moment,k) for k in ("BUY","SELL")},
                     "asof_eligible":False}
                results.append(rec)
        except Exception as exc:
            failures.append({"meeting_date":event_date.isoformat(),
                             "cause":type(exc).__name__+": "+str(exc)[:240]})
    return {"contract":"FED_MACRO_R1_USMPD_REAL_XAU_FOMC_2023_BATCH_ORACLE",
        "year":YEAR,"expected_meetings":len(target_dates),
        "fetched_meetings":len(sources),"failed_meetings":failures,
        "official_usmpd_sha":PINNED_SOURCE_SHA,"official_usmpd_url":SOURCE_URL,
        "xau_sources":sources,"event_outcomes":results,
        "separate_window_stats":_by_kind(results),
        "eligible_asof_buy_n":0,"eligible_asof_sell_n":0,
        "production_ready":False,
        "comment":"Official window factors ex-post; historical 2023 prices are real, but NO archived at-time macro quote snapshots",
        "caveats":[
            "Statement, PC, Monetary Events from a single meeting overlap and cannot be pooled",
            "Official USMPD final research factors are ex-post, not historical live-availability evidence",
            "Actual broker fill/quote/spread/slippage unavailable; assumed synthetic $0.50/oz",
            "Missing M1 or daily-market close censors outcomes; do not impute",
            "Only one previously researched year, not prospective holdout or 2019-2026 validation",
        ]}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--out",type=Path,required=True)
    args=p.parse_args()
    report=run_year()
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(report,indent=2,allow_nan=False)+"\n")
    print("FED_MACRO_2023_REAL_XAU_BATCH",json.dumps({k:v for k,v in report.items()
          if k not in ("event_outcomes","xau_sources")},allow_nan=False))
if __name__=="__main__":main()

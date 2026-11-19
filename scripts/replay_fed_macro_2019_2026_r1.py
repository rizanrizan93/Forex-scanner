"""2019–2026 real XAU × official USMPD Fed event windows, EX-POST oracle.

RESEARCH ONLY: USMPD is retrospective event-study data. It is NOT a
historically captured realtime expectation feed, so every result has
asof_eligible=False and production_ready=False. No broker/order access.

Predeclared comparison: MP2-only (±2 bp) versus MP2/UST2Y/DXY unanimous
(±2 bp / ±1 bp / ±0.05%); include always BUY/SELL matched-date baselines.
Score H4 D1 D3 D5 D10 on observed XAU market M1, with censoring.
"""
from __future__ import annotations
from datetime import date,timedelta,timezone
from collections import Counter
from pathlib import Path
import argparse, hashlib,json,statistics
import pandas as pd
from scripts.replay_fed_macro_event_pilot_r1 import (
    PINNED_SOURCE_SHA,SOURCE_URL,excel_et,load_sheet,fetch_official,
    classify_offline_window,
)
from research.fed_expectation_r1.macro_horizons import evaluate_macro_horizons,HORIZONS
from scripts.replay_rejection_v2_outcomes import wilson

RESEARCH_CUTOFF=date(2026,11,20)
FIRST_YEAR=2019
LAST_YEAR=2026
FUTURE_DAYS=23
COST_USD_OZ=0.50
SHEETS={"STATEMENT":"xl/worksheets/sheet2.xml",
        "PRESS_CONFERENCE":"xl/worksheets/sheet3.xml",
        "FULL_MONETARY":"xl/worksheets/sheet4.xml"}
METHODS=("MP2_ONLY","THREE_MARKET_CONSENSUS")
HORIZON_NAMES=("H4","D1","D3","D5","D10")

def _date(r):
    value=r.get("Date")
    if isinstance(value,(int,float)):
        return excel_et(value).date()
    raise ValueError("NO_NUMERIC_OFFICIAL_DATE")

def raw_policy_sign(r):
    try:
        v=float(r["MP2"])*100
    except (TypeError,ValueError,KeyError):
        return {"side":"WAIT","reason":"MP2_NOT_AVAILABLE","mp2_bp":None}
    side="SELL" if v>=2 else "BUY" if v<=-2 else "WAIT"
    return {"side":side,"reason":"MP2_SHOCK_EXPOST" if side!="WAIT" else
            "MP2_TOO_SMALL","mp2_bp":round(v,5)}

def _by_day(rows):
    out={}
    for r in rows:
        try:
            d=_date(r)
        except ValueError:
            continue
        out.setdefault(d,[]).append(r)
    return out

def event_plan(source,year):
    """Every real statement is an event. No imaginary press conference."""
    if year not in range(FIRST_YEAR,LAST_YEAR+1):
        raise ValueError("YEAR_OUTSIDE_PROTOCOL")
    stmt=_by_day(load_sheet(source,SHEETS["STATEMENT"]))
    pc=_by_day(load_sheet(source,SHEETS["PRESS_CONFERENCE"]))
    full=_by_day(load_sheet(source,SHEETS["FULL_MONETARY"]))
    events=[]
    for d in sorted(k for k in stmt if k.year==year):
        for ordinal,s in enumerate(stmt[d],1):
            try:
                start=excel_et(s["date_time"])
                if start.date()!=d:raise ValueError("STATEMENT_LOCAL_DATE_MISMATCH")
                candidates=full.get(d,[])
                press=pc.get(d,[])
                # When multiple events fall on one calendar day, we cannot
                # deduce the correct full PC ↔ statement pairing by date.
                if len(stmt[d])==1 and len(candidates)==1 and len(press)==1:
                    pc_start=excel_et(press[0]["date_time"])
                    if pc_start<start:raise ValueError("PRESS_BEGINS_BEFORE_STATEMENT")
                    row=candidates[0];kind="FULL_MONETARY"
                    at=pc_start+timedelta(minutes=60)
                elif len(stmt[d])==1 and len(candidates)==0 and len(press)==1:
                    row=press[0];kind="PRESS_CONFERENCE"
                    at=excel_et(row["date_time"])+timedelta(minutes=60)
                else:
                    row=s;kind="STATEMENT"
                    at=start+timedelta(minutes=20)
                if at<start:raise ValueError("EVENT_END_BEFORE_RELEASE")
                if d>RESEARCH_CUTOFF:raise ValueError("FUTURE_EVENT")
                events.append({
                    "event_id":f"FOMC-{d.isoformat()}-{ordinal}",
                    "date":d.isoformat(),"year":year,
                    "window":kind,"release_at_utc":start.astimezone(timezone.utc).isoformat(),
                    "window_end_utc":at.astimezone(timezone.utc).isoformat(),
                    "unavailable_press_conference":kind=="STATEMENT",
                    "oracle_policy_only":raw_policy_sign(row),
                    "oracle_consensus":classify_offline_window(row),
                    "oracle_source_row":{k:row.get(k) for k in
                        ("MP2","UST2Y","DXY","MP1","UST10Y")},
                    "no_intraday_asof_source":True,
                })
            except (TypeError,ValueError,KeyError) as exc:
                events.append({
                    "event_id":f"FOMC-{d.isoformat()}-{ordinal}",
                    "date":d.isoformat(),"year":year,"error":str(exc),
                    "invalid_event":True,
                    "no_intraday_asof_source":True})
    return events

def _metric(events,horizon,method,side,*,baseline=False):
    if baseline:
        chosen=[e for e in events if "scores" in e]
    else:
        field="oracle_policy_only" if method=="MP2_ONLY" else "oracle_consensus"
        chosen=[e for e in events if e.get(field,{}).get("side")==side and
                "scores" in e]
    records=[e["scores"][side]["outcomes"][horizon] for e in chosen]
    known=[x for x in records if x["status"]=="EVALUATED"]
    n=len(known);wins=sum(x["direction_correct"] for x in known)
    returns=[x["signed_net_return_pct"] for x in known]
    moves=[x["terminal_net_usd_oz"] for x in known]
    return {
        "selected_n":len(chosen),"n_evaluable":n,"n_censored":len(chosen)-n,
        "wins":int(wins),"direction_accuracy_pct":round(100*wins/n,2) if n else None,
        "wilson95_pct":wilson(wins,n),
        "median_signed_net_return_pct":round(statistics.median(returns),5) if returns else None,
        "mean_signed_net_return_pct":round(statistics.mean(returns),5) if returns else None,
        "mean_signed_net_usd_oz":round(statistics.mean(moves),3) if moves else None,
        "asof_valid_signal_n":0,
        "accuracy_production_eligible":False,
    }

def report_stats(events,year):
    valid=[e for e in events if "scores" in e]
    out={"year":year,
         "official_statement_rows":len(events),
         "evaluated_event_sources":len(valid),
         "missing_data_or_invalid_event":len(events)-len(valid),
         "oracle_signal_counts":{
             m:dict(Counter(
                 e["oracle_policy_only" if m=="MP2_ONLY" else "oracle_consensus"]["side"]
                 for e in events if "scores" in e)) for m in METHODS},
         "by_method":{}}
    for method in METHODS:
        out["by_method"][method]={}
        for h in HORIZON_NAMES:
            out["by_method"][method][h]={
                side:_metric(events,h,method,side) for side in ("BUY","SELL")}
    out["same_event_unconditional_price_baseline"]={
        h:{side:_metric(events,h,"",side,baseline=True) for side in ("BUY","SELL")}
        for h in HORIZON_NAMES}
    return out

def load_real_xau(start,end):
    """Explicit bounded date, source git pin; no fake price interpolation."""
    from histdata_fetcher import fetch_data
    from fx_scanner.research_xau_histdata_download_v193 import (
        _normalize_frame,PROVIDER_COMMIT)
    result=fetch_data(pair="XAUUSD",start_date=start,end_date=end,
                      timeframe="1min",output_format=None,max_workers=1)
    failed=[{"period":x.period_label,"reason":x.reason}
            for x in result.failed_periods]
    if failed or result.data.empty:
        raise ValueError("DATA_SOURCE_FAILED_OR_EMPTY: "+json.dumps(failed)[:200])
    frame=_normalize_frame(result.data)
    frame.index=pd.DatetimeIndex(frame.pop("timestamp")).tz_convert("UTC")
    if frame.index.has_duplicates or not frame.index.is_monotonic_increasing:
        raise ValueError("UNSORTED_OR_DUPLICATE_M1")
    sha=hashlib.sha256(frame.to_csv(float_format="%.6f").encode()).hexdigest()
    return frame,{
        "utc_normalized_m1_sha256":sha,"bar_count":len(frame),
        "first_m1_open":frame.index[0].isoformat(),
        "last_m1_open":frame.index[-1].isoformat(),
        "source":"HISTDATA_XAUUSD_M1_SECONDARY_MARKET",
        "provider_commit":PROVIDER_COMMIT,"utc_normalization":"SOURCE_FIXED_EST_MINUS5",
        "failed_periods":[]}

def run_year(year,*,source=None,fetcher=load_real_xau):
    if year not in range(FIRST_YEAR,LAST_YEAR+1):
        raise ValueError("BAD_YEAR")
    raw=source if source is not None else fetch_official()
    if hashlib.sha256(raw).hexdigest()!=PINNED_SOURCE_SHA:
        raise ValueError("OFFICIAL_SOURCE_SHA_CHANGED")
    plans=event_plan(raw,year)
    completed=[];failures=[];price_sources=[]
    for e in plans:
        if e.get("invalid_event"):
            failures.append({"event_id":e["event_id"],"reason":e["error"]})
            completed.append(e);continue
        start=date.fromisoformat(e["date"])
        end=min(start+timedelta(days=FUTURE_DAYS),RESEARCH_CUTOFF+timedelta(days=1))
        if end<=start:
            failures.append({"event_id":e["event_id"],"reason":"FUTURE_EVENT_WITHOUT_PRICES"})
            completed.append(e);continue
        try:
            price,manifest=fetcher(start,end)
            e["xau_source_sha"]=manifest["utc_normalized_m1_sha256"]
            e["price_rows"]=len(price)
            e["scores"]={side:evaluate_macro_horizons(price,
                signal_at=e["window_end_utc"],side=side,
                cost_usd_oz=COST_USD_OZ)
                for side in ("BUY","SELL")}
            price_sources.append({"event_id":e["event_id"],"date":e["date"],**manifest})
        except Exception as exc:
            failures.append({"event_id":e["event_id"],"reason":type(exc).__name__+
                             ": "+str(exc)[:240]})
            e["price_error"]=type(exc).__name__
        completed.append(e)
    return {
        "contract":"FED_MACRO_2019_2026_XAU_LONG_HORIZON_ORACLE_V1",
        "year":year,"statement_events_expected":len(plans),
        "real_price_sources_loaded":len(price_sources),
        "source_failures":failures,
        "official_source_url":SOURCE_URL,"official_source_sha256":PINNED_SOURCE_SHA,
        "signal_definition":"EX_POST_MP2_SHOCK; EX_POST_MP2_US2Y_DXY_CONSENSUS",
        "cutoff_date":RESEARCH_CUTOFF.isoformat(),
        "cost_assumption_usd_oz":COST_USD_OZ,
        "stats":report_stats(completed,year),
        "events":completed,"real_price_sources":price_sources,
        "asof_buy_n":0,"asof_sell_n":0,
        "genuine_pit_backtest":False,"production_ready":False,
        "caveats":[
            "Historical SF Fed USMPD ex-post release-window changes cannot be substituted for archived real-time futures expectations",
            "2019-2026 was previously researched; not pristine OOS",
            "D1/D3/D5/D10 represent full following UTC weekday sessions, not exact FP Markets roll-calendar",
            "Overlapping FOMC event outcomes, especially emergency 2020 meetings, must not be considered independent until exposure overlap is removed",
            "2026 incomplete through Nov 20; future labels are censored",
            "Fixed 0.50 USD/oz cost, not actual quoted spread/overnight carry/slippage",
            "No LIVE or production actions",
        ],
    }

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--year",type=int,required=True)
    ap.add_argument("--out",type=Path,required=True)
    args=ap.parse_args()
    result=run_year(args.year)
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(result,indent=2,allow_nan=False)+"\n")
    print("FED_MACRO_8YEAR_YEAR_REPORT",json.dumps({
        k:v for k,v in result.items() if k not in ("events","real_price_sources")},
        allow_nan=False))
if __name__=="__main__":
    main()

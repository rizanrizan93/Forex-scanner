"""Fed Information-Shock R4: XAU D1/D3/D5/D10 real-price falsification.

Research-only: READS official SF Fed full USMPD XLSX and sealed 2019-2026
R1 XAU event ledgers. Official factors are compiled EX POST, not captured
live quotes. Never claim true historical at-time signal, alpha or orders.

FOMC communicates BOTH policy decisions and economic information.
Rate/futures ↑ and equities ↓ is *policy-like*; ↑ and equities ↑ is
*information-like* (Jarocinski/Karadi sign split). Symmetric for ↓.
This sign split is a heuristic, not a causal structural decomposition.

All rules predeclared before looking at their 2019–2026 outcomes.
"""
from __future__ import annotations
import argparse, hashlib, json, math, statistics
from collections import Counter
from datetime import datetime,timezone,timedelta
from pathlib import Path
from scripts.replay_fed_macro_event_pilot_r1 import (
    load_sheet, fetch_official, excel_et, PINNED_SOURCE_SHA
)
from scripts.replay_fed_macro_80pct_r3 import (
    load_archive, wilson95
)

FIELDS=("MP2","OIS1Y","OIS2Y","UST2Y","UST10Y","TIPS5Y","TIPS10Y",
        "SP500","SPFUT","DXY")
BP_FIELDS=set(FIELDS)-{"SP500","SPFUT","DXY"}
SHEETS={"FULL_MONETARY":"xl/worksheets/sheet4.xml",
        "STATEMENT":"xl/worksheets/sheet2.xml",
        "PRESS_CONFERENCE":"xl/worksheets/sheet3.xml"}
HORIZONS=("D1","D3","D5","D10")
SIDES=("BUY","SELL")
FOLDS={
    "2019_2022_exploratory":tuple(range(2019,2023)),
    "2023_2024_already_touched":(2023,2024),
    "2025_2026_already_touched":(2025,2026),
    "all_2019_2026":tuple(range(2019,2027)),
}
# Magnitudes for symmetric sign concordance: policy/real yields (bp),
# USD / equity return (percentage points).
RULES={
    "MP2_ONLY":{"MP2":2.0},
    "MP2_TIPS10_DXY":{"MP2":2.0,"TIPS10Y":1.0,"DXY":.05},
    "OIS1Y_TIPS10_DXY":{"OIS1Y":1.5,"TIPS10Y":1.0,"DXY":.05},
    "TIPS10_DXY":{"TIPS10Y":1.0,"DXY":.05},
    "TIPS5_TIPS10_DXY":{"TIPS5Y":1.0,"TIPS10Y":1.0,"DXY":.05},
    "MP2_OIS1Y_TIPS10_DXY":{"MP2":2.0,"OIS1Y":1.5,"TIPS10Y":1.0,"DXY":.05},
    "POLICY_MP2_TIPS10_DXY_SP500_VETO":{"MP2":2.0,"TIPS10Y":1.0,"DXY":.05,"SP500":.10},
    "POLICY_MP2_UST2Y_SP500_VETO":{"MP2":2.0,"UST2Y":1.0,"SP500":.10},
    "POLICY_OIS1Y_TIPS10_SP500_VETO":{"OIS1Y":1.5,"TIPS10Y":1.0,"SP500":.10},
    "REAL_YIELD_ONLY":{"TIPS10Y":1.0},
}
STOCK_VETO={k for k in RULES if k.startswith("POLICY_")}

def _num(v):
    try:v=float(v)
    except (TypeError,ValueError):return None
    return v if math.isfinite(v) else None

def normalize_market(row):
    """Interest rates in percentage-point CHANGES, returns in percent."""
    result={}
    for k in FIELDS:
        x=_num(row.get(k))
        result[k]=round(x*100,6) if x is not None and k in BP_FIELDS else x
    if result["UST10Y"] is not None and result["TIPS10Y"] is not None:
        result["IMPLIED_BREAKEVEN10_CHANGE_BP"]=round(
            result["UST10Y"]-result["TIPS10Y"],6)
    else:result["IMPLIED_BREAKEVEN10_CHANGE_BP"]=None
    return result

def sign(v,threshold):
    return 1 if v>=threshold else -1 if v<=-threshold else 0

def classify(f,rule):
    conditions=RULES[rule]
    if any(f.get(k) is None for k in conditions):
        return "WAIT_MISSING"
    sides=[]
    for k,t in conditions.items():
        s=sign(f[k],t)
        if k=="SP500":s=-s # pure policy shock: yield ↑ stocks ↓
        sides.append(s)
    if all(s==1 for s in sides):return "SELL"
    if all(s==-1 for s in sides):return "BUY"
    return "WAIT_CONFLICT_OR_TOO_SMALL"

def shock_type(f):
    """Distinct classification, not an entry signal."""
    p=f.get("MP2")
    s=f.get("SP500")
    if p is None or s is None:return "UNKNOWN_MISSING"
    ps=sign(p,2.0);ss=sign(s,.10)
    if ps==0 or ss==0:return "UNKNOWN_SMALL"
    if ps==-ss:return "POLICY_LIKE"
    if ps==ss:return "INFORMATION_LIKE"
    return "UNKNOWN"

def source_join(events,source):
    rows={key:load_sheet(source,path) for key,path in SHEETS.items()}
    idx={}
    for kind,values in rows.items():
        dates={}
        for item in values:
            raw=item.get("Date")
            if not isinstance(raw,(float,int)):continue
            day=excel_et(raw).date().isoformat()
            dates.setdefault(day,[]).append(item)
        idx[kind]=dates
    out=[];failures=[]
    for original in events:
        e=dict(original)
        day=e["date"]; kind=e.get("window")
        candidates=idx.get(kind,{}).get(day,[])
        if len(candidates)!=1:
            e["r4_source_join"]="UNRESOLVED_AMBIGUOUS_OR_MISSING"
            failures.append({"id":e["event_id"],"kind":kind,
                             "date":day,"candidate_count":len(candidates)})
            out.append(e);continue
        item=candidates[0]
        # Source event clock in Eastern; matching only same date+window.
        # For full monetary, date_time is the statement release (not
        # the ending press conference), so compare release clock.
        stamp=item.get("date_time")
        try:
            actual=excel_et(stamp).astimezone(timezone.utc)
            expected=datetime.fromisoformat(
                e["release_at_utc"].replace("Z","+00:00"))
            seconds=abs((actual-expected).total_seconds())
        except (TypeError,ValueError) as ex:
            seconds=float("inf")
        if seconds>61:
            e["r4_source_join"]="UNRESOLVED_RELEASE_CLOCK_DISAGREEMENT"
            failures.append({"id":e["event_id"],"kind":kind,
                             "date":day,"source_time_deviation_s":seconds})
            out.append(e);continue
        e["r4_features"]=normalize_market(item)
        e["r4_shock_type"]=shock_type(e["r4_features"])
        e["r4_source_join"]="VERIFIED_DATE_WINDOW_AND_EVENT_CLOCK"
        out.append(e)
    return out,failures

def next_fomc_overlap(event,events,horizon):
    try:out=event["scores"]["BUY"]["outcomes"][horizon]
    except (KeyError,TypeError):return False
    if out.get("status")!="EVALUATED":return False
    first=datetime.fromisoformat(event["release_at_utc"])
    last=datetime.fromisoformat(out["end_at_utc"])
    return any(first<datetime.fromisoformat(x["release_at_utc"])<last
               for x in events if x["event_id"]!=event["event_id"])

def score(events,rule,side,horizon,years):
    sub=[e for e in events if e["year"] in set(years)]
    selected=[e for e in sub if e.get("r4_features") and
              classify(e["r4_features"],rule)==side]
    rows=[];missing=0;overlap=0
    for e in selected:
        o=e["scores"][side]["outcomes"][horizon]
        if o["status"]!="EVALUATED":
            missing+=1;continue
        if next_fomc_overlap(e,events,horizon):
            overlap+=1;continue
        rows.append(o)
    n=len(rows);w=sum(x["direction_correct"] is True for x in rows)
    returns=[x["signed_net_return_pct"] for x in rows]
    return {
        "selected_n":len(selected),"evaluated_n":n,"correct_n":w,
        "accuracy_pct":round(w*100/n,2) if n else None,
        "wilson95_pct":wilson95(w,n),
        "mean_signed_net_return_pct":round(statistics.mean(returns),5) if returns else None,
        "median_signed_net_return_pct":round(statistics.median(returns),5) if returns else None,
        "censored_n":missing,"excluded_overlapping_next_FOMC_n":overlap,
        "pass_80pct_with_30_independent_n":bool(n>=30 and w/n>=.8) if n else False,
        "genuine_pit_n":0,
    }

def run(events,source_bytes):
    if hashlib.sha256(source_bytes).hexdigest()!=PINNED_SOURCE_SHA:
        raise ValueError("OFFICIAL_USMPD_RAW_SHA_MISMATCH")
    if len(events)!=69:raise ValueError("REPLAY_REQUIRES_69_PREVIOUSLY_SEALED_EVENTS")
    es,joins=source_join(events,source_bytes)
    counts={k:sum(e.get("r4_source_join")==
                   "VERIFIED_DATE_WINDOW_AND_EVENT_CLOCK" for e in es
                   if e["year"]==k) for k in range(2019,2027)}
    result={}
    for rule in RULES:
        result[rule]={}
        for fold,years in FOLDS.items():
            result[rule][fold]={}
            for h in HORIZONS:
                result[rule][fold][h]={
                    side:score(es,rule,side,h,years) for side in SIDES}
    both=[]
    for rule in RULES:
        for h in HORIZONS:
            d=result[rule]["all_2019_2026"][h]
            if all(d[s]["pass_80pct_with_30_independent_n"] for s in SIDES):
                both.append({"rule":rule,"horizon":h})
    return {
        "contract":"FED_R4_INFORMATION_SHOCK_REAL_YIELD_FALSIFICATION",
        "official_usmpd_sha":PINNED_SOURCE_SHA,
        "event_count":len(es),"real_price_source":"R1_SEALED_REAL_XAU_M1",
        "verified_join_count":len(es)-len(joins),
        "join_failures":joins,
        "matched_by_year":counts,
        "source_fields_units":{
            "MP2":"bps","OIS1Y":"bps","OIS2Y":"bps",
            "UST2Y":"bps","UST10Y":"bps","TIPS5Y":"bps","TIPS10Y":"bps",
            "SP500":"percent","SPFUT":"percent","DXY":"percent",
            "IMPLIED_BREAKEVEN10_CHANGE_BP":"bps"},
        "fomc_shock_type_counts":dict(Counter(e.get("r4_shock_type","UNRESOLVED")
                                            for e in es)),
        "hypotheses":RULES,
        "folds":FOLDS,
        "results":result,
        "models_meeting_both_sides_80pct_n30":both,
        "research_only_no_orders":True,
        "production_ready":False,
        "both_sides_prospective_pit_n":{"BUY":0,"SELL":0},
        "limitations":[
            "The 2019-2026 sample has been repeatedly inspected; not untouched OOS",
            "USMPD completed event changes are retrospective study, not historically captured realtime",
            "Policy-vs-information sign split heuristic, not true causal shock identification",
            "TIPS benchmark intraday changes are not future breakevens without assumption",
            "After a FOMC no fixed D1-D10 direction without new macro reassessment",
            "Only FOMC communications; no independent CPI/PCE/NFP transcript surprise capture",
            "All ten rules and four horizons are multiple comparisons, not a valid optimized forecast",
            "No actual cTrader bid/ask, carry, slippage or broker execution",
        ],
    }

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--input-dir",type=Path,required=True)
    p.add_argument("--out",type=Path,required=True)
    a=p.parse_args()
    events=load_archive(a.input_dir)
    source=fetch_official()
    results=run(events,source)
    a.out.parent.mkdir(exist_ok=True,parents=True)
    a.out.write_text(json.dumps(results,indent=2,allow_nan=False)+"\n")
    abridged={
        "matched":results["verified_join_count"],
        "join_failures":results["join_failures"],
        "shock_types":results["fomc_shock_type_counts"],
        "models_meeting_both_sides_80pct_n30":results["models_meeting_both_sides_80pct_n30"],
        "D1_D5_D10":{k:{h:{s:{
            z:results["results"][k]["all_2019_2026"][h][s][z] for z in
            ("selected_n","evaluated_n","correct_n","accuracy_pct",
             "wilson95_pct","mean_signed_net_return_pct","censored_n",
             "excluded_overlapping_next_FOMC_n")}
                for s in SIDES} for h in ("D1","D5","D10")}
            for k in RULES},
        "production_ready":False}
    print("FED_R4_2019_2026_REAL_XAU_REPLAY",json.dumps(abridged,allow_nan=False))
if __name__=="__main__":main()

"""R2 2019-2026 FOMC official statement action vs XAU: audit / falsification.

Official-source event ACTION is not automatically the monetary-policy
SURPRISE. A cut can still be a HAWKISH surprise if markets expected
more easing. KEEP THESE COLUMNS DISTINCT.

Loads the precomputed read-only R1 XAU M1 event/price ledger from GitHub
Actions run 44621561755. Fetches historical official FOMC statement pages,
verifies matching official language and SHA, and compares actual
HIKE/HOLD/CUT with ex-post MP2 market repricing and XAU D1/D3/D5/D10.

No historic first-ingestion proof, no text-based minutes/speech replay,
no executable orders, no claims that ex-post USMPD was a live feed.
"""
from __future__ import annotations
from collections import Counter,defaultdict
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from pathlib import Path
from urllib.request import Request,urlopen
import argparse,json,re,statistics,time
from scripts.audit_fed_official_communications_r2 import extract_visible_text
from scripts.replay_rejection_v2_outcomes import wilson

BASE="https://www.federalreserve.gov/newsevents/pressreleases/"
SOURCE_R1_RUN=44621561755
OFFICIAL_USMPD_SHA="2b91297c42cf692dd74f65eabf7ee97f81d452676e23fa02edb222bfa60f0d0a"
PAT=re.compile(
    r"\b(?:the\s+)?committee\s+(?:decided|voted)\s+to\s+"
    r"(?P<verb>maintain|leave|keep|raise|increase|lower|reduce|decrease|cut)\b"
    r"(?P<context>[^.]{0,240})\btarget\s+range\s+for\s+the\s+federal\s+funds\s+rate\b"
    r"(?P<suffix>[^.]{0,150})",re.I)
ACTION={
    "maintain":"HOLD","leave":"HOLD","keep":"HOLD",
    "raise":"HIKE","increase":"HIKE",
    "lower":"CUT","reduce":"CUT","decrease":"CUT","cut":"CUT",
}
SIDES={"HIKE":"SELL","CUT":"BUY","HOLD":"WAIT"}

def parse_official_actual(text):
    matches=[(ACTION[m["verb"].lower()],m.group(0).strip())
             for m in PAT.finditer(text)]
    actions={a for a,_ in matches}
    if len(actions)!=1:
        return {"actual":"UNRESOLVED","quote":None,
                "failure":"NO_UNIQUE_COMMITTEE_TARGET_RATE_ACTION",
                "candidate_count":len(matches)}
    action=next(iter(actions))
    return {"actual":action,"quote":next(q for a,q in matches if a==action),
            "failure":None,"candidate_count":len(matches)}

def _fetch(date):
    url=BASE+"monetary"+date.replace("-","")+"a.htm"
    try:
        request=Request(url,headers={"User-Agent":"RIZAN-Fed-Statement-Archive/2.0"})
        with urlopen(request,timeout=18) as f:
            raw=f.read(2_000_001)
        if not raw or len(raw)>2_000_000:
            raise ValueError("BOUNDED_OFFICIAL_HTML_FAILED")
        text=extract_visible_text(raw.decode("utf-8","replace"))
        if not "Federal Reserve" in text or "federal funds rate" not in text.lower():
            raise ValueError("HTML_NOT_A_FED_POLICY_DOCUMENT")
        parsed=parse_official_actual(text)
        return {"date":date,"source_url":url,"source_raw_sha256":sha256(raw).hexdigest(),
                "source_text_sha256":sha256(text.encode("utf-8")).hexdigest(),
                "source_retrieval":"LATER_RESEARCH_AUDIT_NOT_HISTORICAL_LIVE_CAPTURE",
                **parsed}
    except Exception as e:
        return {"date":date,"source_url":url,"actual":"UNRESOLVED",
                "failure":type(e).__name__+":"+str(e)[:160]}

def _win(events, action,h, *,oracle_side=False):
    if oracle_side:
        group=[e for e in events if e.get("source_verification",{}).get("actual") in
               ("HIKE","CUT") and e.get("scores")]
    else:
        group=[e for e in events if e.get("source_verification",{}).get("actual")==action
               and e.get("scores")]
    wanted=SIDES[action] if not oracle_side else None
    if wanted=="WAIT":return {"selected":len(group),"wins":0,"n":0,"rate_pct":None}
    selected=[e for e in group if wanted!="WAIT"]
    n=0;wins=0;censored=0;returns=[]
    for e in selected:
        side=wanted or SIDES[e["source_verification"]["actual"]]
        o=e["scores"][side]["outcomes"][h]
        if o["status"]!="EVALUATED":censored+=1;continue
        n+=1
        wins+=int(o["direction_correct"])
        returns.append(o["signed_net_return_pct"])
    return {"selected":len(selected),"n":n,"wins":wins,
            "accuracy_pct":round(100*wins/n,2) if n else None,
            "wilson95_pct":wilson(wins,n),
            "censored":censored,
            "median_signed_net_return_pct":round(statistics.median(returns),5) if returns else None}

def run(files):
    years={}
    for f in files:
        x=json.loads(f.read_text())
        year=x.get("year")
        if year in years:raise ValueError("DUPLICATED_YEAR")
        if x.get("official_source_sha256")!=OFFICIAL_USMPD_SHA:
            raise ValueError("SOURCE_SHA_MISMATCH")
        if x.get("genuine_pit_backtest") is not False or x.get("production_ready") is not False:
            raise ValueError("R1_ARCHIVE_FALSE_PRODUCTION_FLAG")
        years[year]=x
    if sorted(years)!=list(range(2019,2027)):
        raise ValueError("MISSING_EIGHT_YEAR_ARCHIVE")
    events=sorted((dict(e) for y in years.values() for e in y["events"]),
                  key=lambda e:(e["date"],e["event_id"]))
    if len({e["event_id"] for e in events})!=len(events):
        raise ValueError("DUPLICATE_FOMC_EVENT_ID")
    distinct=sorted({e["date"] for e in events})
    # Only confirmed official HTML source matches count as actual decisions.
    with ThreadPoolExecutor(max_workers=4) as pool:
        official=list(pool.map(_fetch,distinct))
    lookup={e["date"]:e for e in official}
    for e in events:e["source_verification"]=lookup[e["date"]]
    counts=Counter(e["source_verification"]["actual"] for e in events)
    by_year={}
    for y in range(2019,2027):
        entries=[e for e in events if e["date"].startswith(str(y))]
        by_year[str(y)]={
            "event_n":len(entries),
            "source_verified_n":sum(e["source_verification"]["actual"]!="UNRESOLVED" for e in entries),
            "actual_actions":dict(Counter(e["source_verification"]["actual"] for e in entries)),
        }
    inconsistent=[]
    actual_vs_mp2=Counter()
    action_metrics={}
    for action in ("HIKE","CUT"):
        action_metrics[action]={h:_win(events,action,h) for h in ("D1","D3","D5","D10")}
    for e in events:
        action=e["source_verification"]["actual"]
        oracle=e.get("oracle_policy_only",{}).get("side","WAIT")
        if action not in ("HIKE","CUT","HOLD"):continue
        actual_vs_mp2[(action,oracle)]+=1
        if action in ("HIKE","CUT") and oracle not in ("WAIT",SIDES[action]):
            inconsistent.append({
                "date":e["date"],"actual":action,
                "naive_direction":SIDES[action],
                "retrospective_MP2_direction":oracle,
                "mp2_bp":e.get("oracle_policy_only",{}).get("mp2_bp"),
                "note":"Not a label inversion: actual policy move vs expected policy SURPRISE differs",
            })
    missing=[{"date":x["date"],"reason":x["failure"],"candidate_source_url":x["source_url"]}
             for x in official if x["failure"]]
    return {
        "contract":"FED_R2_HISTORICAL_OFFICIAL_STATEMENT_ACTION_REPLAY_V1",
        "r1_source_run_id":SOURCE_R1_RUN,
        "r1_official_usmpd_sha":OFFICIAL_USMPD_SHA,
        "event_count":len(events),
        "verified_official_statement_actions":sum(x["actual"]!="UNRESOLVED" for x in official),
        "action_counts":dict(counts),
        "action_by_year":by_year,
        "rate_action_xau_outcomes":action_metrics,
        "actual_vs_MP2_expost_direction":{
            "|".join(k):v for k,v in actual_vs_mp2.items()},
        "cases_where_actual_action_side_differs_from_expost_surprise":inconsistent,
        "official_source_unknowns":missing,
        "official_source_audit":official,
        "events":events,
        "text_minutes_and_speeches_full_2019_2026_replay_completed":False,
        "rate_action_is_not_policy_surprise":True,
        "expost_oracle_is_not_historical_pit":True,
        "genuine_pit_eligible_buy_n":0,
        "genuine_pit_eligible_sell_n":0,
        "production_ready":False,
        "entry_authority":False,
        "methodological_limitations":[
            "Rate direction alone is not the same as unexpectedly hawkish or dovish monetary policy",
            "Official source retrieval performed after events, not archived as-of with historical ingestion clocks",
            "Unknown/unparsed official statements marked UNRESOLVED; never infer policy action from MP2 or XAU",
            "Actual action vs XAU outcomes are illustrative conditional correlations not R2 text-trading win rates",
            "No full 2019-2026 FOMC minutes/speeches source/semantic replay; do not invent headline sentiment scores",
            "R1 price source: public secondary-market M1, synthetic spread 0.50 USD/oz, not FP Markets fills",
        ],
    }

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--input-dir",required=True,type=Path)
    parser.add_argument("--out",required=True,type=Path)
    a=parser.parse_args()
    files=[]
    for year in range(2019,2027):
        found=list(a.input_dir.rglob(f"fed_macro_{year}.json"))
        if len(found)!=1:raise ValueError(f"NO_UNIQUE_ARCHIVED_YEAR_{year}")
        files.append(found[0])
    result=run(files)
    a.out.parent.mkdir(parents=True,exist_ok=True)
    a.out.write_text(json.dumps(result,indent=2,allow_nan=False)+"\n")
    summary={k:v for k,v in result.items() if k not in ("events","official_source_audit")}
    print("FED_R2_STATEMENT_ACTION_8YEAR_REPLAY",json.dumps(summary,allow_nan=False))
if __name__=="__main__":main()

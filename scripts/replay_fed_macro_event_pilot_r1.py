"""First *real price* event-window falsification of Fed macro direction.

Important: Official USMPD is a RETROSPECTIVELY released LSEG event study,
not a historical streaming feed. This is an EX-POST / ORACLE diagnostic,
never a point-in-time production backtest, LIVE alert, or 60% proof.

Event 2023-09-20 is predeclared by official Federal Reserve FOMC release.
Statement: 14:00 ET -> after 14:20 ET; press conference: 14:30 ET ->
after 15:30 ET. The three windows overlap and MUST NOT be pooled as
independent trades. XAU real HistData M1 (fixed EST source -> UTC).
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import argparse, hashlib, io, json, math, zipfile
from pathlib import Path
import pandas as pd
from scripts.audit_frbsf_usmpd_xlsx_r1 import (
    SOURCE_URL, fetch_official, _as_value, _col_ref, _unshared)
from scripts.replay_rejection_v2_outcomes import load_csv, future

PINNED_SOURCE_SHA = "2b91297c42cf692dd74f65eabf7ee97f81d452676e23fa02edb222bfa60f0d0a"
FED_RELEASE_URL="https://www.federalreserve.gov/newsevents/pressreleases/monetary20230920a.htm"
TEST_DATE="2023-09-20"
ET=ZoneInfo("America/New_York")
EXCEL_EPOCH=datetime(1899,12,30)

def excel_et(v):
    if not isinstance(v,(int,float)) or not math.isfinite(v):
        raise ValueError("USMPD_DATE_TIME_INVALID")
    local=EXCEL_EPOCH+timedelta(days=float(v))
    # XLSX fractional-day arithmetic may differ by microseconds; official
    # communication timestamps have minute precision, never fabricated seconds.
    if local.second not in (0,59):
        raise ValueError("OFFICIAL_EVENT_NOT_MINUTE_ALIGNED")
    if local.second==59:local+=timedelta(seconds=1)
    return local.replace(second=0,microsecond=0,tzinfo=ET)

def load_sheet(source_bytes, filename):
    z=zipfile.ZipFile(io.BytesIO(source_bytes))
    strings=_unshared(z)
    root=__import__("xml.etree.ElementTree",fromlist=["ElementTree"]).fromstring(z.read(filename))
    ns={"x":"http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    headers=None; rows=[]
    for row in root.findall(".//x:sheetData/x:row",ns):
        values={}
        for c in row.findall("x:c",ns):
            v=_as_value(c,strings)
            if v is not None:
                values[_col_ref(c.attrib["r"])]=v
        if not values:continue
        if headers is None:
            headers=[str(values.get(i,"")) for i in range(max(values)+1)]
            continue
        rec={key:values.get(i) for i,key in enumerate(headers)}
        rows.append(rec)
    return rows

def classify_offline_window(row):
    """Use OFFICIAL EX-POST changes (MP2, UST2Y in p.p.; DXY in %).
    Not an input to the real-time decide() PIT engine.
    """
    keys=("MP2","UST2Y","DXY")
    if any(row.get(k) is None for k in keys):
        return {"side":"WAIT","reason":"MISSING_OFFICIAL_SERIES"}
    try:
        mp=100*float(row["MP2"])   # p.p. -> bps
        y2=100*float(row["UST2Y"])  # p.p. -> bps
        usd=float(row["DXY"])       # already percent return
    except (TypeError,ValueError):
        return {"side":"WAIT","reason":"NONNUMERIC_OFFICIAL_SERIES"}
    signs=(1 if mp>=2 else -1 if mp<=-2 else 0,
           1 if y2>=1 else -1 if y2<=-1 else 0,
           1 if usd>=.05 else -1 if usd<=-.05 else 0)
    side="SELL" if signs==(1,1,1) else "BUY" if signs==(-1,-1,-1) else "WAIT"
    return {"side":side,"reason":"RETROSPECTIVE_UNANIMOUS" if side!="WAIT" else "MIXED_OR_SMALL",
            "mp2_change_bp":round(mp,5),"us2y_change_bp":round(y2,5),
            "dxy_return_pct":round(usd,5)}

def event_schedule(source_bytes, event_date=TEST_DATE):
    sheet_files={"STATEMENT":"xl/worksheets/sheet2.xml",
                 "PRESS_CONFERENCE":"xl/worksheets/sheet3.xml",
                 "FULL_MONETARY":"xl/worksheets/sheet4.xml"}
    by_kind={}
    for kind,file in sheet_files.items():
        matches=[r for r in load_sheet(source_bytes,file)
                 if isinstance(r.get("Date"),(float,int)) and
                 excel_et(r["Date"]).date().isoformat()==event_date]
        if len(matches)!=1:raise ValueError(f"EXPECTED_ONE_{kind}_EVENT_GOT_{len(matches)}")
        by_kind[kind]=matches[0]
    start=excel_et(by_kind["STATEMENT"]["date_time"])
    pc=excel_et(by_kind["PRESS_CONFERENCE"]["date_time"])
    if start.date().isoformat()!=event_date or pc.date().isoformat()!=event_date:
        raise ValueError("EVENT_DATE_LOCAL_ET_MISMATCH")
    # Cross-check this known meeting against the official FOMC statement.
    if event_date==TEST_DATE and (start.hour,start.minute,pc.hour,pc.minute)!=(14,0,14,30):
        raise ValueError("FED_OFFICIAL_RELEASE_TIME_MISMATCH")
    return [
        ("STATEMENT",start+timedelta(minutes=20),by_kind["STATEMENT"]),
        ("PRESS_CONFERENCE",pc+timedelta(minutes=60),by_kind["PRESS_CONFERENCE"]),
        ("FULL_MONETARY",pc+timedelta(minutes=60),by_kind["FULL_MONETARY"]),
    ]

def replay_official_event(xau_m1, source_bytes, *, xau_sha,manifest):
    if hashlib.sha256(source_bytes).hexdigest()!=PINNED_SOURCE_SHA:
        raise ValueError("OFFICIAL_USMPD_SOURCE_SHA_CHANGED")
    d=xau_m1[["open","high","low","close"]].copy().astype(float)
    if d.index.tz is None or not d.index.is_monotonic_increasing or d.index.has_duplicates:
        raise ValueError("UTC_M1_REQUIRED")
    d.index=d.index.tz_convert("UTC")
    results=[]
    for kind,window_end_et,row in event_schedule(source_bytes):
        at=pd.Timestamp(window_end_et.astimezone(timezone.utc))
        # Last bar with close <= window_end; entry must be NEXT M1 open.
        matching=d.index.get_indexer([at-pd.Timedelta(minutes=1)])
        i=int(matching[0])
        if i<0:raise ValueError(f"MISSING_EXACT_M1_BAR_{kind}_{at}")
        fwd={}
        for side in ("BUY","SELL"):
            h1=future(d,i,side,60,3,3)
            h4=future(d,i,side,240,10,5)
            if h1 is None or h4 is None:
                raise ValueError(f"XAU_FORWARD_GAP_OR_INCOMPLETE_{kind}_{side}")
            fwd[side]={"h1_3before3":h1["state"],"h1_terminal_net_usd_oz":round(h1["net_end"],3),
                       "h4_10before5":h4["state"],"h4_terminal_net_usd_oz":round(h4["net_end"],3),
                       "mfe_1h_usd_oz":round(h1["mfe"],3),"mae_1h_usd_oz":round(h1["mae"],3)}
        offline=classify_offline_window(row)
        results.append({"kind":kind,"window_end_et":window_end_et.isoformat(),
                        "window_end_utc":at.isoformat(),"xau_last_closed_m1_utc":d.index[i].isoformat(),
                        "oracle_macro":offline,"both_sides_counterfactual":fwd,
                        "production_eligible":False,
                        "reason_not_production":"RETROSPECTIVE_USMPD_FACTORS_NOT_ARCHIVED_AS_OF_THIS_2023_MINUTE"})
    # This official Excel file is a retrospective source and cannot be used to
    # generate historically archived realtime Fed expectation signals.
    from research.fed_expectation_r1.engine import decide
    event={"event_id":"FOMC-2023-09-20",
           "event_kind":"FOMC_STATEMENT","release_at":"2023-09-20T18:00:00Z",
           "source_url":FED_RELEASE_URL}
    pit=decide(event,[],decision_at="2023-09-20T18:20:00Z")
    if pit["search_bias"]!="NONE" or pit["direction"]!="WAIT":
        raise AssertionError("FALSE_READY_FROM_MISSING_HISTORICAL_QUOTES")
    return {
        "contract":"FED_MACRO_R1_OFFICIAL_USMPD_XAU_REAL_PRICE_PILOT",
        "event_date":TEST_DATE,"fed_event_url":FED_RELEASE_URL,
        "official_usmpd_url":SOURCE_URL,"official_usmpd_sha256":PINNED_SOURCE_SHA,
        "xau_source":manifest,"xau_csv_sha256":xau_sha,
        "price_rows":len(d),"cost_model":"0.50 USD/oz synthetic round trip; next-M1-open",
        "outcomes":results,
        "macro_pit_live_ready_n":0,"eligible_buy_n":0,"eligible_sell_n":0,
        "historical_independent_event_n":1,
        "windows_are_overlapping_not_independent":True,
        "risk_gate":"NO_PRODUCTION",
        "caveats":["Official USMPD event-study data calculated retrospectively; not historically archived live quotes",
                   "All window-level directions are ex-post oracle diagnostics, not eligible backtest signals",
                   "Three windows belong to ONE FOMC meeting; do not pool",
                   "Broker bid/ask actual spread and event slippage unknown",
                   "2023 is a prior explored period, not untouched holdout",
                   "No verified expected-policy-rate same-contract pre/post snapshots for the R1 engine"]
    }

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--csv",type=Path,required=True)
    p.add_argument("--out",type=Path,required=True)
    a=p.parse_args()
    manifest_path=Path(str(a.csv)+".provenance.json")
    if not manifest_path.exists():raise ValueError("MISSING_REAL_XAU_PROVENANCE")
    manifest=json.loads(manifest_path.read_text())
    sha=hashlib.sha256(a.csv.read_bytes()).hexdigest()
    if (manifest.get("sha256_csv")!=sha or manifest.get("failed_periods")
        or manifest.get("source")!="HISTDATA_XAUUSD_M1"
        or manifest.get("timestamp_normalized")!="UTC"):
        raise ValueError("SOURCE_MANIFEST_INVALID")
    data=load_csv(a.csv)
    raw=fetch_official()
    out=replay_official_event(data,raw,xau_sha=sha,manifest=manifest)
    from research.fed_expectation_r1.release_gate import evaluate
    report=evaluate({
        "paired_real_xau_events":False, # offline oracle is NOT a PIT event
        "futures_same_contract_pit":False,
        "intraday_cash_us2y_pit":False,
        "usd_proxy_pit":False,
        "source_hashes_valid":True,
        "utc_release_windows_verified":True,
        "real_quote_age_and_spread_valid":False,
        "commission_slippage_included":False,
        "genuine_prospective_holdout":False,
        "buy":{"n":0,"wins":0,"nonoverlapping":True,"net_expectancy_usd":0.0},
        "sell":{"n":0,"wins":0,"nonoverlapping":True,"net_expectancy_usd":0.0},
        "years":[2023]})
    if report["read_only_production_review_eligible"]:
        raise AssertionError("EXPOST_SOURCE_CANNOT_UNLOCK_PRODUCTION")
    out["release_gate"]=report
    a.out.parent.mkdir(exist_ok=True,parents=True)
    a.out.write_text(json.dumps(out,indent=2,allow_nan=False)+"\n")
    print("FED_MACRO_REAL_XAU_PILOT",json.dumps({k:v for k,v in out.items()
                                              if k!="xau_source"}))
if __name__=="__main__":main()

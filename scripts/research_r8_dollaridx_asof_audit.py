"""R8 Dukascopy DOLLARIDXUSD M1 point-in-time provenance gate.

Offline, read-only, fail closed. Never downloads, fabricates, or forward-fills.
Expected CSV columns: timestamp,open,high,low,close,available_at.
Both timestamps MUST carry UTC offset. timestamp = M1 OPEN time;
available_at = when this completed M1 was observable by the strategy.
Manifest requires sha256_csv, instrument, provider, timestamp_semantics.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import pandas as pd

INSTRUMENT="DOLLARIDXUSD"
REQUIRED={"timestamp","open","high","low","close","available_at"}

def audit(path: Path, manifest_path: Path):
    raw=path.read_bytes()
    digest=hashlib.sha256(raw).hexdigest()
    manifest=json.loads(manifest_path.read_text())
    if manifest.get("sha256_csv") != digest:
        raise ValueError("SHA256_MISMATCH")
    if manifest.get("instrument","").upper()!=INSTRUMENT:
        raise ValueError("WRONG_INSTRUMENT")
    if manifest.get("provider")!="Dukascopy" or manifest.get("timestamp_semantics")!="M1_OPEN_UTC":
        raise ValueError("PROVENANCE_INCOMPLETE")
    df=pd.read_csv(path)
    if not REQUIRED.issubset(df):
        raise ValueError("MISSING_REQUIRED_COLUMNS")
    for key in ("timestamp","available_at"):
        s=df[key].astype(str)
        if not s.str.contains(r"(?:Z|[+-][0-9]{2}:[0-9]{2})$",regex=True).all():
            raise ValueError("MISSING_EXPLICIT_UTC_OFFSET_"+key)
        df[key]=pd.to_datetime(s,utc=True,errors="raise")
    if df.empty or df.timestamp.duplicated().any() or not df.timestamp.is_monotonic_increasing:
        raise ValueError("EMPTY_DUPLICATE_OR_UNSORTED")
    if ((df.timestamp.dt.second!=0)|(df.timestamp.dt.microsecond!=0)).any():
        raise ValueError("NON_MINUTE_OPEN")
    for c in ("open","high","low","close"):
        df[c]=pd.to_numeric(df[c],errors="raise")
    import numpy as np
    if not np.isfinite(df[["open","high","low","close"]].to_numpy()).all():
        raise ValueError("NONFINITE_PRICE")
    if ((df.high<df[["open","close","low"]].max(axis=1))|
        (df.low>df[["open","close"]].min(axis=1))|(df.low<=0)).any():
        raise ValueError("BAD_OHLC_GEOMETRY")
    close_at=df.timestamp+pd.Timedelta(minutes=1)
    if (df.available_at<close_at).any():
        raise ValueError("LOOKAHEAD_AVAILABLE_BEFORE_M1_CLOSE")
    if (df.available_at.diff().dropna()<pd.Timedelta(0)).any():
        raise ValueError("NONMONOTONIC_PUBLICATION")
    age=(df.available_at-close_at).dt.total_seconds()
    gap=(df.timestamp.diff().dropna()!=pd.Timedelta(minutes=1))
    # Gaps are reported, never interpolated; market closures must be labeled.
    return df,dict(contract="R8_DOLLARIDXUSD_M1_PROVENANCE_V1",
        sha256_csv=digest,rows=int(len(df)),
        first_open_utc=df.timestamp.iloc[0].isoformat(),
        last_open_utc=df.timestamp.iloc[-1].isoformat(),
        max_publication_lag_seconds=float(age.max()),
        median_publication_lag_seconds=float(age.median()),
        missing_minute_transitions=int(gap.sum()),
        market_closure_or_gap_unresolved=bool(gap.any()),
        valid_for_replay=not bool(gap.any()),
        caveat="Dukascopy dollar-index CFD proxy, NOT ICE DXY futures; requires separate XAU event file and as-of validation")

def causal_features(df, events, max_quote_age_seconds=90):
    """Only previously published M1 closes, never contemporaneous forming bars.

    events columns: event_at (UTC close timestamp); all M1 data must have
    timestamp OPEN, available_at publication time. Event order preserved.
    Reject unknown publication age instead of silently forward filling.
    """
    if "event_at" not in events: raise ValueError("MISSING_EVENT_TIME")
    events=events.copy()
    s=events.event_at.astype(str)
    if not s.str.contains(r"(?:Z|[+-][0-9]{2}:[0-9]{2})$",regex=True).all():
        raise ValueError("EVENT_TZ_REQUIRED")
    events["event_at"]=pd.to_datetime(s,utc=True)
    if events.event_at.duplicated().any(): raise ValueError("DUPLICATE_EVENT")
    available=df.copy()
    available["closed_at"]=available.timestamp+pd.Timedelta(minutes=1)
    # Rows with publication delays are eligible ONLY after available_at.
    available=available.sort_values("available_at")
    output=[]
    for t in events.event_at:
        valid=available.loc[(available.available_at<=t)&(available.closed_at<=t)]
        if valid.empty:
            output.append(dict(event_at=t.isoformat(),status="NO_DXY_ASOF"))
            continue
        last=valid.iloc[-1]
        age=(t-last.closed_at).total_seconds()
        if age<0 or age>max_quote_age_seconds:
            output.append(dict(event_at=t.isoformat(),status="STALE_DXY",quote_age_seconds=age))
            continue
        # Strictly contiguous M1 windows; no data gap, session closure, or
        # missing published candle may be bridged.
        by_close=valid.sort_values("closed_at").drop_duplicates("closed_at",keep="last")
        values={"event_at":t.isoformat(),"status":"OK","quote_age_seconds":age}
        for minutes in (5,15,60):
            w=by_close.tail(minutes+1)
            contiguous=(len(w)==minutes+1 and
                        (w.closed_at.diff().dropna()==pd.Timedelta(minutes=1)).all() and
                        (w.available_at<=t).all())
            values["dxy_direction_"+str(minutes)+"m"]=(
                "UP" if w.close.iloc[-1]>w.close.iloc[0] else
                "DOWN" if w.close.iloc[-1]<w.close.iloc[0] else "FLAT"
            ) if contiguous else None
        output.append(values)
    return pd.DataFrame(output)

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--csv",type=Path,required=True)
    p.add_argument("--manifest",type=Path,required=True)
    p.add_argument("--events",type=Path)
    p.add_argument("--out",type=Path,required=True)
    a=p.parse_args()
    df,report=audit(a.csv,a.manifest)
    if a.events:
        features=causal_features(df,pd.read_csv(a.events))
        report["event_rows"]=len(features)
        report["asof_ok"]=int((features.status=="OK").sum())
        report["all_5_15_60_available"]=int(features[["dxy_direction_5m","dxy_direction_15m","dxy_direction_60m"]].notna().all(axis=1).sum())
        report["feature_rows"]=features.to_dict(orient="records")
    a.out.parent.mkdir(parents=True,exist_ok=True)
    a.out.write_text(json.dumps(report,indent=2,allow_nan=False)+"\n")
    print(json.dumps({k:v for k,v in report.items() if k!="feature_rows"}))
if __name__=="__main__": main()

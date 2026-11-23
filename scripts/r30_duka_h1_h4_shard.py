"""Convert authenticated HTTPS Dukascopy-node H1 BID candles into UTC H1/H4.

No HistData TLS bypass, synthetic price imputation, cross-provider price splicing,
daily/W1 reconstruction, or broker order access. H4 requires exact four
consecutive completed H1 candles on the UTC 4-hour boundary.
"""
from __future__ import annotations
import argparse,hashlib,json
from datetime import UTC,datetime
from pathlib import Path
import numpy as np
import pandas as pd

PROVIDER="DUKASCOPY_NODE_1_51_1_H1_BID_PUBLIC"


def normalize(path,year,now=None):
    now=pd.Timestamp(now or datetime.now(UTC))
    if now.tzinfo is None:raise ValueError("DUKA_UTC_NOW_MUST_BE_AWARE")
    f=pd.read_csv(path)
    required={"timestamp","open","high","low","close"}
    if not required.issubset(f):
        raise ValueError("DUKA_CSV_COLUMNS_MISSING")
    if f.empty:raise ValueError("DUKA_CSV_EMPTY")
    ts=pd.to_datetime(f["timestamp"],unit="ms",utc=True,errors="coerce")
    if ts.isna().any() or ts.has_duplicates or not ts.is_monotonic_increasing:
        raise ValueError("DUKA_TIMESTAMP_INVALID")
    f=f.assign(timestamp=ts).set_index("timestamp")
    f=f.loc[(f.index.year==year)&(f.index+pd.Timedelta(hours=1)<=now),
            ["open","high","low","close"]].astype(float)
    f=f.rename(columns={"open":"o","high":"h","low":"l","close":"c"})
    if (f.empty or not np.isfinite(f.to_numpy()).all() or
            ((f.l<=0)|(f.h<f[["o","c","l"]].max(axis=1))
             |(f.l>f[["o","c"]].min(axis=1))).any()):
        raise ValueError("DUKA_OHLC_INVALID")
    if f.index.second.any() or f.index.minute.any() or f.index.microsecond.any():
        raise ValueError("DUKA_H1_TIMESTAMP_NOT_ALIGNED")
    # Required history completeness is based on months, not synthetic padding.
    month_counts={int(y):int(n) for y,n in f.groupby(f.index.month).size().items()}
    if len(month_counts)<(8 if year==2026 else 11):
        raise ValueError(f"DUKA_YEAR_MONTH_COVERAGE_INSUFFICIENT:{year}:{month_counts}")
    if any(n<120 for n in month_counts.values()):
        raise ValueError(f"DUKA_MONTH_H1_BARS_TOO_FEW:{year}:{month_counts}")
    h4=f.resample("4h",label="left",closed="left").agg(
        o=("o","first"),h=("h","max"),l=("l","min"),
        c=("c","last"),hours=("c","size"))
    # Count=4 also implies distinct consecutive H1 if the timestamps are
    # unique and aligned; reject incomplete Sunday/Friday sessions.
    h4=h4.loc[h4.hours==4]
    h4=h4.drop(columns="hours")
    if not len(h4)>=len(f)//8:raise ValueError("DUKA_H4_COMPLETENESS_LOW")
    return f,h4,month_counts


def run(year,raw):
    raw=Path(raw)
    if not raw.is_file() or raw.stat().st_size<30000:
        raise ValueError(f"DUKA_SOURCE_MISSING_OR_TOO_SHORT:{raw}")
    h1,h4,months=normalize(raw,year)
    out=Path("artifacts/r30");out.mkdir(parents=True,exist_ok=True)
    files={}
    for tf,data in (("1h",h1),("4h",h4)):
        name=f"r10-{tf}-{year}.csv"
        path=out/name;data.to_csv(path)
        files[tf]={"name":name,"sha256":hashlib.sha256(path.read_bytes()).hexdigest(),
                   "rows":len(data),"first":data.index[0].isoformat(),
                   "last":data.index[-1].isoformat()}
    metadata={
        "contract":"RIZAN_R30_DUKASCOPY_H1_H4_YEAR_V1",
        "source":PROVIDER,"year":year,"symbol":"XAUUSD",
        "price_side":"BID","utc_origin":"UNIX_EPOCH_MILLISECONDS",
        "raw_sha256":hashlib.sha256(raw.read_bytes()).hexdigest(),
        "source_files":files,"month_h1_counts":months,
        "validation":"UTC_PRECISE_CLOSED_H1_AND_4_CONTIGUOUS_H1_TO_H4",
        "research_only":True,"execution_authority":False,"execution_influence":False,
        "warning":"Dukascopy BID may differ from FP Markets cTrader, no broker parity or executable spread",
    }
    (out/f"r30-dukascopy-provenance-{year}.json").write_text(json.dumps(metadata,indent=2)+"\n")
    print(json.dumps({"stage":"R30_DUKA_SOURCE_VERIFIED","year":year,
                      "h1":len(h1),"h4":len(h4),
                      "month_count":len(months),
                      "sha256":metadata["raw_sha256"]}),flush=True)
    return metadata


if __name__=="__main__":
    a=argparse.ArgumentParser()
    a.add_argument("--year",type=int,required=True)
    a.add_argument("--csv",required=True)
    args=a.parse_args()
    if not 2012<=args.year<=2026:raise SystemExit("R30_YEAR_OUT_OF_SCOPE")
    run(args.year,args.csv)

"""R32: verified Dukascopy XAUUSD BID M5 calendar-year source (research only).

No synthetic candles, weekend fills, TLS bypass, or cTrader order access.
Data is a PUBLIC secondary quote feed and not certified FP Markets pricing.
"""
from __future__ import annotations
import argparse,hashlib,json
from datetime import UTC,datetime
from pathlib import Path
import numpy as np
import pandas as pd

CONTRACT="RIZAN_R32_DUKASCOPY_M5_YEAR_V1"
PROVIDER="DUKASCOPY_NODE_1_51_1_XAUUSD_M5_BID"
OUT=Path("artifacts/r32")


def normalize(csv,year,*,asof=None):
    now=pd.Timestamp(asof or datetime.now(UTC))
    if now.tzinfo is None:raise ValueError("R32_NOW_NAIVE")
    f=pd.read_csv(csv)
    needed={"timestamp","open","high","low","close"}
    if not needed.issubset(f.columns):raise ValueError("R32_M5_FIELDS_MISSING")
    if f.empty:raise ValueError("R32_M5_SOURCE_EMPTY")
    ts=pd.to_datetime(f.timestamp,unit="ms",utc=True,errors="coerce")
    if ts.isna().any() or not ts.is_unique or not ts.is_monotonic_increasing:
        raise ValueError("R32_M5_TIMESTAMP_INVALID")
    if (ts.dt.minute.mod(5)!=0).any() or ts.dt.second.any():
        raise ValueError("R32_M5_TIMESTAMP_NOT_ALIGNED")
    f=f.assign(timestamp=ts).set_index("timestamp")
    f=f.loc[(f.index.year==year)&(f.index+pd.Timedelta(minutes=5)<=now),
            ["open","high","low","close"]].astype("float64")
    f=f.rename(columns={"open":"o","high":"h","low":"l","close":"c"})
    if f.empty or not np.isfinite(f.to_numpy()).all():
        raise ValueError("R32_M5_NONFINITE")
    bad=(f.l<=0)|(f.h<f[["o","c","l"]].max(axis=1))|(f.l>f[["o","c"]].min(axis=1))
    if bad.any():raise ValueError("R32_M5_PRICE_GEOMETRY")
    raw_rows=len(f)
    weekend=(f.index.dayofweek>=5)
    weekend_removed=int(weekend.sum())
    f=f.loc[~weekend]
    flat=(f.h-f.l).abs()<1e-9
    flat_removed=int(flat.sum())
    f=f.loc[~flat]
    if f.empty or len(f)<raw_rows*.40:raise ValueError("R32_M5_TRADEABLE_COVERAGE_TOO_LOW")
    months={str(k):int(v) for k,v in f.groupby(f.index.month).size().items()}
    required_months=8 if year==2026 else 11
    if len(months)<required_months or any(v<500 for v in months.values()):
        raise ValueError(f"R32_M5_MONTH_COVERAGE:{year}:{months}")
    if f.index.has_duplicates or not f.index.is_monotonic_increasing:
        raise ValueError("R32_M5_NORMALIZED_INDEX_INVALID")
    return f,{
        "raw_rows":raw_rows,"weekend_removed":weekend_removed,
        "flat_removed":flat_removed,"trading_session_rows":len(f),
        "months":months,
        "partial_2026":year==2026,
        "missing_intervals_not_interpolated":True
    }


def run(year,csv):
    path=Path(csv)
    if year<2012 or year>2026:raise ValueError("R32_YEAR_OUT_OF_RANGE")
    if not path.is_file() or path.stat().st_size<20000:
        raise ValueError("R32_M5_RAW_MISSING_OR_TOO_SMALL")
    frame,audit=normalize(path,year)
    OUT.mkdir(parents=True,exist_ok=True)
    target=OUT/f"r32-m5-{year}.csv.gz"
    frame.to_csv(target,compression={"method":"gzip","compresslevel":5,"mtime":0})
    receipt={
        "contract":CONTRACT,"source":PROVIDER,
        "year":year,"symbol":"XAUUSD","side":"BID",
        "timestamp_convention":"UTC_UNIX_EPOCH_MILLISECONDS",
        "data_window":"2012-01-01--2026-11-24_partial",
        "first_bar_open":frame.index[0].isoformat(),
        "last_bar_open":frame.index[-1].isoformat(),
        "raw_sha256":hashlib.sha256(path.read_bytes()).hexdigest(),
        "normalized_sha256":hashlib.sha256(target.read_bytes()).hexdigest(),
        "output_file":target.name,"source_audit":audit,
        "execution_authority":False,"execution_influence":False,
        "research_only":True,
        "limitations":[
            "Public Dukascopy BID prices, not FP Markets cTrader fills or verified spread",
            "Weekend/flat candles excluded; missing intraday bars never forward filled",
            "2026 is partial through the latest available completed candle",
        ]
    }
    (OUT/f"r32-source-{year}.json").write_text(json.dumps(receipt,indent=2)+"\n")
    print(json.dumps({"stage":"R32_SOURCE_READY","year":year,
                      "rows":len(frame),"source_audit":audit,
                      "sha256":receipt["normalized_sha256"]}),flush=True)
    return receipt

if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--year",type=int,required=True)
    ap.add_argument("--csv",required=True)
    args=ap.parse_args()
    run(args.year,args.csv)

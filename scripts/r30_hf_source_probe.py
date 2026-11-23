"""R30 audit probe for alternate independent XAUUSD 2012-2018 source.

Downloaded only from publicly documented Hugging Face source at an HTTPS
verified origin. No personal credentials and no proprietary order signals.
This is a provenance/price-scale QUALITY CHECK, not a training claim.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import urllib.request
from pathlib import Path
import numpy as np
import pandas as pd

REPO="TheFinanceEngineer/impulse-market-data"
URL="https://huggingface.co/datasets/"+REPO+"/resolve/main/data/XAUUSD/XAUUSD_{year}.parquet"


def probe(year,out):
    if year not in range(2012,2027):raise ValueError("R30_HF_YEAR_OUT_OF_RANGE")
    path=Path(out)
    path.parent.mkdir(parents=True,exist_ok=True)
    req=urllib.request.Request(URL.format(year=year),
        headers={"User-Agent":"RIZAN-R30-research-readonly/1"})
    with urllib.request.urlopen(req,timeout=90) as response, path.open("wb") as fp:
        total=0
        while True:
            block=response.read(1024*1024)
            if not block:break
            total+=len(block)
            if total>80_000_000:raise ValueError("R30_HF_FILE_UNEXPECTEDLY_LARGE")
            fp.write(block)
    if path.stat().st_size<100_000:raise ValueError("R30_HF_FILE_TOO_SMALL")
    h=hashlib.sha256(path.read_bytes()).hexdigest()
    df=pd.read_parquet(path)
    report={
      "source":REPO,"url":URL.format(year=year),"year":year,
      "sha256":h,"size_bytes":path.stat().st_size,
      "shape":list(df.shape),"columns":list(df.columns),
      "dtypes":{k:str(v) for k,v in df.dtypes.items()},
      "first_rows":df.head(3).astype(str).to_dict("records"),
      "last_rows":df.tail(2).astype(str).to_dict("records"),
      "execution_authority":False
    }
    for k in ("timestamp","time","datetime","Date","date","ts"):
        if k in df.columns:
            times=pd.to_datetime(df[k],utc=True,errors="coerce",unit="s" if k in ("ts","timestamp") and pd.api.types.is_numeric_dtype(df[k]) else None)
            report["timestamp_field"]=k
            report["ts_monotonic"]=bool(times.is_monotonic_increasing)
            report["ts_duplicates"]=int(times.duplicated().sum())
            report["year_counts"]={str(y):int(n) for y,n in times.dt.year.value_counts().sort_index().items()}
            report["timestamp_first"]=str(times.min())
            report["timestamp_last"]=str(times.max())
            report["median_diff_seconds"] = float(times.sort_values().diff().dt.total_seconds().median())
            break
    print(json.dumps(report,default=str),flush=True)
    (path.parent/f"r30-source-probe-{year}.json").write_text(
        json.dumps(report,indent=2,default=str)+"\n")
    return report


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--year",type=int,required=True)
    p.add_argument("--output",required=True)
    a=p.parse_args()
    probe(a.year,a.output)

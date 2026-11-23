"""RIZAN R30: audit-preserving XAU H1/H4 backfill from original HistData M1.

The provider code has already normalized FIXED_EST to UTC and has a
per-year original M1 source hash. This writes only compact completed
H1/H4 OHLC and an explicit per-year quality manifest. Never broker orders.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd

REQUIRED=("timestamp","open","high","low","close")
CONTRACT="R30_XAUUSD_HISTDATA_H1_H4_UTC_2012_2018_SHARD_V1"

def checksum(path):
    h=hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):h.update(chunk)
    return h.hexdigest()

def build(source,prov_file,output,year):
    source=Path(source);prov_file=Path(prov_file);output=Path(output)
    prov=json.loads(prov_file.read_text())
    if (year not in range(2012,2019)
            or prov.get("year")!=year
            or prov.get("contract")!="XAU_HISTDATA_M1_SHARD_V193_1"
            or prov.get("source")!="HISTDATA_XAUUSD_M1"
            or prov.get("source_timestamp_contract")!="FIXED_EST_UTC_MINUS5_NO_DST"
            or prov.get("execution_authority") is not False
            or prov.get("normalized_csv_sha256")!=checksum(source)):
        raise ValueError("R30_HISTDATA_SOURCE_NOT_PROVEN")
    d=pd.read_csv(source)
    if not set(REQUIRED).issubset(d):raise ValueError("R30_M1_MISSING_OHLC")
    d.index=pd.to_datetime(d.pop("timestamp"),utc=True)
    if not d.index.is_monotonic_increasing or not d.index.is_unique:
        raise ValueError("R30_M1_TS_NOT_UNIQUE_SORTED")
    if d.index.tz is None or d.index.year.min()>year or d.index.year.max()<year:
        raise ValueError("R30_M1_TIME_RANGE_INVALID")
    if d[list(REQUIRED[1:])].isna().any().any():
        raise ValueError("R30_M1_NAN")
    if ((d.high<d.low)|(d.high<d[["open","close"]].max(axis=1))|
        (d.low>d[["open","close"]].min(axis=1))).any():
        raise ValueError("R30_M1_OHLC_INVALID")
    output.mkdir(parents=True,exist_ok=True)
    shards={}
    for tf,minimum in (("1h",40),("4h",160)):
        agg=d.resample(tf,closed="left",label="left").agg(
            o=("open","first"),h=("high","max"),l=("low","min"),
            c=("close","last"),minutes=("close","count")
        )
        bars=agg.loc[(agg.minutes>=minimum)&(agg.index.year==year)].copy()
        if bars.empty or len(bars)<(800 if tf=="1h" else 200):
            raise ValueError("R30_SOURCE_YEAR_INSUFFICIENT_"+tf)
        if not ((bars.h>=bars[["o","c"]].max(axis=1)) &
                (bars.l<=bars[["o","c"]].min(axis=1))&
                (bars.h>=bars.l)&bars.index.is_unique).all():
            raise ValueError("R30_RESAMPLED_OHLC_INVALID_"+tf)
        file=output/f"r10-{tf}-{year}.csv"
        bars.to_csv(file)
        shards[tf]={
            "file":file.name, "rows":len(bars),
            "sha256":checksum(file),"first":bars.index[0].isoformat(),
            "last":bars.index[-1].isoformat(),
            "minimum_complete_minutes":minimum,
            "observed_year":year,
            "minutes_min":int(bars.minutes.min()),
        }
    report={
        "contract":CONTRACT,"year":year,"symbol":"XAUUSD",
        "source_provenance_sha256":checksum(prov_file),
        "normalized_source_sha256":prov["normalized_csv_sha256"],
        "provider_commit":prov["provider_commit"],
        "source_timestamp_contract":prov["source_timestamp_contract"],
        "failed_periods":prov.get("failed_periods",[]),
        "fetched_periods":prov.get("fetched_periods",[]),
        "shards":shards,"research_only":True,
        "execution_authority":False,"execution_influence":False,
    }
    (output/f"r30-backfill-provenance-{year}.json").write_text(
        json.dumps(report,indent=2,allow_nan=False)+"\n")
    print(json.dumps({"year":year,"source":prov["normalized_csv_sha256"],
                      "bars":{tf:q["rows"] for tf,q in shards.items()},
                      "failed_periods":len(report["failed_periods"])}),flush=True)
    return report

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--source",type=Path,required=True)
    p.add_argument("--provenance",type=Path,required=True)
    p.add_argument("--year",type=int,required=True)
    p.add_argument("--output",type=Path,default=Path("artifacts/r30_backfill"))
    a=p.parse_args()
    build(a.source,a.provenance,a.output,a.year)

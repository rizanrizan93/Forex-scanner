"""R30 XAU 2012–2026 uniform *external* Parquet source (research only).

Separate from HistData R10, preserves source commit and SHA256. Downloads
public HF XAUUSD minute OHLC with normal TLS verification and explicit
UNIX SECONDS -> UTC minute timestamps. Does NOT claim this redistributed
price source is FP Markets broker history or identical to HistData.
"""
from __future__ import annotations
import argparse,hashlib,json,re
from pathlib import Path
from urllib.request import Request,urlopen

import numpy as np
import pandas as pd

DATASET="TheFinanceEngineer/impulse-market-data"
API="https://huggingface.co/api/datasets/"+DATASET
ROOT="https://huggingface.co/datasets/"+DATASET+"/resolve/{sha}/data/XAUUSD/XAUUSD_{year}.parquet"
CONTRACT="R30_HF_XAUUSD_M1_TO_H1_H4_UTC_YEAR_V1"
MIN_BARS={"1h":500,"4h":120}

def checksum(path):
    h=hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda:f.read(1048576),b""):h.update(block)
    return h.hexdigest()

def revision(*,opener=urlopen):
    req=Request(API,headers={"User-Agent":"RIZAN-R30-XAU-quant-readonly/1"})
    with opener(req,timeout=40) as f:p=json.load(f)
    sha=p.get("sha")
    if not isinstance(sha,str) or not re.fullmatch(r"[0-9a-f]{40}",sha):
        raise ValueError("R30_HF_SOURCE_COMMIT_NOT_PINNED")
    return sha

def download(year,path,commit,*,opener=urlopen):
    if year not in range(2012,2027):raise ValueError("R30_HF_YEAR_INVALID")
    if not re.fullmatch(r"[0-9a-f]{40}",commit):
        raise ValueError("R30_HF_PINNED_SHA_REQUIRED")
    url=ROOT.format(sha=commit,year=year)
    req=Request(url,headers={"User-Agent":"RIZAN-R30-XAU-quant-readonly/1"})
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    size=0
    with opener(req,timeout=120) as resp,path.open("wb") as fp:
        while True:
            buf=resp.read(1048576)
            if not buf:break
            size+=len(buf)
            if size>80_000_000:raise ValueError("R30_HF_FILE_OVERSIZE")
            fp.write(buf)
    if size<100_000:raise ValueError("R30_HF_DOWNLOAD_TOO_SMALL")
    return url

def build(year,input_path,outdir,commit,url):
    outdir=Path(outdir)
    source=Path(input_path)
    original_hash=checksum(source)
    a=pd.read_parquet(source)
    need={"timestamp","open","high","low","close"}
    if not need.issubset(a.columns):raise ValueError("R30_HF_PRICE_COLUMNS_INVALID")
    if (len(a)<90_000 or not pd.api.types.is_integer_dtype(a.timestamp)):
        raise ValueError("R30_HF_DATA_NOT_ONE_MINUTE_UNIX_SECONDS")
    dt=pd.to_datetime(a.timestamp,unit="s",utc=True,errors="coerce")
    if (dt.isna().any() or not dt.is_monotonic_increasing
            or dt.duplicated().any()
            or int(dt.iloc[0].year)!=year or int(dt.iloc[-1].year)!=year):
        raise ValueError("R30_HF_MINUTE_TIMESTAMPS_YEAR_INVALID")
    nmin=int((dt.diff().dt.total_seconds().iloc[1:]==60).sum())
    if nmin/max(1,len(a)-1)<.90:
        raise ValueError("R30_HF_NOT_REGULAR_MINUTE_SERIES")
    df=a.loc[:,["open","high","low","close"]].copy()
    df.index=pd.DatetimeIndex(dt)
    if (df.isna().any().any()
            or not np.isfinite(df.to_numpy(float)).all()
            or (df.high<df.low).any()
            or (df.high<df[["open","close"]].max(axis=1)).any()
            or (df.low>df[["open","close"]].min(axis=1)).any()
            or (df.low<=0).any()):
        raise ValueError("R30_HF_INVALID_PRICE_DATA")
    outdir.mkdir(parents=True,exist_ok=True)
    children={}
    for tf,minimum in (("1h",40),("4h",160)):
        q=df.resample(tf,closed="left",label="left").agg(
            o=("open","first"),h=("high","max"),l=("low","min"),
            c=("close","last"),minutes=("close","count"))
        q=q[(q.minutes>=minimum)&(q.index.year==year)]
        if len(q)<MIN_BARS[tf]:
            raise ValueError("R30_HF_INSUFFICIENT_CLOSED_CANDLES_"+tf)
        if (q.index.tz is None or not q.index.is_monotonic_increasing
                or (q.h<q[["o","c"]].max(axis=1)).any()
                or (q.l>q[["o","c"]].min(axis=1)).any()):
            raise ValueError("R30_HF_CANDLE_PRICE_INVALID_"+tf)
        out=outdir/f"r10-{tf}-{year}.csv"
        q.to_csv(out)
        children[tf]={
            "file":out.name,"sha256":checksum(out),"rows":len(q),
            "source_minute_threshold":minimum,
            "first_utc":q.index.min().isoformat(),
            "last_utc":q.index.max().isoformat(),
        }
    manifest={
        "contract":CONTRACT,
        "symbol":"XAUUSD","year":year,
        "source_dataset":DATASET,
        "source_commit":commit,
        "source_url":url,"source_file_sha256":original_hash,
        "source_minute_rows":len(df),"native_timestamp":"UNIX_SECONDS_UTC",
        "first_utc":dt.iloc[0].isoformat(),
        "last_utc":dt.iloc[-1].isoformat(),
        "one_minute_fraction":nmin/max(1,len(df)-1),
        "candle_aggregation":"UTC_OPEN_ANCHORED_00",
        "price_quote_kind":"UNVERIFIED_EXTERNAL_OHLC",
        "vendor_homogeneity":"UNIFORM_FOR_2012_TO_2026_ONLY",
        "derivatives":children,
        "execution_authority":False,"execution_influence":False,
        "research_only":True,
    }
    dest=outdir/f"r30-hf-provenance-{year}.json"
    dest.write_text(json.dumps(manifest,indent=2,allow_nan=False)+"\n")
    print(json.dumps({
        "year":year,"source_sha":original_hash,"minute_rows":len(df),
        "commit":commit,"H1":children["1h"]["rows"],"H4":children["4h"]["rows"],
        "first":manifest["first_utc"],"last":manifest["last_utc"]
    }),flush=True)
    return manifest

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--year",type=int,required=True)
    p.add_argument("--out",type=Path,default=Path("artifacts/r30_uniform"))
    a=p.parse_args()
    commit=revision()
    source=Path(f"/tmp/r30-hf-{a.year}.parquet")
    url=download(a.year,source,commit)
    build(a.year,source,a.out,commit,url)

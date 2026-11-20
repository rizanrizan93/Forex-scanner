"""Research-only USD 6FX geometric index reconstructed from HistData M1 quotes.

This is NOT a licensed ICE USDX or Dukascopy DOLLARIDXUSD. Uses published
currency basket weights but independently sourced, asynchronous spot candles.
No bid/ask synchrony and no 2019 point-in-time first_seen audit; explicit lag
scenarios are necessary. Missing pairs/minutes are dropped, never forward-filled.
"""
from __future__ import annotations
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd

WEIGHTS={"EURUSD":-.576,"USDJPY":.136,"GBPUSD":-.119,
         "USDCAD":.091,"USDSEK":.042,"USDCHF":.036}
CONST=50.14348112
SOURCE_CONTRACT="R8_RECONSTRUCTED_DXY_6FX_HISTDATA_V1"
INSTRUMENT="RECONSTRUCTED_DXY_6FX_HISTDATA"
AVAILABILITY="HISTORICAL_FIRST_SEEN_UNKNOWN_ASSUMED_LAG_ONLY"
EXECUTION_AUTHORITY=False
EXECUTION_INFLUENCE=False

def sha(path):
    digest=hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):digest.update(chunk)
    return digest.hexdigest()

def reconstruct(frames:dict[str,pd.DataFrame])->pd.DataFrame:
    """True pointwise common timestamps; gaps stay gaps; no fake intrabar wick."""
    if set(frames)!=set(WEIGHTS):raise ValueError('SIX_FX_PAIRS_REQUIRED')
    logs=[]
    for pair,power in WEIGHTS.items():
        x=frames[pair]
        if x.empty or not {"timestamp","close"}.issubset(x.columns):
            raise ValueError(f'MISSING_FX_M1:{pair}')
        t=pd.to_datetime(x.timestamp,utc=True,errors="raise")
        if t.duplicated().any() or not t.is_monotonic_increasing:raise ValueError(f'INVALID_FX_TIME:{pair}')
        v=pd.to_numeric(x.close,errors="raise").to_numpy(float)
        if not np.isfinite(v).all() or np.any(v<=0):raise ValueError(f'INVALID_FX_CLOSE:{pair}')
        logs.append(pd.Series(np.log(v)*power,index=pd.DatetimeIndex(t),name=pair))
    basket=pd.concat(logs,axis=1,join="inner").dropna()
    if basket.empty:raise ValueError('NO_SIX_PAIR_COMMON_MINUTES')
    c=np.exp(np.log(CONST)+basket.sum(axis=1).to_numpy())
    if not np.isfinite(c).all() or np.any(c<=0):raise ValueError('INVALID_SYNTHETIC_INDEX')
    # Close-to-close index. OHLC envelope is NOT genuine intrabar high/low.
    o=np.r_[c[0],c[:-1]]
    # At an ordinary discontinuity the previous close is stale: use current close
    # for OPEN instead; R8 scorer only uses timestamp and CLOSE.
    continuous=basket.index.to_series().diff().eq(pd.Timedelta(minutes=1)).to_numpy()
    o[~continuous]=c[~continuous]
    out=pd.DataFrame({"timestamp":basket.index.strftime('%Y-%m-%dT%H:%M:%SZ'),
                      "open":o,"high":np.maximum(o,c),"low":np.minimum(o,c),
                      "close":c})
    return out

def acquire(year:int,out:Path):
    from histdata_fetcher import fetch_data
    from fx_scanner.research_xau_histdata_download_v193 import _normalize_frame,PROVIDER_COMMIT
    if not 2019<=year<=dt.datetime.now(dt.timezone.utc).year:raise ValueError('YEAR_OUT_OF_RANGE')
    first=dt.date(year,1,1)
    end=min(dt.datetime.now(dt.timezone.utc).date(),dt.date(year,12,31))
    frames={};sources=[]
    out.mkdir(parents=True,exist_ok=True)
    for pair in WEIGHTS:
        fetch=fetch_data(pair=pair,start_date=first,end_date=end,timeframe='1min',
                         output_format=None,max_workers=1)
        if fetch.data.empty:raise RuntimeError(f'EMPTY_MARKET_SOURCE:{pair}')
        failed=[{"start":str(x.period_start),"end":str(x.period_end),"reason":str(x.reason)}
                for x in fetch.failed_periods]
        if failed:raise RuntimeError(f'FAILED_MARKET_PERIODS:{pair}:{failed[:3]}')
        df=_normalize_frame(fetch.data)
        df=df[(pd.to_datetime(df.timestamp,utc=True).dt.year==year)].reset_index(drop=True)
        if len(df)<5000:raise RuntimeError(f'INSUFFICIENT_SOURCE_M1:{pair}:{len(df)}')
        dfpath=out/f'fx_{pair}_m1_{year}.csv'
        df.to_csv(dfpath,index=False)
        sources.append({"pair":pair,"rows":int(len(df)),"normalized_sha256":sha(dfpath),
                        "fetched_periods":list(fetch.fetched_periods),"failed_periods":failed,
                        "data_time_basis":"HISTDATA_FIXED_EST_UTC_MINUS5"})
        frames[pair]=df
        print("R8_FX6_PAIR",year,pair,len(df),flush=True)
    usd=reconstruct(frames)
    path=out/f'r8_reconstructed_usd6_{year}.csv'
    usd.to_csv(path,index=False)
    gaps=int((pd.to_datetime(usd.timestamp,utc=True).diff().dropna()!=pd.Timedelta(minutes=1)).sum())
    prov={"contract":SOURCE_CONTRACT,"instrument":INSTRUMENT,"year":year,
          "provider":"HistData","provider_package":"histdata-fetcher",
          "provider_commit":PROVIDER_COMMIT,"component_sources":sources,
          "source_timestamp_semantics":"FIXED_EST_MINUS5_CONVERTED_TO_M1_OPEN_UTC",
          "synthetic_index_definition":"ICE_WEIGHTED_FORMULA_APPLIED_TO_INDEPENDENT_6FX_M1_CLOSE",
          "valid_intrabar_high_low":False,"availability_model":AVAILABILITY,
          "csv_sha256":sha(path),"rows":len(usd),"gap_transitions":gaps,
          "days_ok":int(pd.to_datetime(usd.timestamp,utc=True).dt.date.nunique()),
          "missing_weekdays":None,"execution_authority":False,"execution_influence":False}
    manifest=out/f'r8_reconstructed_usd6_{year}_provenance.json'
    manifest.write_text(json.dumps(prov,indent=2,default=str)+"\n")
    return path,manifest,prov

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--year',type=int,required=True)
    p.add_argument('--out',type=Path,default=Path('/tmp/r8-fx6'))
    args=p.parse_args()
    path,manifest,prov=acquire(args.year,args.out)
    print("R8_FX6_YEAR_READY",json.dumps({"year":args.year,"rows":prov["rows"],
          "sha256":prov["csv_sha256"],"gap_transitions":prov["gap_transitions"]}))
if __name__=="__main__":main()
